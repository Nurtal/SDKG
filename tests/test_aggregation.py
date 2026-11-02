"""Issue #11: grouped claims and separate quality fields."""
from __future__ import annotations

import duckdb

import sdkg

from conftest import build_with, make_claim

A, B, C = "SAMPLE:0001", "SAMPLE:0002", "SAMPLE:0003"


def group(release, **kw):
    groups = sdkg.load(release).claim_groups(**kw)
    assert len(groups) == 1
    return groups[0]


def test_support_counts_distinct_publications(workspace):
    release = build_with(workspace, {
        A: [make_claim(), make_claim(span="labial salivary gland")],
        B: [make_claim()],
    })

    assert group(release, subject="HGNC:6120")["support"] == 2


def test_different_contexts_are_grouped_separately(workspace):
    release = build_with(workspace, {A: [make_claim(tissue="blood")], B: [make_claim(tissue="saliva")]})

    assert len(sdkg.load(release).claim_groups(subject="HGNC:6120")) == 2


def test_opposite_signs_in_compatible_contexts_are_a_contradiction(workspace):
    release = build_with(workspace, {
        A: [make_claim(sign="positive", tissue="blood")],
        B: [make_claim(sign="negative", tissue="blood")],
    })

    pairs = sdkg.load(release).contradictions()
    assert len(pairs) == 1
    assert {pairs[0]["pmid_a"], pairs[0]["pmid_b"]} == {A, B}


def test_opposite_signs_where_context_is_unstated_are_compatible(workspace):
    release = build_with(workspace, {
        A: [make_claim(sign="positive", tissue="blood")],
        B: [make_claim(sign="negative", tissue=None)],
    })

    assert len(sdkg.load(release).contradictions()) == 1


def test_opposite_signs_in_incompatible_contexts_are_not_a_contradiction(workspace):
    release = build_with(workspace, {
        A: [make_claim(sign="positive", tissue="blood")],
        B: [make_claim(sign="negative", tissue="saliva")],
        C: [make_claim(sign="negative", tissue="blood", evidence_model="animal", species="mouse")],
    })

    assert sdkg.load(release).contradictions() == []


def test_null_results_are_kept_and_reported(workspace):
    release = build_with(workspace, {
        A: [make_claim(negated=True, tissue="blood")],
        B: [make_claim(sign="positive", tissue="blood")],
    })
    loaded = sdkg.load(release)

    assert [c["pmid"] for c in loaded.claims(negated=True)] == [A]
    assert loaded.contradictions() == []
    groups = {g["negated"]: g for g in loaded.claim_groups(subject="HGNC:6120")}
    assert groups[True]["support"] == 1


def test_quality_fields_are_separate_with_no_composite_score(release):
    claim = sdkg.load(release).claims(subject_label="TNFSF13B")[0]
    columns = [r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{release}/claims.parquet')").fetchall()]

    assert claim["claim_status"] == "ai_extracted"
    assert claim["evidence_level"] == "human_observational"
    assert {"claim_status", "evidence_level", "extraction_reliability"} <= set(columns)
    assert not [c for c in columns if "confidence" in c or "score" in c]


def test_evidence_level_comes_from_study_type_and_model(workspace):
    path = workspace / "sample/corpus/documents.jsonl"
    path.write_text(path.read_text("utf-8").replace('"publication_type":"primary"', '"publication_type":"primary","study_type":"randomised_trial"', 1), "utf-8")
    release = build_with(workspace, {
        A: [make_claim()],
        B: [make_claim(subject="STAT4", evidence_model="animal", species="mouse")],
        C: [make_claim(subject="BAFF", evidence_model=None)],
    })
    loaded = sdkg.load(release)

    assert loaded.claims(subject="HGNC:6120")[0]["evidence_level"] == "randomised_trial"
    assert loaded.claims(subject="HGNC:11365")[0]["evidence_level"] == "animal_or_in_vitro"
    assert loaded.claims(subject="HGNC:11929")[0]["evidence_level"] == "unspecified"


def test_evidence_types_can_be_filtered_apart(workspace):
    release = build_with(workspace, {
        A: [make_claim(evidence_model="human")],
        B: [make_claim(subject="STAT4", evidence_model="animal", species="mouse")],
        C: [make_claim(subject="BAFF", evidence_model="in_vitro"), make_claim(subject="rituximab", evidence_model="secondary_sjd")],
    })
    loaded = sdkg.load(release)

    assert {m: len(loaded.claims(evidence_model=m)) for m in ("human", "animal", "in_vitro", "secondary_sjd")} == {
        "human": 1, "animal": 1, "in_vitro": 1, "secondary_sjd": 1,
    }


def test_every_underlying_claim_of_a_group_is_retrievable(workspace):
    release = build_with(workspace, {A: [make_claim(tissue="blood")], B: [make_claim(tissue="blood")]})
    loaded = sdkg.load(release)

    grouped = group(release, subject="HGNC:6120")
    assert set(grouped["claim_ids"]) == {c["claim_id"] for c in loaded.claims(subject="HGNC:6120")}
    assert len(grouped["claim_ids"]) == 2
