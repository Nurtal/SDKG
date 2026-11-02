"""Issue #5: a recorded LLM response becomes a loadable release."""
from __future__ import annotations

import sdkg


def test_release_is_written_as_canonical_tables(release):
    assert (release / "claims.parquet").exists()
    assert (release / "entities.parquet").exists()
    assert (release / "evidence.parquet").exists()


def test_user_can_read_a_claim_with_its_evidence_span_and_context(release):
    claims = sdkg.load(release).claims(subject_label="TNFSF13B")

    assert len(claims) == 1
    claim = claims[0]
    assert claim["predicate"] == "altered_in"
    assert claim["object_label"] == "labial salivary gland"
    assert claim["pmid"] == "SAMPLE:0001"
    assert claim["tissue"] == "labial salivary gland"
    assert claim["species"] == "human"


def test_evidence_offsets_point_at_the_supporting_passage(release):
    claim = sdkg.load(release).claims(subject_label="TNFSF13B")[0]

    abstract = (
        "Synthetic test abstract. In labial salivary gland biopsies from patients with primary "
        "Sjögren's disease, TNFSF13B expression was increased compared with controls."
    )
    assert abstract[claim["span_start"] : claim["span_end"]] == (
        "TNFSF13B expression was increased compared with controls"
    )


def test_claim_with_unverifiable_span_is_absent_and_counted(release):
    loaded = sdkg.load(release)

    assert loaded.claims(subject_label="STAT4") == []
    assert loaded.metadata["rejected_claims"] == {"span_not_found": 1}


def test_document_with_no_claims_does_not_break_the_release(release):
    assert sdkg.load(release).metadata["documents"] == 3
