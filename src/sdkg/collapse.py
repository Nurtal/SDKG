"""Derive simplified, deliberately lossy graphs from claims, under published rules (ADR-0001)."""
from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

EDGE_COLUMNS = (
    "subject", "predicate", "object", "layer", "support", "claim_count", "positive_claims",
    "negative_claims", "has_contradiction", "evidence_levels", "claim_statuses",
)
RULES = {
    "merge": "All claims with the same subject, predicate and object become one edge. Context is discarded.",
    "exclude": "null results are removed, because they do not assert a relationship.",
    "layer": "An edge is disease_core if at least one of its claims is in the disease core, otherwise background.",
    "support": "The number of distinct publications or database sources behind the edge.",
    "has_contradiction": "True if any two of the edge's claims form a contradiction.",
    "composite_score": "None. Use the separate fields.",
}
FILES = {
    "edges_all.tsv": "Every edge in both layers.",
    "edges_core.tsv": "Edges with at least one disease core claim, counting only those claims.",
    "edges_core_human.tsv": "Edges from disease core claims with human evidence only.",
    "nodes.tsv": "Integer index for each entity in edges_all.tsv.",
    "triples.tsv": "edges_all.tsv as integer head, relation and tail.",
    "graph.graphml": "edges_all.tsv with entity labels and categories, for network tools.",
}


def collapse(claims: list[dict[str, Any]], source_of: dict[str, str], contradicted: set[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        grouped[(claim["subject"], claim["predicate"], claim["object"])].append(claim)
    edges = []
    for (subject, predicate, obj), members in sorted(grouped.items()):
        signs = [m["sign"] for m in members]
        edges.append({
            "subject": subject, "predicate": predicate, "object": obj,
            "layer": "disease_core" if any(m["layer"] == "disease_core" for m in members) else "background",
            "support": len({source_of[m["claim_id"]] for m in members}),
            "claim_count": len(members),
            "positive_claims": signs.count("positive"),
            "negative_claims": signs.count("negative"),
            "has_contradiction": "true" if any(m["claim_id"] in contradicted for m in members) else "false",
            "evidence_levels": ";".join(sorted({m["evidence_level"] for m in members if m["evidence_level"]})),
            "claim_statuses": ";".join(sorted({m["claim_status"] for m in members})),
        })
    return edges


def _write_tsv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_graphml(path: Path, edges: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> None:
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    integer_fields = {"support", "claim_count", "positive_claims", "negative_claims"}
    ET.SubElement(root, "key", {"id": "description", "for": "graph", "attr.name": "description", "attr.type": "string"})
    for field in ("label", "category"):
        ET.SubElement(root, "key", {"id": f"n_{field}", "for": "node", "attr.name": field, "attr.type": "string"})
    edge_fields = [c for c in EDGE_COLUMNS if c not in ("subject", "object")]
    for field in edge_fields:
        kind = "int" if field in integer_fields else "string"
        ET.SubElement(root, "key", {"id": f"e_{field}", "for": "edge", "attr.name": field, "attr.type": kind})
    graph = ET.SubElement(root, "graph", edgedefault="directed")
    ET.SubElement(graph, "data", key="description").text = (
        "Collapsed, lossy graph from SDKG. Context and evidence are in the canonical tables."
    )
    used = sorted({e["subject"] for e in edges} | {e["object"] for e in edges})
    for entity in used:
        node = ET.SubElement(graph, "node", id=entity)
        for field in ("label", "category"):
            ET.SubElement(node, "data", key=f"n_{field}").text = str(nodes[entity][field])
    for edge in edges:
        element = ET.SubElement(graph, "edge", source=edge["subject"], target=edge["object"])
        for field in edge_fields:
            ET.SubElement(element, "data", key=f"e_{field}").text = str(edge[field])
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_collapsed(
    out: Path,
    claims: list[dict[str, Any]],
    source_of: dict[str, str],
    contradictions: list[tuple[str, str]],
    entities: list[dict[str, Any]],
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    asserted = [c for c in claims if not c["negated"]]
    contradicted = {claim_id for pair in contradictions for claim_id in pair}
    core = [c for c in asserted if c["layer"] == "disease_core"]
    human = [c for c in core if c["evidence_model"] == "human"]
    edges = collapse(asserted, source_of, contradicted)

    _write_tsv(out / "edges_all.tsv", EDGE_COLUMNS, edges)
    _write_tsv(out / "edges_core.tsv", EDGE_COLUMNS, collapse(core, source_of, contradicted))
    _write_tsv(out / "edges_core_human.tsv", EDGE_COLUMNS, collapse(human, source_of, contradicted))

    nodes = {e["entity_id"]: e for e in entities}
    used = sorted({e["subject"] for e in edges} | {e["object"] for e in edges})
    index = {entity: i for i, entity in enumerate(used)}
    _write_tsv(out / "nodes.tsv", ("index", "entity_id", "label", "category"), [
        {"index": index[e], "entity_id": e, "label": nodes[e]["label"], "category": nodes[e]["category"]} for e in used
    ])
    _write_tsv(out / "triples.tsv", ("head", "relation", "tail"), [
        {"head": index[e["subject"]], "relation": e["predicate"], "tail": index[e["object"]]} for e in edges
    ])
    _write_graphml(out / "graph.graphml", edges, nodes)

    metadata = {
        "lossy": True,
        "note": "Collapsed exports discard context and evidence. The canonical tables are the source of truth.",
        "rules": RULES,
        "files": FILES,
        "excluded": {"null_results": len(claims) - len(asserted)},
    }
    (out / "collapse_rules.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", "utf-8")
