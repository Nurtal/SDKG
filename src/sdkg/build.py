"""Build a release deterministically from archived LLM outputs and frozen sources."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import duckdb

from sdkg.aggregate import evidence_level, find_contradictions, group_claims
from sdkg.collapse import write_collapsed
from sdkg.databases import DatabaseConfig, ResolvedRecord, load_records, within_hops
from sdkg.exports import write_lossless
from sdkg.extraction import document_hash, load_documents, text_hash
from sdkg.licences import LicenceManifest
from sdkg.normalise import HYPHENS, Lexicon
from sdkg.schema_tools import allowed_predicates, claim_validator

CONTEXT_FIELDS = ("species", "tissue", "population", "assay", "evidence_model")
CLAIM_COLUMNS = (
    "claim_id", "subject", "predicate", "object", "sign", "negated", "directed", "direct",
    *CONTEXT_FIELDS, "biomarker_role", "layer", "claim_status", "evidence_level",
    "extraction_reliability", "source", "source_version", "source_record",
    "trial_id", "trial_phase", "trial_status", "endpoint",
)
COLUMN_TYPES = {
    "span_start": "INTEGER", "span_end": "INTEGER", "negated": "BOOLEAN", "directed": "BOOLEAN",
    "direct": "BOOLEAN", "extraction_reliability": "DOUBLE", "resolved": "BOOLEAN",
    "score": "DOUBLE", "support": "INTEGER", "positive_claims": "INTEGER", "negative_claims": "INTEGER",
}
EVIDENCE_COLUMNS = ("claim_id", "pmid", "span_start", "span_end", "span_hash", "span_text")
ENTITY_COLUMNS = ("entity_id", "label", "category", "resolved")


GROUP_FIELDS = ("subject", "predicate", "object", "species", "tissue", "population", "assay", "evidence_model", "negated")
GROUP_COLUMNS = ("group_id", "support", "positive_claims", "negative_claims", "claim_ids", *GROUP_FIELDS)


def claim_id(claim: dict[str, Any], subject: str, obj: str, doc_id: str, start: int, end: int) -> str:
    content = {
        "subject": subject,
        "predicate": claim["predicate"],
        "object": obj,
        "sign": claim.get("sign"),
        "negated": bool(claim.get("negated")),
        "context": {k: claim.get("context", {}).get(k) for k in CONTEXT_FIELDS},
        "pmid": doc_id,
        "start": start,
        "end": end,
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return f"C{digest[:24]}"


def database_claim_row(item: ResolvedRecord) -> dict[str, Any]:
    record = item.record
    content = {
        "subject": item.subject.entity_id, "predicate": record.predicate, "object": item.object.entity_id,
        "sign": record.sign, "negated": record.negated, "source": item.source, "record": record.record_id,
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    row = {
        "claim_id": f"C{digest[:24]}", "subject": item.subject.entity_id, "predicate": record.predicate,
        "object": item.object.entity_id, "sign": record.sign, "negated": record.negated, "directed": None,
        "direct": None, **{k: None for k in CONTEXT_FIELDS}, "biomarker_role": None, "layer": item.layer,
        "claim_status": "curated_source", "evidence_level": "curated_database", "extraction_reliability": None,
        "source": item.source, "source_version": item.version, "source_record": record.record_id,
        "trial_id": None, "trial_phase": None, "trial_status": None, "endpoint": None,
    }
    row.update(record.fields)
    return row


TYPOGRAPHIC_CLASSES = {
    "-": "[-\u2010\u2011\u2012\u2013\u2014\u2015\u2212]",
    "'": "['\u2018\u2019\u02bc]",
    '"': '["\u201c\u201d]',
}


def locate_span(text: str, span: str) -> tuple[int, int] | None:
    """Find a span, allowing only typographic differences. Words and numbers must match exactly.

    Published abstracts often contain thin spaces and special hyphens, which a copy of the text may
    not keep. An empty passage would match anywhere, so it can never verify a claim.
    """
    if not span.strip():
        return None
    start = text.find(span)
    if start >= 0:
        return start, start + len(span)
    parts = []
    for chunk in re.split(r"(\s+)", span.strip()):
        if chunk.isspace():
            parts.append(r"\s+")
        else:
            variants = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
            parts.extend(
                TYPOGRAPHIC_CLASSES.get(variants.get(c, HYPHENS.sub("-", c)), re.escape(c)) for c in chunk
            )
    match = re.search("".join(parts), text)
    return match.span() if match else None


def write_table(db: duckdb.DuckDBPyConnection, path: Path, columns: Sequence[str], rows: list[tuple]) -> None:
    db.execute("DROP TABLE IF EXISTS t")
    db.execute("CREATE TABLE t (" + ", ".join(f'"{c}" {COLUMN_TYPES.get(c, "VARCHAR")}' for c in columns) + ")")
    if rows:
        db.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(columns))})", rows)
    order = ", ".join(f'"{c}"' for c in columns)
    target = str(path).replace("'", "''")
    db.execute(f"COPY (SELECT * FROM t ORDER BY {order}) TO '{target}' (FORMAT PARQUET)")


def run_build(
    corpus: str | Path,
    archive: str | Path,
    licences: str | Path,
    lexicon: str | Path,
    out: str | Path,
    version: str,
    allow_unconfirmed: bool = False,
    databases: str | Path | None = None,
) -> None:
    manifest = LicenceManifest.read(licences)
    corpus_info = json.loads((Path(corpus) / "corpus.json").read_text("utf-8"))
    config = DatabaseConfig.read(databases) if databases else None
    publishable = manifest.check([corpus_info["source"], *(config.sources() if config else [])], allow_unconfirmed)
    documents = {d["doc_id"]: d for d in load_documents(corpus)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    claims: dict[str, tuple] = {}
    evidence: dict[str, tuple] = {}
    entities: dict[str, tuple] = {}
    unresolved: dict[tuple[str, str], dict[str, str]] = {}
    names = Lexicon(lexicon)
    predicates = allowed_predicates()
    rejected: Counter[str] = Counter()

    validator = claim_validator()
    archive_digest = hashlib.sha256()
    provenance: dict[str, set[str]] = {"model": set(), "model_version": set(), "prompt_hash": set(), "schema_hash": set()}
    for path in sorted(p for p in Path(archive).glob("*.json") if not p.name.startswith("_")):
        raw = path.read_text("utf-8")
        archive_digest.update(text_hash(raw).encode())
        record = json.loads(raw)
        document = documents[record["doc_id"]]
        if record["document_hash"] != document_hash(document):
            raise ValueError(f"Archived output for {record['doc_id']} does not match the frozen corpus")
        for key, values in provenance.items():
            values.add(record[key])
        for claim in record["response"]["claims"]:
            if claim.get("sjd_context") is False:
                rejected["outside_sjd_context"] += 1
                continue
            if claim["predicate"] not in predicates:
                rejected["predicate_not_allowed"] += 1
                continue
            if not (claim["subject"].strip() and claim["object"].strip()):
                rejected["empty_entity"] += 1
                continue
            located = locate_span(document["text"], claim["span"])
            if located is None:
                rejected["span_not_found"] += 1
                continue
            start, end = located
            subject, obj = names.resolve(claim["subject"]), names.resolve(claim["object"])
            cid = claim_id(claim, subject.entity_id, obj.entity_id, document["doc_id"], start, end)
            context = claim.get("context", {})
            row = {
                "claim_id": cid, "subject": subject.entity_id, "predicate": claim["predicate"],
                "object": obj.entity_id, "sign": claim.get("sign"), "negated": bool(claim.get("negated")),
                "directed": claim.get("directed"), "direct": claim.get("direct"),
                **{k: context.get(k) for k in CONTEXT_FIELDS},
                "biomarker_role": claim.get("biomarker_role"), "layer": "disease_core",
                "claim_status": "ai_extracted", "evidence_level": evidence_level(document, context.get("evidence_model")),
                "extraction_reliability": None,
                "source": corpus_info["source"], "source_version": corpus_info.get("frozen_on"),
                "source_record": document["doc_id"],
                "trial_id": claim["trial_id"] if claim.get("trial_id") and claim["trial_id"] in document["text"] else None,
                "trial_phase": None, "trial_status": None, "endpoint": None,
            }
            problem = next(validator.iter_errors(row), None)
            if problem is not None:
                raise ValueError(f"Claim from {document['doc_id']} violates the schema: {problem.message}")
            claims[cid] = tuple(row[c] for c in CLAIM_COLUMNS)
            source_span = document["text"][start:end]
            span_text = source_span if manifest.may_publish_span(document.get("licence")) else None
            evidence[cid] = (cid, document["doc_id"], start, end, text_hash(source_span), span_text)
            for mention, entity in ((claim["subject"], subject), (claim["object"], obj)):
                entities[entity.entity_id] = (entity.entity_id, entity.label, entity.category, entity.resolved)
                if not entity.resolved:
                    unresolved[(entity.entity_id, mention)] = {
                        "entity_id": entity.entity_id, "mention": mention, "reason": entity.reason,
                    }

    database_skipped: dict[str, int] = {}
    held_out: list = []
    if config:
        records, held_out, database_skipped = load_records(config, names)
        core_ids = {row[1] for row in claims.values()} | {row[3] for row in claims.values()} | {config.disease_id}
        core_records = [r for r in records if r.layer == "disease_core"]
        core_ids |= {e for r in core_records for e in (r.subject.entity_id, r.object.entity_id)}
        background = within_hops([r for r in records if r.layer == "background"], core_ids, config.max_hops)
        for item in core_records + background:
            row = database_claim_row(item)
            problem = next(validator.iter_errors(row), None)
            if problem is not None:
                raise ValueError(f"Record {item.record.record_id} from {item.source} violates the schema: {problem.message}")
            claims[row["claim_id"]] = tuple(row[c] for c in CLAIM_COLUMNS)
            for entity in (item.subject, item.object):
                entities[entity.entity_id] = (entity.entity_id, entity.label, entity.category, entity.resolved)

    db = duckdb.connect()
    db.execute("SET threads=1")
    write_table(db, out / "claims.parquet", CLAIM_COLUMNS, list(claims.values()))
    write_table(db, out / "evidence.parquet", EVIDENCE_COLUMNS, list(evidence.values()))
    write_table(db, out / "entities.parquet", ENTITY_COLUMNS, [entities[k] for k in sorted(entities)])
    # Keep held-out associations out of the disease core, whatever an adapter does (ADR-0011).
    reserved = {(h.target, h.disease) for h in held_out}
    for row in claims.values():
        fields = dict(zip(CLAIM_COLUMNS, row))
        if fields["source"] == "open-targets" and fields["layer"] == "disease_core" and (fields["subject"], fields["object"]) in reserved:
            raise ValueError(f"A held-out association reached the disease core: {fields['claim_id']}")
    if held_out:
        (out / "held_out").mkdir(exist_ok=True)
        write_table(
            db, out / "held_out" / "open_targets_sjd.parquet", ("target", "disease", "score", "record_id"),
            [(h.target, h.disease, h.score, h.record_id) for h in held_out],
        )
    claim_rows = [dict(zip(CLAIM_COLUMNS, row)) for row in claims.values()]
    pmid_of = {row["claim_id"]: row["source"] for row in claim_rows}
    pmid_of.update({cid: row[1] for cid, row in evidence.items()})
    groups = group_claims(claim_rows, pmid_of)
    group_rows = [(f"G{i:07d}", g["support"], g["positive_claims"], g["negative_claims"], json.dumps(g["claim_ids"]), *[g[k] for k in GROUP_FIELDS]) for i, g in enumerate(groups)]
    write_table(db, out / "claim_groups.parquet", GROUP_COLUMNS, group_rows)
    contradictions = find_contradictions(claim_rows)
    write_table(db, out / "contradictions.parquet", ("claim_id_a", "claim_id_b"), contradictions)
    write_lossless(out / "exports", {
        "claims": claim_rows,
        "evidence": [dict(zip(EVIDENCE_COLUMNS, row)) for row in evidence.values()],
        "entities": [dict(zip(ENTITY_COLUMNS, entities[k])) for k in sorted(entities)],
    })
    write_collapsed(
        out / "exports", claim_rows, pmid_of, contradictions,
        [dict(zip(ENTITY_COLUMNS, entities[k])) for k in sorted(entities)],
    )
    review = [unresolved[k] for k in sorted(unresolved)]
    (out / "unresolved_entities.json").write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n", "utf-8")
    unresolved_count = sum(not e[3] for e in entities.values())
    metadata = {
        "unresolved_entity_rate": unresolved_count / len(entities) if entities else 0.0,
        "version": version,
        "publishable": publishable,
        "documents": len(documents),
        "development_documents": sum(d.get("split") == "development" for d in documents.values()),
        "claims": len(claims),
        "rejected_claims": dict(sorted(rejected.items())),
        "archive_hash": archive_digest.hexdigest(),
        "excluded_sources": config.excluded if config else [],
        "database_records_skipped": dict(sorted(database_skipped.items())),
        "extraction": {key: sorted(values) for key, values in provenance.items()},
    }
    (out / "release.json").write_text(json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")
