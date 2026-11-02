"""Defects found by reading the code after the tickets' tests passed."""
from __future__ import annotations

import json

import pytest

import sdkg
from sdkg.corpus import classify
from sdkg.hydrate import hydrate

from conftest import build_with, make_claim, write_databases

A = "SAMPLE:0001"


def test_empty_evidence_span_is_rejected(workspace):
    loaded = sdkg.load(build_with(workspace, {A: [make_claim(span=""), make_claim(subject="STAT4", span="   ")]}))

    assert loaded.claims() == []
    assert loaded.metadata["rejected_claims"] == {"span_not_found": 2}


def test_claim_with_an_empty_entity_is_rejected(workspace):
    loaded = sdkg.load(build_with(workspace, {A: [make_claim(subject="  ")]}))

    assert loaded.claims() == []
    assert loaded.metadata["rejected_claims"] == {"empty_entity": 1}


def test_greek_letters_do_not_merge_different_concepts(workspace):
    claims = sdkg.load(build_with(workspace, {A: [
        make_claim(subject="TNF-α"), make_claim(subject="TNF-β"), make_claim(subject="IFN-γ"),
    ]})).claims()

    assert len({c["subject"] for c in claims}) == 3


def test_concepts_with_no_latin_characters_do_not_merge(workspace):
    claims = sdkg.load(build_with(workspace, {A: [make_claim(subject="???"), make_claim(subject="!!!")]})).claims()

    assert len({c["subject"] for c in claims}) == 2
    assert all(c["subject"] not in ("sdkg:", "sdkg:_") for c in claims)


def test_local_identifiers_survive_the_lossless_exports(workspace):
    from sdkg.exports import read_jsonld_export, read_rdf_export

    release = build_with(workspace, {A: [make_claim(subject="TNF-α")]})

    for reader, name in ((read_rdf_export, "graph.nt"), (read_jsonld_export, "graph.jsonld")):
        assert any("alpha" in entity for entity in reader(release / "exports" / name)["entities"])


def test_span_retrieval_skips_curated_claims_that_have_no_publication(workspace):
    config = write_databases(workspace, [{"source": "reactome", "adapter": "reactome", "path": "reactome.tsv"}])
    release = build_with(workspace, {A: [make_claim()]}, databases=config)
    asked = []

    def fetch(pmid):
        asked.append(pmid)
        return None

    results = hydrate(release, fetch=fetch)

    assert asked == [A]
    assert [r["pmid"] for r in results] == [A]


@pytest.mark.parametrize("title", [
    "Skin in Sjögren-Larsson syndrome",
    "Skin in Sjögren–Larsson syndrome",  # en dash, the usual spelling
    "Skin in Sjogren Larsson syndrome",
    "SJÖGREN-LARSSON SYNDROME in a family",
])
def test_every_spelling_of_sjogren_larsson_is_excluded(title):
    assert classify({"title": title, "text": "Synthetic.", "mesh": [], "publication_types": []}) == "sjogren_larsson"


@pytest.mark.parametrize("title", ["Marinesco-Sjögren syndrome in a family", "Marinesco–Sjogren syndrome"])
def test_marinesco_sjogren_syndrome_is_excluded(title):
    assert classify({"title": title, "text": "Synthetic.", "mesh": [], "publication_types": []}) == "other_disease"


def test_sjogrens_disease_itself_is_not_excluded():
    assert classify({"title": "Sjögren's disease", "text": "Synthetic.", "mesh": [], "publication_types": []}) == "primary"
