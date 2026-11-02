"""Issue #31: the production lexicon, from frozen snapshots of genes and ontologies."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from sdkg.cli import main
from sdkg.normalise import Lexicon

SOURCES = [
    {"source": "hgnc", "adapter": "hgnc", "path": "hgnc.tsv", "group": "gene"},
    {"source": "mondo", "adapter": "obo", "path": "mondo.json", "prefix": "MONDO", "category": "disease", "group": "disease", "xrefs": True},
    {"source": "hpo", "adapter": "obo", "path": "hp.json", "prefix": "HP", "category": "phenotype", "group": "phenotype"},
    {"source": "chembl", "adapter": "chembl_molecules", "path": "chembl_molecules.json", "group": "drug"},
    {"source": "chebi", "adapter": "obo", "path": "chebi.json", "prefix": "CHEBI", "category": "drug", "group": "drug"},
    {"source": "chembl", "adapter": "chembl_targets", "path": "chembl_targets.json", "group": "gene"},
]


def config(ws: Path, sources=None) -> Path:
    root = ws / "sample/ontologies"
    entries = [
        {"version": "test", "sha256": hashlib.sha256((root / s["path"]).read_bytes()).hexdigest(), **s}
        for s in (sources or SOURCES)
    ]
    path = root / "lexicon.json"
    path.write_text(json.dumps({"sources": entries, "curated": "curated.tsv"}), "utf-8")
    return path


def build(ws: Path, out: str = "lexicon", *extra: str, sources=None) -> Path:
    target = ws / out
    code = main([
        "lexicon", "--config", str(config(ws, sources)), "--licences", str(ws / "sample/licences.json"),
        "--out", str(target), *extra,
    ])
    assert code == 0
    return target


@pytest.fixture
def lexicon(workspace) -> Lexicon:
    return Lexicon(build(workspace) / "lexicon.tsv")


@pytest.mark.parametrize("mention", ["SYNA", "synthetic gene a", "SYNA-ALT", "OLDSYNA", "Q00001"])
def test_gene_symbols_names_aliases_and_accessions_resolve(lexicon, mention):
    resolved = lexicon.resolve(mention)
    assert (resolved.entity_id, resolved.label, resolved.category) == ("HGNC:90001", "SYNA", "gene_or_protein")


def test_withdrawn_genes_are_not_used(lexicon):
    assert not lexicon.resolve("SYNC").resolved


def test_very_short_aliases_are_too_ambiguous_to_use(lexicon):
    assert not lexicon.resolve("AB").resolved


@pytest.mark.parametrize("mention", ["synthetic disease", "Orphanet:900001", "ORPHA:900001", "OMIM:900002"])
def test_ontology_labels_and_useful_cross_references_resolve(lexicon, mention):
    assert lexicon.resolve(mention).entity_id == "MONDO:9000001"


@pytest.mark.parametrize("mention", ["related synthetic thing", "broad synthetic thing", "MESH:D900003"])
def test_inexact_synonyms_and_other_cross_references_are_not_used(lexicon, mention):
    assert not lexicon.resolve(mention).resolved


def test_exact_synonyms_count_as_names(workspace):
    report = json.loads((build(workspace) / "lexicon_report.json").read_text("utf-8"))

    # This exact synonym is also an HP label, so it can only be ambiguous if the synonym was read.
    assert "exact synthetic disease" in [a["mention"] for a in report["ambiguous"]]


def test_obsolete_terms_are_not_used(lexicon):
    assert not lexicon.resolve("obsolete synthetic disease").resolved


def test_terms_imported_from_other_ontologies_stay_with_their_own_source(lexicon):
    assert not lexicon.resolve("phenotype imported into mondo").resolved
    assert not lexicon.resolve("a property").resolved


def test_ontology_phenotype_resolves_with_its_category(lexicon):
    resolved = lexicon.resolve("synthetic phenotype")
    assert (resolved.entity_id, resolved.category) == ("HP:9000001", "phenotype")


def test_within_a_group_the_first_source_wins(lexicon):
    assert lexicon.resolve("syntheticol").entity_id == "CHEMBL:9000001"
    assert lexicon.resolve("only in chebi").entity_id == "CHEBI:9000002"


def test_drug_synonyms_resolve(lexicon):
    assert lexicon.resolve("Syntheticol-X").entity_id == "CHEMBL:9000001"


def test_chembl_single_protein_targets_map_through_their_accession(lexicon):
    assert lexicon.resolve("CHEMBL9100001").entity_id == "HGNC:90001"
    assert not lexicon.resolve("CHEMBL9100002").resolved  # Not a single protein.
    assert not lexicon.resolve("CHEMBL9100003").resolved  # No known gene.


def test_a_mention_shared_across_groups_is_ambiguous_and_reported(workspace):
    out = build(workspace)
    report = json.loads((out / "lexicon_report.json").read_text("utf-8"))

    assert not Lexicon(out / "lexicon.tsv").resolve("exact synthetic disease").resolved
    entry = next(a for a in report["ambiguous"] if a["mention"] == "exact synthetic disease")
    assert set(entry["entity_ids"]) == {"MONDO:9000001", "HP:9000002"}


def test_curated_mentions_settle_a_conflict_and_add_names(lexicon):
    assert lexicon.resolve("CURATEDNAME").entity_id == "MONDO:9000001"
    assert lexicon.resolve("SHARED").entity_id == "HGNC:90002"


def test_report_records_each_source_version_hash_and_counts(workspace):
    out = build(workspace)
    report = json.loads((out / "lexicon_report.json").read_text("utf-8"))

    hgnc = next(s for s in report["sources"] if s["source"] == "hgnc")
    assert hgnc["version"] == "test" and len(hgnc["sha256"]) == 64 and hgnc["mentions"] > 0
    assert report["publishable"] is True


def test_a_changed_snapshot_stops_the_build(workspace):
    path = config(workspace)
    snapshot = workspace / "sample/ontologies/hgnc.tsv"
    snapshot.write_text(snapshot.read_text("utf-8") + "x\n", "utf-8")

    with pytest.raises(ValueError, match="hgnc.*hash"):
        main(["lexicon", "--config", str(path), "--licences", str(workspace / "sample/licences.json"), "--out", str(workspace / "o")])


def test_a_source_without_an_allowed_licence_stops_the_build(workspace):
    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["sources"]["hgnc"] = {"status": "unconfirmed"}
    manifest.write_text(json.dumps(data), "utf-8")

    with pytest.raises(ValueError, match="hgnc.*unconfirmed"):
        build(workspace)


def test_private_lexicon_with_an_unconfirmed_source_is_marked_not_publishable(workspace):
    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["sources"]["hgnc"] = {"status": "unconfirmed"}
    manifest.write_text(json.dumps(data), "utf-8")

    out = build(workspace, "private", "--allow-unconfirmed")

    assert json.loads((out / "lexicon_report.json").read_text("utf-8"))["publishable"] is False


def test_building_twice_gives_identical_files(workspace):
    one, two = build(workspace, "one"), build(workspace, "two")

    for name in ("lexicon.tsv", "lexicon_report.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()


def test_output_has_the_columns_the_build_expects(workspace):
    with (build(workspace) / "lexicon.tsv").open(encoding="utf-8", newline="") as handle:
        assert csv.DictReader(handle, delimiter="\t").fieldnames == ["mention", "entity_id", "label", "category"]


def test_quotes_in_names_do_not_corrupt_the_lexicon(workspace):
    curated = workspace / "sample/ontologies/curated.tsv"
    curated.write_text(curated.read_text("utf-8") + '"QUOTED" NAME\tHP:9000001\tsynthetic phenotype\tphenotype\nAFTERQUOTE\tHP:9000001\tsynthetic phenotype\tphenotype\n', "utf-8")

    lexicon = Lexicon(build(workspace) / "lexicon.tsv")

    assert lexicon.resolve('"QUOTED" NAME').entity_id == "HP:9000001"
    assert lexicon.resolve("AFTERQUOTE").entity_id == "HP:9000001"
