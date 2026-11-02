"""A mention only maps to an entity of the category that extraction assigned (issue found on real abstracts)."""
from __future__ import annotations

import json

import sdkg
from sdkg.batch import extraction_output_schema
from sdkg.normalise import Lexicon

from conftest import REPO, build_with, make_claim
from test_lexicon import SOURCES, build

A = "SAMPLE:0001"


def lexicon_file(tmp_path):
    path = tmp_path / "lexicon.tsv"
    path.write_text(
        "mention\tentity_id\tlabel\tcategory\n"
        "p300\tHGNC:3373\tEP300\tgene_or_protein\n"
        "lymphoma\tMONDO:1\tlymphoma\tdisease\n"
        "lymphoma\tHP:1\tLymphoma\tphenotype\n"
        "shared\tHGNC:1\tA\tgene_or_protein\n"
        "shared\tHGNC:2\tB\tgene_or_protein\n", "utf-8")
    return Lexicon(path)


def test_a_mention_of_another_category_is_not_mapped(tmp_path):
    resolved = lexicon_file(tmp_path).resolve("P300", "clinical_endpoint")

    assert resolved.entity_id == "sdkg:p300"
    assert resolved.category == "clinical_endpoint"
    assert not resolved.resolved
    assert resolved.reason == "other_category"


def test_a_mention_of_the_same_category_is_mapped(tmp_path):
    assert lexicon_file(tmp_path).resolve("P300", "gene_or_protein").entity_id == "HGNC:3373"


def test_category_settles_a_name_shared_by_a_disease_and_a_phenotype(tmp_path):
    lexicon = lexicon_file(tmp_path)

    assert lexicon.resolve("lymphoma", "disease").entity_id == "MONDO:1"
    assert lexicon.resolve("lymphoma", "phenotype").entity_id == "HP:1"


def test_a_name_shared_within_one_category_stays_ambiguous(tmp_path):
    assert lexicon_file(tmp_path).resolve("shared", "gene_or_protein").reason == "ambiguous"


def test_an_unmatched_concept_keeps_the_category_it_was_given(tmp_path):
    resolved = lexicon_file(tmp_path).resolve("unknown thing", "cell_type")

    assert (resolved.category, resolved.reason) == ("cell_type", "no_match")


def test_a_release_applies_the_categories(workspace):
    lexicon = workspace / "sample/lexicon.tsv"
    lexicon.write_text(lexicon.read_text("utf-8") + "P300\tHGNC:3373\tEP300\tgene_or_protein\n", "utf-8")
    claim = {**make_claim(subject="P300"), "subject_category": "clinical_endpoint", "object_category": "disease"}

    found = sdkg.load(build_with(workspace, {A: [claim]})).claims()[0]

    assert found["subject"] == "sdkg:p300"
    assert found["object"] == "MONDO:0010030"


def test_a_symbol_beats_another_genes_alias(workspace):
    root = workspace / "sample/ontologies/hgnc.tsv"
    root.write_text(
        "hgnc_id\tsymbol\tname\tstatus\talias_symbol\tprev_symbol\tuniprot_ids\n"
        "HGNC:1\tHGF\thepatocyte growth factor\tApproved\t\t\t\n"
        "HGNC:2\tOTHER\tother gene\tApproved\tHGF\t\t\n", "utf-8")
    sources = [s for s in SOURCES if s["source"] == "hgnc"]

    assert Lexicon(build(workspace, sources=sources) / "lexicon.tsv").resolve("HGF", "gene_or_protein").entity_id == "HGNC:1"


def test_common_hyphenated_gene_symbols_resolve(workspace):
    root = workspace / "sample/ontologies/hgnc.tsv"
    root.write_text(
        "hgnc_id\tsymbol\tname\tstatus\talias_symbol\tprev_symbol\tuniprot_ids\n"
        "HGNC:1\tIL21\tinterleukin 21\tApproved\t\t\t\n", "utf-8")
    sources = [s for s in SOURCES if s["source"] == "hgnc"]

    assert Lexicon(build(workspace, sources=sources) / "lexicon.tsv").resolve("IL-21", "gene_or_protein").entity_id == "HGNC:1"


def test_diseases_and_phenotypes_keep_separate_entries_in_the_example_configuration():
    sources = json.loads((REPO / "lexicon/sources.example.json").read_text("utf-8"))["sources"]
    groups = {s["source"]: s["group"] for s in sources}

    assert groups["mondo"] != groups["hpo"]


def test_structured_output_requires_categories():
    item = extraction_output_schema()["properties"]["claims"]["items"]

    assert {"subject_category", "object_category"} <= set(item["required"])
    assert "phenotype" in item["properties"]["subject_category"]["enum"]


def test_the_prompt_explains_categories():
    prompt = (REPO / "pipeline/prompts/extract-v3.md").read_text("utf-8")

    assert "`subject_category`" in prompt and "`clinical_endpoint`" in prompt
