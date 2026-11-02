"""Issue #10: deterministic entity normalisation and closed predicates."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

import sdkg

from conftest import run_build, run_extract


def base_claim(subject: str, obj: str, predicate: str = "associated_with") -> dict:
    return {
        "subject": subject, "predicate": predicate, "object": obj,
        "span": "Synthetic test abstract", "sign": None,
        "context": {"species": "human", "tissue": None, "population": None, "assay": None, "evidence_model": "human"},
    }


def release_with(ws: Path, *claims: dict) -> Path:
    path = ws / "sample/recorded/responses.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    rows[2]["claims"] = list(claims)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    return run_build(ws, run_extract(ws))


def entities(release: Path) -> dict[str, tuple]:
    rows = duckdb.sql(
        f"SELECT entity_id, label, category, resolved FROM read_parquet('{release}/entities.parquet')"
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def test_predicate_outside_the_closed_list_is_rejected_and_counted(workspace):
    release = release_with(workspace, base_claim("rituximab", "prednisone", predicate="vaguely_linked_to"))
    loaded = sdkg.load(release)

    assert loaded.claims(predicate="vaguely_linked_to") == []
    assert loaded.metadata["rejected_claims"]["predicate_not_allowed"] == 1


def test_spelling_variants_of_a_mention_resolve_to_one_identifier(workspace):
    release = release_with(
        workspace,
        base_claim("rituximab", "Sjögren's disease"),
        base_claim("prednisone", "SJOGREN'S   DISEASE"),
        base_claim("IRF5", "Sjogren’s disease"),
    )

    objects = {c["object"] for c in sdkg.load(release).claims(predicate="associated_with")}
    assert objects == {"MONDO:0010030"}


def test_mentions_resolve_to_the_planned_identifier_systems(workspace):
    mentions = [
        "BAFF", "IRF5 protein", "Sjögren's syndrome", "Keratoconjunctivitis sicca",
        "type I interferon signalling", "plasmacytoid dendritic cell", "minor salivary gland",
        "rituximab", "prednisone",
    ]
    release = release_with(workspace, *[base_claim(m, "Sjögren's disease") for m in mentions])

    prefixes = {c["subject"].split(":")[0] for c in sdkg.load(release).claims(predicate="associated_with")}
    assert prefixes == {"HGNC", "UniProtKB", "MONDO", "HP", "GO", "CL", "UBERON", "CHEMBL", "CHEBI"}


def test_concept_without_a_match_gets_a_local_identifier_and_is_listed(workspace):
    release = release_with(workspace, base_claim("Ectopic Lymphoid Structure", "Sjögren's disease"))

    entity = entities(release)["sdkg:ectopic_lymphoid_structure"]
    assert entity == ("Ectopic Lymphoid Structure", "unclassified", False)
    review = json.loads((release / "unresolved_entities.json").read_text("utf-8"))
    assert "sdkg:ectopic_lymphoid_structure" in [e["entity_id"] for e in review]


def test_close_but_inexact_mention_is_never_mapped(workspace):
    release = release_with(workspace, base_claim("TNFSF13", "Sjögren's disease"))

    assert "HGNC:11929" not in {c["subject"] for c in sdkg.load(release).claims(predicate="associated_with")}
    assert "sdkg:tnfsf13" in entities(release)


def test_ambiguous_mention_is_not_mapped_to_either_candidate(workspace):
    lexicon = workspace / "sample/lexicon.tsv"
    lexicon.write_text(lexicon.read_text("utf-8") + "BAFF\tHGNC:99999\tOTHER\tgene_or_protein\n", "utf-8")
    release = release_with(workspace, base_claim("BAFF", "Sjögren's disease"))

    claim = sdkg.load(release).claims(predicate="associated_with")[0]
    assert claim["subject"] == "sdkg:baff"
    review = json.loads((release / "unresolved_entities.json").read_text("utf-8"))
    assert {"entity_id": "sdkg:baff", "mention": "BAFF", "reason": "ambiguous"} in review


def test_release_reports_its_unresolved_entity_rate(release):
    # Sample mentions: TNFSF13B, IRF5, Sjögren's disease resolve; labial salivary gland does not.
    assert sdkg.load(release).metadata["unresolved_entity_rate"] == 0.25
