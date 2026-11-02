"""Defects found by running the pipeline on 10 real development-set abstracts."""
from __future__ import annotations

import json

import pytest

import sdkg
from sdkg.cli import main
from sdkg.extraction import read_jsonl
from sdkg.normalise import Lexicon, normal_form

from conftest import REPO, build_with, make_claim
from test_lexicon import SOURCES, build

A = "SAMPLE:0001"
TEXT = "Result (OR = 8.0, p < 0.01) in IL‑6 and “quoted” text."


def with_text(ws, text=TEXT):
    path = ws / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    rows[0]["text"] = text
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")


@pytest.mark.parametrize("span,expected", [
    ("(OR = 8.0, p < 0.01)", "(OR = 8.0, p < 0.01)"),  # A model writes ordinary spaces.
    ("IL-6", "IL‑6"),
    ('"quoted"', "“quoted”"),
    ("Result  (OR", "Result (OR"),
])
def test_span_matches_despite_typographic_variants_and_keeps_the_source_text(workspace, span, expected):
    with_text(workspace)
    claim = sdkg.load(build_with(workspace, {A: [make_claim(span=span)]})).claims()[0]

    assert TEXT[claim["span_start"] : claim["span_end"]] == expected


def test_span_retrieval_still_verifies_after_a_typographic_match(workspace):
    from sdkg.hydrate import hydrate

    with_text(workspace)
    release = build_with(workspace, {A: [make_claim(span="(OR = 8.0, p < 0.01)")]})

    assert hydrate(release, fetch=lambda pmid: TEXT)[0]["status"] == "verified"


@pytest.mark.parametrize("span", ["OR = 9.0", "Result(OR", "IL6"])
def test_changed_words_or_numbers_are_still_rejected(workspace, span):
    with_text(workspace)
    loaded = sdkg.load(build_with(workspace, {A: [make_claim(span=span)]}))

    assert loaded.claims() == []


@pytest.mark.parametrize("a,b", [("IL‑6", "IL-6"), ("IL‐6", "IL-6"), ("IL–6", "IL-6"), ("TNF alpha", "TNF alpha")])
def test_typographic_variants_of_a_mention_have_one_form(a, b):
    assert normal_form(a) == normal_form(b)


# Lexicon


def test_plural_cell_names_resolve_when_the_source_allows_it(workspace):
    root = workspace / "sample/ontologies"
    (root / "cl.json").write_text(json.dumps({"graphs": [{"nodes": [
        {"id": "http://purl.obolibrary.org/obo/CL_9000001", "lbl": "synthetic B cell", "type": "CLASS",
         "meta": {"synonyms": [{"pred": "hasExactSynonym", "val": "SBC"}]}},
    ]}]}), "utf-8")
    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["sources"]["cl"] = {"status": "allowed"}
    manifest.write_text(json.dumps(data), "utf-8")
    source = {"source": "cl", "adapter": "obo", "path": "cl.json", "prefix": "CL", "category": "cell_type", "group": "cell", "plurals": True}

    lexicon = Lexicon(build(workspace, sources=SOURCES + [source]) / "lexicon.tsv")

    for mention in ("synthetic B cell", "synthetic B cells", "SBC", "SBCs"):
        assert lexicon.resolve(mention).entity_id == "CL:9000001", mention


def test_plurals_are_not_added_unless_the_source_allows_it(lexicon_default):
    assert not lexicon_default.resolve("synthetic phenotypes").resolved


@pytest.fixture
def lexicon_default(workspace):
    return Lexicon(build(workspace) / "lexicon.tsv")


def test_a_disease_and_a_phenotype_with_one_name_resolve_to_the_first_source_when_grouped(workspace):
    grouped = [{**s, "group": "clinical"} if s["source"] in ("mondo", "hpo") else s for s in SOURCES]

    lexicon = Lexicon(build(workspace, sources=grouped) / "lexicon.tsv")

    assert lexicon.resolve("exact synthetic disease").entity_id == "MONDO:9000001"


def test_the_example_configuration_groups_diseases_and_phenotypes():
    sources = json.loads((REPO / "lexicon/sources.example.json").read_text("utf-8"))["sources"]
    groups = {s["source"]: s["group"] for s in sources}

    assert groups["mondo"] == groups["hpo"]
    assert [s["source"] for s in sources].index("mondo") < [s["source"] for s in sources].index("hpo")
    assert next(s for s in sources if s["source"] == "cl").get("plurals") is True


def test_sjd_instruments_and_autoantibodies_have_curated_entries(workspace):
    rows = {r.split("\t")[0]: r.split("\t") for r in (REPO / "lexicon/curated.tsv").read_text("utf-8").splitlines()[1:]}

    for mention in ("ESSDAI", "ESSPRI", "ClinESSDAI", "anti-SSA", "anti-Ro", "anti-SSB", "anti-La"):
        assert rows[mention][1].startswith("sdkg:"), mention
    assert rows["ESSDAI"][3] == "clinical_endpoint"
    assert rows["anti-SSA"][3] == "autoantibody"


# The prototype's documents stay in the development set


def freeze(ws, include=None, development=1, out="corpus"):
    args = ["corpus", "--query-file", str(REPO / "corpus/query.txt"), "--frozen-on", "2026-11-02",
            "--from-xml", str(REPO / "sample/pubmed/efetch.xml"), "--development", str(development),
            "--seed", "11", "--out", str(ws / out)]
    if include:
        args += ["--development-include", str(include)]
    assert main(args) == 0
    return {d["doc_id"]: d for d in read_jsonl(ws / out / "documents.jsonl")}


def test_documents_already_used_for_prompt_work_are_forced_into_the_development_set(workspace):
    include = workspace / "used.txt"
    include.write_text("9000002\n9000007\n1234567\n", "utf-8")

    documents = freeze(workspace, include, development=1)

    assert documents["9000002"]["split"] == "development"
    assert documents["9000007"]["split"] == "development"
    assert documents["9000001"]["split"] == "evaluation"


def test_forced_documents_count_towards_the_development_set_size(workspace):
    include = workspace / "used.txt"
    include.write_text("9000002\n", "utf-8")

    documents = freeze(workspace, include, development=2)

    assert sum(d["split"] == "development" for d in documents.values()) == 2


def test_the_prototype_documents_are_recorded():
    pmids = (REPO / "pipeline/prototype-pmids.txt").read_text("utf-8").split()

    assert len(pmids) == 10 and all(p.isdigit() for p in pmids)


# Prompts


def test_the_extraction_prompt_defines_each_predicate_and_sign():
    import yaml

    prompt = (REPO / "pipeline/prompts/extract-v1.md").read_text("utf-8")
    predicates = yaml.safe_load((REPO / "schema/sdkg.yaml").read_text("utf-8"))["enums"]["Predicate"]["permissible_values"]

    for predicate in predicates:
        assert f"`{predicate}`" in prompt, predicate
    assert "direction of change" in prompt
