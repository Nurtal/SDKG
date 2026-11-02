"""Issue #13: the first database in the background layer (ADR-0002)."""
from __future__ import annotations

import json

import pytest

import sdkg

from conftest import build_with, make_claim, write_databases

CORE = {"SAMPLE:0001": [make_claim()]}  # IRF5 associated with SjD
REACTOME = {"source": "reactome", "adapter": "reactome", "path": "reactome.tsv", "version": "95"}


def build(ws, max_hops=1, **kw):
    return sdkg.load(build_with(ws, CORE, databases=write_databases(ws, [REACTOME], max_hops), **kw))


def test_database_records_become_curated_source_claims(workspace):
    loaded = build(workspace)

    claim = loaded.claims(source="reactome", object="REACTOME:R-HSA-0000001", subject="HGNC:6120")[0]
    assert claim["claim_status"] == "curated_source"
    assert claim["predicate"] == "participates_in"
    assert claim["source_version"] == "95"
    assert claim["layer"] == "background"
    assert claim["object_label"] == "Synthetic pathway one"
    assert claim["evidence_level"] == "curated_database"


def test_only_high_confidence_human_records_are_imported(workspace):
    objects = {c["object"] for c in build(workspace).claims(source="reactome")}

    assert "REACTOME:R-HSA-0000003" not in objects  # inferred electronically
    assert "REACTOME:R-MMU-0000004" not in objects  # another species


def test_one_hop_keeps_only_records_touching_the_disease_core(workspace):
    claims = build(workspace, max_hops=1).claims(source="reactome")

    assert {(c["subject"], c["object"]) for c in claims} == {("HGNC:6120", "REACTOME:R-HSA-0000001")}


def test_two_hops_reach_one_step_further_and_no_more(workspace):
    claims = build(workspace, max_hops=2).claims(source="reactome")

    assert {(c["subject"], c["object"]) for c in claims} == {
        ("HGNC:6120", "REACTOME:R-HSA-0000001"),
        ("HGNC:99990", "REACTOME:R-HSA-0000001"),
    }


def test_three_hops_are_refused(workspace):
    with pytest.raises(ValueError, match="1 or 2 hops"):
        build(workspace, max_hops=3)


def test_filtering_to_the_disease_core_removes_background_claims(workspace):
    loaded = build(workspace)

    core = loaded.claims(layer="disease_core")
    assert core and all(c["source"] == "sample-literature" for c in core)
    assert loaded.claims(layer="background")


def test_rebuilding_from_the_frozen_snapshot_gives_the_same_claims(workspace):
    first = build(workspace, out="one", archive="a1")
    second = build(workspace, out="two", archive="a2")

    assert first.claims() == second.claims()


def test_a_changed_snapshot_stops_the_build(workspace):
    config = write_databases(workspace, [REACTOME])
    snapshot = workspace / "sample/databases/reactome.tsv"
    snapshot.write_text(snapshot.read_text("utf-8") + "Q1\tR-HSA-9\tu\tn\tTAS\tHomo sapiens\n", "utf-8")

    with pytest.raises(ValueError, match="reactome.*snapshot"):
        build_with(workspace, CORE, databases=config)


def test_a_database_without_licence_stops_the_build(workspace):
    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    del data["sources"]["reactome"]
    manifest.write_text(json.dumps(data), "utf-8")

    with pytest.raises(ValueError, match="reactome.*not in the licence manifest"):
        build(workspace)
