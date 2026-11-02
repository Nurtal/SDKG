"""Derive exports from the canonical tables (ADR-0008). Claims stay reified in lossless exports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import rdflib

from sdkg.schema_tools import SCHEMA_DIR

VOCAB = "https://nurtal.github.io/SDKG/schema/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD = "http://www.w3.org/2001/XMLSchema#"
BASE = "https://nurtal.github.io/SDKG/id/"

INTEGERS = {"span_start", "span_end"}
BOOLEANS = {"negated", "directed", "direct", "resolved"}
FLOATS = {"extraction_reliability"}
KEYS = {"claims": "claim_id", "evidence": "claim_id", "entities": "entity_id"}
CLASSES = {"claims": "Claim", "evidence": "Evidence", "entities": "Entity"}


def _entity_iri(entity_id: str) -> str:
    return VOCAB + entity_id.removeprefix("sdkg:") if entity_id.startswith("sdkg:") else entity_id


def _entity_id(iri: str) -> str:
    return "sdkg:" + iri.removeprefix(VOCAB) if iri.startswith(VOCAB) else iri


def _iri(table: str, row: dict[str, Any]) -> str:
    if table == "entities":
        return _entity_iri(row["entity_id"])
    return f"{BASE}{'claim' if table == 'claims' else 'evidence'}/{row['claim_id']}"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )


def _ntriples_literal(field: str, value: Any) -> str:
    if field in BOOLEANS:
        return f'"{"true" if value else "false"}"^^<{XSD}boolean>'
    if field in INTEGERS:
        return f'"{value}"^^<{XSD}integer>'
    if field in FLOATS:
        return f'"{value!r}"^^<{XSD}float>'
    return f'"{_escape(str(value))}"'


def _fields(table: str, row: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    for field, value in row.items():
        # entity_id is the node's own identifier, as the generated context defines it.
        if value is not None and not (table == "entities" and field == "entity_id"):
            yield field, value


def write_lossless(out: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    graph: list[dict[str, Any]] = []
    for table, rows in tables.items():
        for row in sorted(rows, key=lambda r: r[KEYS[table]]):
            iri = _iri(table, row)
            lines.append(f"<{iri}> <{RDF_TYPE}> <{VOCAB}{CLASSES[table]}> .")
            node: dict[str, Any] = {"@id": iri, "@type": CLASSES[table]}
            for field, value in _fields(table, row):
                lines.append(f"<{iri}> <{VOCAB}{field}> {_ntriples_literal(field, value)} .")
                node[field] = value
            graph.append(node)
    (out / "graph.nt").write_text("\n".join(sorted(lines)) + "\n", "utf-8")
    context = json.loads((SCHEMA_DIR / "generated" / "sdkg.context.jsonld").read_text("utf-8"))["@context"]
    document = {"@context": context, "@graph": graph}
    (out / "graph.jsonld").write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n", "utf-8")


def _empty_row(table: str, columns: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    return {c: None for c in columns[table]}


def _read_graph(graph: rdflib.Graph) -> dict[str, dict[str, dict[str, Any]]]:
    from sdkg.build import CLAIM_COLUMNS, ENTITY_COLUMNS, EVIDENCE_COLUMNS

    columns = {"claims": CLAIM_COLUMNS, "evidence": EVIDENCE_COLUMNS, "entities": ENTITY_COLUMNS}
    result: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in columns}
    for table, class_name in CLASSES.items():
        for node in graph.subjects(rdflib.RDF.type, rdflib.URIRef(VOCAB + class_name)):
            row = _empty_row(table, columns)
            for predicate, value in graph.predicate_objects(node):
                field = str(predicate).removeprefix(VOCAB)
                if field in row:
                    row[field] = value.toPython()
            if table == "entities":
                row["entity_id"] = _entity_id(str(node))
            result[table][row[KEYS[table]]] = row
    return result


def read_rdf_export(path: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    return _read_graph(rdflib.Graph().parse(path, format="nt"))


def read_jsonld_export(path: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    return _read_graph(rdflib.Graph().parse(path, format="json-ld"))
