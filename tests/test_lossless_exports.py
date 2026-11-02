"""Issue #15: lossless RDF and JSON-LD exports."""
from __future__ import annotations

import json

import pyshacl
import pytest
import rdflib

import sdkg
from sdkg.exports import read_jsonld_export, read_rdf_export

from conftest import REPO, build_with, make_claim, write_databases

SHAPES = REPO / "schema/generated/sdkg.shacl.ttl"
A, B = "SAMPLE:0001", "SAMPLE:0002"


@pytest.fixture
def rich(workspace):
    """A release with AI-extracted and curated claims, a null result and an unresolved entity."""
    config = write_databases(workspace, [{"source": "reactome", "adapter": "reactome", "path": "reactome.tsv"}])
    return build_with(workspace, {
        A: [make_claim(sign="positive", tissue="blood"), make_claim(subject="Unmapped concept", negated=True)],
        B: [make_claim(subject="STAT4", evidence_model="animal", species="mouse")],
    }, databases=config)


def canonical(release):
    loaded = sdkg.load(release)
    columns = "SELECT * FROM read_parquet('{}/{}.parquet')"
    tables = {}
    for table, key in (("claims", "claim_id"), ("evidence", "claim_id"), ("entities", "entity_id")):
        rows = loaded._rows(columns.format(release, table))
        tables[table] = {r[key]: r for r in rows}
    return tables


def test_rdf_export_conforms_to_the_generated_shacl_constraints(rich):
    conforms, _, message = pyshacl.validate(
        rdflib.Graph().parse(rich / "exports/graph.nt", format="nt"),
        shacl_graph=rdflib.Graph().parse(SHAPES, format="turtle"),
    )
    assert conforms, message


def test_json_ld_export_conforms_to_the_generated_shacl_constraints(rich):
    conforms, _, message = pyshacl.validate(
        rdflib.Graph().parse(rich / "exports/graph.jsonld", format="json-ld"),
        shacl_graph=rdflib.Graph().parse(SHAPES, format="turtle"),
    )
    assert conforms, message


def test_shacl_validation_can_actually_fail(rich):
    graph = rdflib.Graph().parse(rich / "exports/graph.nt", format="nt")
    predicate = rdflib.URIRef("https://nurtal.github.io/SDKG/schema/predicate")
    node = next(graph.subjects(predicate, None))
    graph.set((node, predicate, rdflib.Literal("invented_predicate")))

    conforms, _, _ = pyshacl.validate(graph, shacl_graph=rdflib.Graph().parse(SHAPES, format="turtle"))
    assert not conforms


def test_json_ld_export_uses_the_generated_context(rich):
    document = json.loads((rich / "exports/graph.jsonld").read_text("utf-8"))
    context = json.loads((REPO / "schema/generated/sdkg.context.jsonld").read_text("utf-8"))["@context"]

    assert document["@context"] == context


@pytest.mark.parametrize("reader,name", [(read_rdf_export, "graph.nt"), (read_jsonld_export, "graph.jsonld")])
def test_round_trip_preserves_every_field(rich, reader, name):
    assert reader(rich / "exports" / name) == canonical(rich)


def test_round_trip_covers_null_results_and_both_layers(rich):
    claims = read_rdf_export(rich / "exports/graph.nt")["claims"].values()

    assert any(c["negated"] for c in claims)
    assert {c["layer"] for c in claims} == {"disease_core", "background"}
    assert {c["claim_status"] for c in claims} == {"ai_extracted", "curated_source"}


def test_exports_are_written_identically_on_rebuild(workspace):
    first = build_with(workspace, {A: [make_claim()]}, out="one", archive="a1")
    second = build_with(workspace, {A: [make_claim()]}, out="two", archive="a2")

    for name in ("graph.nt", "graph.jsonld"):
        assert (first / "exports" / name).read_bytes() == (second / "exports" / name).read_bytes()


def test_span_text_in_exports_follows_the_licence_rules(workspace):
    span = "Synthetic test abstract"
    closed = build_with(workspace, {A: [make_claim()]}, out="closed", archive="a1")
    assert span not in (closed / "exports/graph.nt").read_text("utf-8")
    assert span not in (closed / "exports/graph.jsonld").read_text("utf-8")

    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["publish_span_text"] = True
    manifest.write_text(json.dumps(data), "utf-8")
    opened = build_with(workspace, {A: [make_claim()]}, out="open", archive="a2")
    assert span in (opened / "exports/graph.nt").read_text("utf-8")
    assert span in (opened / "exports/graph.jsonld").read_text("utf-8")


def test_held_out_associations_are_not_exported(workspace):
    config = write_databases(workspace, [{"source": "open-targets", "adapter": "open_targets", "path": "open_targets.json"}])
    release = build_with(workspace, {A: [make_claim()]}, databases=config)

    assert "ENSG00000000001" not in (release / "exports/graph.nt").read_text("utf-8")
