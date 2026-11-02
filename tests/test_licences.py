"""Issue #7: source licences and evidence span publication rules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sdkg
from sdkg.cli import main
from sdkg.hydrate import abstract_text_from_xml, hydrate

from conftest import REPO, run_build, run_extract

SPAN = "TNFSF13B expression was increased compared with controls"


def edit_manifest(ws: Path, **changes) -> None:
    path = ws / "sample/licences.json"
    manifest = json.loads(path.read_text("utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest), "utf-8")


def set_doc_licence(ws: Path, doc_id: str, licence: str) -> None:
    path = ws / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    for row in rows:
        if row["doc_id"] == doc_id:
            row["licence"] = licence
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")


def test_source_absent_from_manifest_stops_the_build(workspace):
    archive = run_extract(workspace)
    edit_manifest(workspace, sources={})

    with pytest.raises(ValueError, match="sample-literature.*not in the licence manifest"):
        run_build(workspace, archive)


def test_restricted_source_stops_the_build(workspace):
    archive = run_extract(workspace)
    edit_manifest(workspace, sources={"sample-literature": {"status": "restricted"}})

    with pytest.raises(ValueError, match="sample-literature.*restricted"):
        run_build(workspace, archive)


def test_unconfirmed_source_stops_a_normal_build(workspace):
    archive = run_extract(workspace)
    edit_manifest(workspace, sources={"sample-literature": {"status": "unconfirmed"}})

    with pytest.raises(ValueError, match="sample-literature.*unconfirmed"):
        run_build(workspace, archive)


def test_private_build_with_unconfirmed_source_is_marked_not_publishable(workspace):
    archive = run_extract(workspace)
    edit_manifest(workspace, sources={"sample-literature": {"status": "unconfirmed"}})

    code = main([
        "build", "--corpus", str(workspace / "sample/corpus"), "--archive", str(archive),
        "--licences", str(workspace / "sample/licences.json"),
        "--lexicon", str(workspace / "sample/lexicon.tsv"), "--out", str(workspace / "private"),
        "--version", "0.0.0-test", "--allow-unconfirmed",
    ])

    assert code == 0
    assert sdkg.load(workspace / "private").metadata["publishable"] is False


def test_release_from_allowed_sources_is_publishable(release):
    assert sdkg.load(release).metadata["publishable"] is True


def test_by_default_only_identifier_and_offsets_are_published(release):
    claim = sdkg.load(release).claims(subject_label="TNFSF13B")[0]

    assert claim["span_text"] is None
    assert claim["pmid"] == "SAMPLE:0001"
    assert claim["span_end"] > claim["span_start"]
    assert SPAN.encode() not in (release / "evidence.parquet").read_bytes()


def test_when_enabled_text_appears_only_for_compatible_open_licences(workspace):
    edit_manifest(workspace, publish_span_text=True)
    set_doc_licence(workspace, "SAMPLE:0002", "CC-BY-NC-4.0")
    loaded = sdkg.load(run_build(workspace, run_extract(workspace)))

    assert loaded.claims(subject_label="TNFSF13B")[0]["span_text"] == SPAN
    assert loaded.claims(subject_label="IRF5")[0]["span_text"] is None


def test_user_can_retrieve_span_text_from_identifier_and_offsets(release):
    texts = {
        "SAMPLE:0001": "Synthetic test abstract. In labial salivary gland biopsies from patients with "
                       "primary Sjögren's disease, TNFSF13B expression was increased compared with controls.",
    }
    results = hydrate(release, fetch=texts.get, pmids=["SAMPLE:0001"])

    assert [r["span_text"] for r in results] == [SPAN]
    assert results[0]["status"] == "verified"


def test_retrieval_reports_a_source_text_that_has_changed(release):
    results = hydrate(release, fetch=lambda pmid: "x" * 500, pmids=["SAMPLE:0001"])

    assert results[0]["status"] == "text_changed"
    assert results[0]["span_text"] is None


def test_retrieval_reports_an_unavailable_source(release):
    results = hydrate(release, fetch=lambda pmid: None, pmids=["SAMPLE:0001"])

    assert results[0]["status"] == "unavailable"


def test_pubmed_abstract_sections_are_joined_predictably():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><Abstract>
      <AbstractText Label="BACKGROUND">First <i>part</i>.</AbstractText>
      <AbstractText Label="RESULTS">Second part.</AbstractText>
    </Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

    assert abstract_text_from_xml(xml) == "First part. Second part."


def test_every_planned_v1_source_is_listed_and_none_is_preapproved():
    manifest = json.loads((REPO / "licences/manifest.json").read_text("utf-8"))
    planned = {
        "pubmed", "pmc-open-access", "uniprot", "reactome", "chembl", "hpo",
        "clinicaltrials-gov", "open-targets", "hgnc", "mondo", "go", "cl", "uberon", "chebi",
    }

    assert planned <= set(manifest["sources"])
    assert manifest["publish_span_text"] is False
    assert all(s["status"] == "unconfirmed" and s["terms_url"] for s in manifest["sources"].values())
