"""Build the mention-to-identifier lexicon from frozen snapshots (issue #31)."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from sdkg.licences import LicenceManifest
from sdkg.normalise import normal_form

HYPHENATED_SYMBOL = re.compile(r"([A-Z]{2,5})(\d{1,3})")
MIN_MENTION_LENGTH = 3  # Shorter names are mostly collisions with other concepts.
XREF_PREFIXES = {"Orphanet": "ORPHA", "ORPHA": "ORPHA", "OMIM": "OMIM"}  # Used by the HPO annotations.


class Entry(NamedTuple):
    mention: str
    entity_id: str
    label: str
    category: str
    primary: bool = False  # An approved symbol or name beats another gene's alias.


def _accession_map(entries: Iterable[Entry]) -> dict[str, str]:
    return {e.mention: e.entity_id for e in entries if e.entity_id.startswith("HGNC:")}


def read_hgnc(path: Path, entry: dict[str, Any], known: dict[str, list[Entry]]) -> Iterable[Entry]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["status"] != "Approved":
                continue
            names = [row["symbol"], row["name"]]
            # IL21 is usually written IL-21 in abstracts.
            hyphenated = HYPHENATED_SYMBOL.fullmatch(row["symbol"])
            if hyphenated:
                names.append(f"{hyphenated.group(1)}-{hyphenated.group(2)}")
            for name in names:
                yield Entry(name, row["hgnc_id"], row["symbol"], "gene_or_protein", True)
            for field in ("alias_symbol", "prev_symbol", "uniprot_ids"):
                for name in (row.get(field) or "").strip('"').split("|"):
                    if name:
                        yield Entry(name, row["hgnc_id"], row["symbol"], "gene_or_protein", False)


def read_obo(path: Path, entry: dict[str, Any], known: dict[str, list[Entry]]) -> Iterable[Entry]:
    """OBO Graphs JSON, keeping this ontology's own current classes, labels and exact synonyms."""
    prefix = entry["prefix"]
    marker = f"/obo/{prefix}_"
    for graph in json.loads(path.read_text("utf-8"))["graphs"]:
        for node in graph["nodes"]:
            meta = node.get("meta") or {}
            label = node.get("lbl")
            if node.get("type") != "CLASS" or marker not in node["id"] or meta.get("deprecated") or not label:
                continue
            entity_id = f"{prefix}:{node['id'].split(marker)[1]}"
            names = [label] + [s["val"] for s in meta.get("synonyms") or [] if s.get("pred") == "hasExactSynonym"]
            for name in names:
                yield Entry(name, entity_id, label, entry["category"])
                if entry.get("plurals") and not name.endswith("s"):
                    yield Entry(name + "s", entity_id, label, entry["category"])
            if entry.get("xrefs"):
                for xref in meta.get("xrefs") or []:
                    scheme, _, local = xref.get("val", "").partition(":")
                    if scheme in XREF_PREFIXES and local:
                        yield Entry(f"{scheme}:{local}", entity_id, label, entry["category"])
                        yield Entry(f"{XREF_PREFIXES[scheme]}:{local}", entity_id, label, entry["category"])


def read_chembl_molecules(path: Path, entry: dict[str, Any], known: dict[str, list[Entry]]) -> Iterable[Entry]:
    for molecule in json.loads(path.read_text("utf-8"))["molecules"]:
        chembl_id = molecule["molecule_chembl_id"]
        name = molecule.get("pref_name")
        if not name:
            continue
        entity_id = f"CHEMBL:{chembl_id.removeprefix('CHEMBL')}"
        yield Entry(name, entity_id, name, "drug")
        for synonym in molecule.get("molecule_synonyms") or []:
            yield Entry(synonym["molecule_synonym"], entity_id, name, "drug")


def read_chembl_targets(path: Path, entry: dict[str, Any], known: dict[str, list[Entry]]) -> Iterable[Entry]:
    """Map a target to a gene only when it is one protein, so that complexes are never misread as one gene."""
    genes = _accession_map(known["hgnc"]) if "hgnc" in known else {}
    labels = {e.entity_id: e.label for e in known.get("hgnc", [])}
    for target in json.loads(path.read_text("utf-8"))["targets"]:
        components = target.get("target_components") or []
        if len(components) != 1:
            continue
        gene = genes.get(components[0].get("accession"))
        if gene:
            yield Entry(target["target_chembl_id"], gene, labels[gene], "gene_or_protein")


ADAPTERS = {
    "hgnc": read_hgnc,
    "obo": read_obo,
    "chembl_molecules": read_chembl_molecules,
    "chembl_targets": read_chembl_targets,
}


def _read_curated(path: Path) -> list[Entry]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [Entry(r["mention"], r["entity_id"], r["label"], r["category"]) for r in rows]


def build_lexicon(config_path: str | Path, licences: str | Path, out: str | Path, allow_unconfirmed: bool = False) -> None:
    config_path = Path(config_path)
    config = json.loads(config_path.read_text("utf-8"))
    root = config_path.parent
    sources = config["sources"]
    publishable = LicenceManifest.read(licences).check([s["source"] for s in sources], allow_unconfirmed)

    # form -> group -> first source's entity. Within a group, sources are listed in priority order.
    by_group: dict[str, dict[str, set[tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(set))
    known: dict[str, list[Entry]] = {}
    report_sources = []
    for source in sources:
        path = root / source["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"The {source['source']} snapshot does not match its recorded hash")
        entries = [e for e in ADAPTERS[source["adapter"]](path, source, known) if len(e.mention.strip()) >= MIN_MENTION_LENGTH]
        primary_forms = {normal_form(e.mention) for e in entries if e.primary}
        known.setdefault(source["source"], []).extend(entries)
        added = 0
        group = by_group[source["group"]]
        claimed = {form for form, entities in group.items() if entities}
        for entry in entries:
            form = normal_form(entry.mention)
            if form in primary_forms and not entry.primary:
                continue
            if form not in claimed:
                group[form].add((entry.entity_id, entry.label, entry.category))
                added += 1
        report_sources.append({
            "source": source["source"], "adapter": source["adapter"], "version": source["version"],
            "sha256": digest, "mentions": added,
        })

    curated = _read_curated(root / config["curated"]) if config.get("curated") else []
    settled: dict[str, tuple[str, str, str]] = {normal_form(e.mention): (e.entity_id, e.label, e.category) for e in curated}

    merged: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for group in by_group.values():
        for form, entities in group.items():
            merged[form] |= entities
    for form, entity in settled.items():
        merged[form] = {entity}

    # Whitespace inside a label would break the one-line-per-mention format.
    rows = sorted((form, entity[0], " ".join(entity[1].split()), entity[2]) for form, entities in merged.items() for entity in entities)
    ambiguous = [
        {"mention": form, "entity_ids": sorted(e[0] for e in entities)}
        for form, entities in sorted(merged.items()) if len({e[0] for e in entities}) > 1
    ]

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "lexicon.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writerow(["mention", "entity_id", "label", "category"])
        writer.writerows(rows)
    report = {
        "publishable": publishable, "sources": report_sources, "curated_mentions": len(settled),
        "mentions": len(merged), "ambiguous_count": len(ambiguous), "ambiguous": ambiguous,
    }
    (out / "lexicon_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")
