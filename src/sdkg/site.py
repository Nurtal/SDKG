"""Generate the static website from a release (ADR-0009)."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from sdkg.package import load

ASSETS = Path(__file__).parent / "site_assets"
CLAIM_FIELDS = (
    "claim_id", "layer", "claim_status", "evidence_level", "extraction_reliability", "sign", "negated",
    "species", "tissue", "population", "assay", "evidence_model", "biomarker_role", "source",
    "pmid", "span_text", "trial_phase", "trial_status", "endpoint",
)
DOWNLOADS = ("graph.graphml", "edges_all.tsv", "edges_core.tsv", "edges_core_human.tsv", "nodes.tsv", "triples.tsv", "graph.nt", "graph.jsonld", "collapse_rules.json")


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")


def _file_name(entity_id: str) -> str:
    return hashlib.sha256(entity_id.encode()).hexdigest()[:32] + ".json"


def run_site(release: str | Path, out: str | Path, data_notice: str | None = None, downloads_url: str | None = None) -> None:
    loaded = load(release)
    if not loaded.metadata.get("publishable"):
        raise ValueError("This release is not publishable, because some source licences are unconfirmed")

    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "data/entities").mkdir(parents=True)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copyfile(ASSETS / name, out / name)
    (out / ".nojekyll").write_text("", "utf-8")

    entities = {
        row["entity_id"]: row
        for row in loaded._rows(f"SELECT * FROM read_parquet('{loaded._parquet('entities')}')")
    }
    claims = loaded.claims()
    grouped: dict[str, dict[tuple, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for claim in claims:
        view = {field: claim.get(field) for field in CLAIM_FIELDS}
        grouped[claim["subject"]][(claim["predicate"], claim["object"], "out")].append(view)
        grouped[claim["object"]][(claim["predicate"], claim["subject"], "in")].append(view)

    index = []
    for entity_id in sorted(entities):
        entity = entities[entity_id]
        relationships = [
            {
                "predicate": predicate,
                "other": {"id": other, "label": entities[other]["label"]},
                "direction": direction,
                "claims": sorted(members, key=lambda c: c["claim_id"]),
            }
            # Disease core relationships come first, because they are about the disease.
            for (predicate, other, direction), members in sorted(
                grouped[entity_id].items(),
                key=lambda item: (not any(c["layer"] == "disease_core" for c in item[1]), item[0]),
            )
        ]
        name = _file_name(entity_id)
        _write(out / "data/entities" / name, {
            "id": entity_id, "label": entity["label"], "category": entity["category"],
            "resolved": entity["resolved"], "relationships": relationships,
        })
        index.append({
            "id": entity_id, "label": entity["label"], "file": name,
            "claims": sum(len(r["claims"]) for r in relationships),
        })
    _write(out / "data/index.json", {"entities": index})

    if downloads_url:
        downloads: dict[str, Any] = {"url": downloads_url}
    else:
        (out / "downloads").mkdir()
        for name in DOWNLOADS:
            shutil.copyfile(Path(release) / "exports" / name, out / "downloads" / name)
        downloads = {"files": list(DOWNLOADS)}
    _write(out / "data/release.json", {
        "version": loaded.metadata["version"], "claims": len(claims), "entities": len(entities),
        "data_notice": data_notice, "downloads": downloads,
    })
