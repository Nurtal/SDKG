"""Issue #8: the Biolink-aligned schema is the single definition of the data model."""
from __future__ import annotations

import json
import re

import pytest
import rdflib
import yaml

from sdkg.schema_tools import generate_json_schema

from conftest import REPO, run_build, run_extract

SCHEMA_DIR = REPO / "schema"
SOURCE = SCHEMA_DIR / "sdkg.yaml"
GENERATED = SCHEMA_DIR / "generated"


@pytest.fixture(scope="module")
def predicates():
    return yaml.safe_load(SOURCE.read_text("utf-8"))["enums"]["Predicate"]["permissible_values"]


def test_list_has_20_to_30_predicates(predicates):
    assert 20 <= len(predicates) <= 30


def test_each_predicate_traces_to_a_real_competency_question(predicates):
    known = set(re.findall(r"\bCQ\d\d\b", (REPO / "docs/competency-questions.md").read_text("utf-8")))
    for name, definition in predicates.items():
        cited = definition["annotations"]["competency_questions"].split()
        assert cited, name
        assert set(cited) <= known, name


def test_each_predicate_aligns_to_a_current_biolink_predicate_or_records_a_gap(predicates):
    lines = (SCHEMA_DIR / "biolink-predicates.txt").read_text("utf-8").splitlines()
    current = {l for l in lines if not l.startswith("#")}
    for name, definition in predicates.items():
        mappings = definition.get("exact_mappings", []) + definition.get("close_mappings", [])
        assert mappings, name
        for mapping in mappings:
            assert mapping.removeprefix("biolink:").replace("_", " ") in current, (name, mapping)
        if not definition.get("exact_mappings"):
            assert definition["annotations"].get("biolink_gap"), name


def test_generated_json_schema_is_in_sync_with_the_source():
    committed = json.loads((GENERATED / "sdkg.schema.json").read_text("utf-8"))
    assert committed == generate_json_schema(SOURCE)


def test_owl_schema_parses_and_describes_claims_without_instances():
    graph = rdflib.Graph().parse(GENERATED / "sdkg.owl.ttl", format="turtle")
    classes = {str(s) for s in graph.subjects(rdflib.RDF.type, rdflib.OWL.Class)}

    assert any(c.endswith("/Claim") for c in classes)
    assert not list(graph.subjects(rdflib.RDF.type, rdflib.URIRef(next(c for c in classes if c.endswith("/Claim")))))


def test_json_ld_context_covers_claim_fields():
    context = json.loads((GENERATED / "sdkg.context.jsonld").read_text("utf-8"))["@context"]

    for field in ("claim_id", "predicate", "evidence_level", "claim_status"):
        assert field in context


def test_shacl_constraints_parse_and_cover_claims():
    graph = rdflib.Graph().parse(GENERATED / "sdkg.shacl.ttl", format="turtle")
    targets = {str(o) for o in graph.objects(None, rdflib.URIRef("http://www.w3.org/ns/shacl#targetClass"))}

    assert any(t.endswith("/Claim") for t in targets)


def test_release_that_violates_the_schema_fails_the_build(workspace):
    path = workspace / "sample/recorded/responses.jsonl"
    path.write_text(path.read_text("utf-8").replace('"sign":"positive"', '"sign":"upward"'), "utf-8")

    with pytest.raises(ValueError, match="violates the schema"):
        run_build(workspace, run_extract(workspace))
