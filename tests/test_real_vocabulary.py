"""Gaps found while reading real abstracts."""
from __future__ import annotations

import csv
import json

import pytest

from sdkg.normalise import Lexicon, normal_form

from conftest import REPO
from test_lexicon import SOURCES, build


@pytest.mark.parametrize("a,b", [("IFN-γ", "IFN-gamma"), ("TNF-α", "TNF-alpha"), ("IL-1β", "IL-1beta"), ("Δ7 FoxP3", "delta7 FoxP3")])
def test_greek_letters_and_their_names_have_one_form(a, b):
    assert normal_form(a) == normal_form(b)


def test_veterinary_terms_do_not_make_a_human_disease_ambiguous(workspace):
    (workspace / "sample/ontologies/mondo.json").write_text(json.dumps({"graphs": [{"nodes": [
        {"id": "http://purl.obolibrary.org/obo/MONDO_9000001", "lbl": "plasma cell myeloma", "type": "CLASS",
         "meta": {"synonyms": [{"pred": "hasExactSynonym", "val": "multiple myeloma"}]}},
        {"id": "http://purl.obolibrary.org/obo/MONDO_1000002", "lbl": "plasma cell myeloma, non-human animal", "type": "CLASS",
         "meta": {"synonyms": [{"pred": "hasExactSynonym", "val": "multiple myeloma"}]}},
        {"id": "http://purl.obolibrary.org/obo/MONDO_7770003", "lbl": "plasma cell myeloma, dog", "type": "CLASS",
         "meta": {"synonyms": [{"pred": "hasExactSynonym", "val": "multiple myeloma"}]}},
    ]}]}), "utf-8")

    lexicon = Lexicon(build(workspace) / "lexicon.tsv")

    assert lexicon.resolve("multiple myeloma", "disease").entity_id == "MONDO:9000001"


def test_a_drug_mention_can_match_a_chemical_entity(tmp_path):
    path = tmp_path / "l.tsv"
    path.write_text("mention\tentity_id\tlabel\tcategory\nprednisone\tCHEBI:1\tprednisone\tchemical\n", "utf-8")

    assert Lexicon(path).resolve("prednisone", "drug").entity_id == "CHEBI:1"
    assert Lexicon(path).resolve("prednisone", "chemical").entity_id == "CHEBI:1"


def test_a_biomarker_mention_can_match_any_category(tmp_path):
    path = tmp_path / "l.tsv"
    path.write_text("mention\tentity_id\tlabel\tcategory\nb2m\tHGNC:914\tB2M\tgene_or_protein\n", "utf-8")

    assert Lexicon(path).resolve("B2M", "biomarker").entity_id == "HGNC:914"


def test_chemical_is_an_allowed_category():
    from sdkg.batch import extraction_output_schema

    item = extraction_output_schema()["properties"]["claims"]["items"]

    assert "chemical" in item["properties"]["subject_category"]["enum"]


def test_common_immunology_names_are_curated():
    with (REPO / "lexicon/curated.tsv").open(encoding="utf-8", newline="") as handle:
        rows = {r["mention"]: r for r in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)}

    assert rows["IFN-gamma"]["entity_id"] == "HGNC:5438"
    assert rows["CD4+ T cell"]["entity_id"] == "CL:0000624"
    assert rows["Th1"]["category"] == "cell_type"
    assert rows["IgG"]["category"] == "clinical_endpoint"
