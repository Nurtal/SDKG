"""Issue #28: a static website, with no live server (ADR-0009)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from sdkg.cli import main

from conftest import build_with, make_claim, write_databases

A = "SAMPLE:0001"
IRF5 = "HGNC:6120"


@pytest.fixture
def release(workspace):
    config = write_databases(workspace, [
        {"source": "reactome", "adapter": "reactome", "path": "reactome.tsv"},
        {"source": "open-targets", "adapter": "open_targets", "path": "open_targets.json"},
    ])
    return build_with(workspace, {A: [make_claim(sign="positive", tissue="blood")]}, databases=config)


def site(workspace: Path, release: Path, *extra: str, out: str = "site") -> Path:
    target = workspace / out
    assert main(["site", "--release", str(release), "--out", str(target), *extra]) == 0
    return target


def entity_page(site_dir: Path, entity_id: str) -> dict:
    index = json.loads((site_dir / "data/index.json").read_text("utf-8"))
    entry = next(e for e in index["entities"] if e["id"] == entity_id)
    return json.loads((site_dir / "data/entities" / entry["file"]).read_text("utf-8"))


def test_every_entity_can_be_searched(workspace, release):
    index = json.loads((site(workspace, release) / "data/index.json").read_text("utf-8"))

    labels = {e["label"] for e in index["entities"]}
    assert {"IRF5", "Sjogren syndrome", "Synthetic pathway one"} <= labels


def test_each_relationship_shows_its_claims_layer_and_quality_fields(workspace, release):
    page = entity_page(site(workspace, release), IRF5)

    relation = next(r for r in page["relationships"] if r["other"]["id"] == "MONDO:0010030")
    assert relation["predicate"] == "associated_with"
    claim = relation["claims"][0]
    assert claim["layer"] == "disease_core"
    assert claim["claim_status"] == "ai_extracted"
    assert claim["evidence_level"] == "human_observational"
    assert claim["tissue"] == "blood"
    assert claim["pmid"] == A


def test_neighbourhood_includes_background_relationships(workspace, release):
    page = entity_page(site(workspace, release), IRF5)

    layers = {c["layer"] for r in page["relationships"] for c in r["claims"]}
    assert layers == {"disease_core", "background"}


def test_span_text_appears_only_where_allowed(workspace, release):
    site_dir = site(workspace, release)

    assert entity_page(site_dir, IRF5)["relationships"][0]["claims"][0]["span_text"] is None
    assert "Synthetic test abstract" not in "".join(p.read_text("utf-8") for p in (site_dir / "data/entities").iterdir())


def test_held_out_associations_never_reach_the_site(workspace, release):
    text = "".join(p.read_text("utf-8") for p in (site(workspace, release) / "data").rglob("*.json"))

    assert "ENSG00000000001" not in text


def test_the_site_is_self_contained_and_needs_no_server(workspace, release):
    site_dir = site(workspace, release)
    html = (site_dir / "index.html").read_text("utf-8")

    assert not re.search(r"""(src|href)=["']https?://""", html)
    assert "app.js" in html and (site_dir / "app.js").exists() and (site_dir / "style.css").exists()
    assert "fetch(\"data/" in (site_dir / "app.js").read_text("utf-8")


def test_the_site_works_at_phone_width(workspace, release):
    site_dir = site(workspace, release)

    assert 'name="viewport"' in (site_dir / "index.html").read_text("utf-8")
    assert "@media" in (site_dir / "style.css").read_text("utf-8")


def test_it_is_clear_that_ai_extracted_claims_are_not_curated(workspace, release):
    html = (site(workspace, release) / "index.html").read_text("utf-8")

    assert "not curated" in html
    assert "not medical advice" in html.lower()


def test_sample_data_is_labelled_as_synthetic(workspace, release):
    site_dir = site(workspace, release, "--data-notice", "Synthetic sample data, not scientific evidence.")

    assert json.loads((site_dir / "data/release.json").read_text("utf-8"))["data_notice"] == "Synthetic sample data, not scientific evidence."


def test_unpublishable_release_refuses_to_become_a_site_unless_labelled(workspace, release):
    path = release / "release.json"
    data = json.loads(path.read_text("utf-8"))
    data["publishable"] = False
    path.write_text(json.dumps(data), "utf-8")

    with pytest.raises(ValueError, match="not publishable"):
        site(workspace, release)


def test_downloads_are_linked_from_a_release_url_or_copied_for_the_sample(workspace, release):
    linked = site(workspace, release, "--downloads-url", "https://doi.org/10.5281/zenodo.0", out="linked")
    copied = site(workspace, release, out="copied")

    assert json.loads((linked / "data/release.json").read_text("utf-8"))["downloads"]["url"] == "https://doi.org/10.5281/zenodo.0"
    assert not (linked / "downloads").exists()
    assert (copied / "downloads/graph.graphml").exists()
    assert "graph.graphml" in json.loads((copied / "data/release.json").read_text("utf-8"))["downloads"]["files"]


def test_extracted_text_cannot_inject_markup(workspace, release):
    script = (site(workspace, release) / "app.js").read_text("utf-8")

    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "textContent" in script


def test_links_only_open_expected_addresses(workspace, release):
    script = (site(workspace, release) / "app.js").read_text("utf-8")

    assert "https://pubmed.ncbi.nlm.nih.gov/" in script
    assert re.search(r"/\^\\d\+\$/", script)  # Only numeric PMIDs become links.


def test_site_generation_is_deterministic(workspace, release):
    def hashes(path):
        return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()}

    assert hashes(site(workspace, release, out="one")) == hashes(site(workspace, release, out="two"))
