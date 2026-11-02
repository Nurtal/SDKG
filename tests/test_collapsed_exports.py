"""Issue #16: collapsed exports and subgraph extraction."""
from __future__ import annotations

import csv
import json

import networkx as nx
import pytest

import sdkg

from conftest import build_with, make_claim, write_databases

A, B, C = "SAMPLE:0001", "SAMPLE:0002", "SAMPLE:0003"
IRF5, STAT4, SJD = "HGNC:6120", "HGNC:11365", "MONDO:0010030"


def edges(release, name="edges_all.tsv"):
    with (release / "exports" / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@pytest.fixture
def mixed(workspace):
    config = write_databases(workspace, [{"source": "reactome", "adapter": "reactome", "path": "reactome.tsv"}])
    return build_with(workspace, {
        A: [make_claim(sign="positive", tissue="blood"), make_claim(subject="STAT4", negated=True)],
        B: [make_claim(sign="negative", tissue="blood"), make_claim(subject="BAFF", evidence_model="animal", species="mouse")],
        C: [make_claim(sign="positive", tissue="saliva")],
    }, databases=config)


def test_claims_about_one_relationship_collapse_into_one_edge_with_counts(mixed):
    edge = next(e for e in edges(mixed) if e["subject"] == IRF5 and e["object"] == SJD)

    assert edge["predicate"] == "associated_with"
    assert edge["support"] == "3"
    assert edge["positive_claims"] == "2"
    assert edge["negative_claims"] == "1"
    assert edge["has_contradiction"] == "true"
    assert edge["layer"] == "disease_core"


def test_null_results_are_excluded_and_counted_in_the_published_rules(mixed):
    assert not [e for e in edges(mixed) if e["subject"] == STAT4 and e["object"] == SJD]
    rules = json.loads((mixed / "exports/collapse_rules.json").read_text("utf-8"))
    assert rules["excluded"]["null_results"] == 1
    assert "null results" in rules["rules"]["exclude"]


def test_collapsed_exports_are_labelled_as_lossy(mixed):
    rules = json.loads((mixed / "exports/collapse_rules.json").read_text("utf-8"))
    graph = nx.read_graphml(mixed / "exports/graph.graphml")

    assert rules["lossy"] is True
    assert "lossy" in graph.graph["description"]
    assert "edges_all.tsv" in rules["files"]


def test_core_edge_list_contains_no_background_edges(mixed):
    assert edges(mixed, "edges_core.tsv")
    assert {e["layer"] for e in edges(mixed, "edges_core.tsv")} == {"disease_core"}
    assert "background" in {e["layer"] for e in edges(mixed)}


def test_human_edge_list_excludes_model_only_evidence(mixed):
    human = edges(mixed, "edges_core_human.tsv")

    assert {e["subject"] for e in human} == {IRF5}
    assert "HGNC:11929" in {e["subject"] for e in edges(mixed, "edges_core.tsv")}


def test_graphml_opens_in_a_standard_network_tool(mixed):
    graph = nx.read_graphml(mixed / "exports/graph.graphml")

    assert graph.nodes[IRF5]["label"] == "IRF5"
    assert graph.nodes[IRF5]["category"] == "gene_or_protein"
    data = graph.get_edge_data(IRF5, SJD)
    assert data["predicate"] == "associated_with"
    assert data["support"] == 3


def test_integer_indexed_files_are_ready_for_graph_learning(mixed):
    with (mixed / "exports/nodes.tsv").open(encoding="utf-8", newline="") as handle:
        nodes = list(csv.DictReader(handle, delimiter="\t"))
    with (mixed / "exports/triples.tsv").open(encoding="utf-8", newline="") as handle:
        triples = list(csv.DictReader(handle, delimiter="\t"))

    assert [int(n["index"]) for n in nodes] == list(range(len(nodes)))
    by_index = {n["index"]: n["entity_id"] for n in nodes}
    assert len(triples) == len(edges(mixed))
    assert (IRF5, "associated_with", SJD) in {(by_index[t["head"]], t["relation"], by_index[t["tail"]]) for t in triples}


def test_no_composite_score_appears_in_collapsed_edges(mixed):
    assert not [c for c in edges(mixed)[0] if "score" in c or "confidence" in c]


# Python package


@pytest.mark.parametrize("filters,expected", [
    ({"layer": "background"}, {"reactome"}),
    ({"claim_status": "curated_source"}, {"reactome"}),
    ({"evidence_level": "animal_or_in_vitro"}, {"sample-literature"}),
    ({"species": "mouse"}, {"sample-literature"}),
    ({"tissue": "saliva"}, {"sample-literature"}),
])
def test_package_filters_claims(mixed, filters, expected):
    assert {c["source"] for c in sdkg.load(mixed).claims(**filters)} == expected


def test_subgraph_around_an_entity_respects_hops_and_filters(mixed):
    loaded = sdkg.load(mixed)

    one = loaded.subgraph([IRF5], hops=1)
    assert one["entities"] >= {IRF5, SJD, "REACTOME:R-HSA-0000001"}
    assert STAT4 not in one["entities"]
    assert all(IRF5 in (c["subject"], c["object"]) for c in one["claims"])

    two = loaded.subgraph([IRF5], hops=2)
    assert "HGNC:11929" in two["entities"]

    core = loaded.subgraph([IRF5], hops=2, layer="disease_core")
    assert "REACTOME:R-HSA-0000001" not in core["entities"]


def test_subgraph_refuses_an_unknown_entity(mixed):
    with pytest.raises(KeyError, match="NOPE:1"):
        sdkg.load(mixed).subgraph(["NOPE:1"])


def test_path_reports_its_background_layer_steps(mixed):
    paths = sdkg.load(mixed).paths("REACTOME:R-HSA-0000001", SJD, max_hops=3)

    assert paths[0]["entities"] == ["REACTOME:R-HSA-0000001", IRF5, SJD]
    assert paths[0]["background_steps"] == 1
    assert [s["layer"] for s in paths[0]["steps"]] == ["background", "disease_core"]


def test_path_inside_the_disease_core_has_no_background_steps(mixed):
    assert sdkg.load(mixed).paths(IRF5, SJD)[0]["background_steps"] == 0


def test_no_path_returns_an_empty_list(mixed):
    assert sdkg.load(mixed).paths(IRF5, SJD, layer="background") == []
