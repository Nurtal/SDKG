"""Extract in a Claude Code session, with no paid API (ADR-0013)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from sdkg.batch import extraction_output_schema
from sdkg.extraction import RecordedClient, archive_path, load_documents, read_jsonl, run_extract

SESSION_MODEL = "claude-opus-5-5"
SESSION_VERSION = "claude-code-session"


class SessionClient(RecordedClient):
    model = SESSION_MODEL
    model_version = SESSION_VERSION


def next_batch(corpus: str | Path, archive: str | Path, size: int, seed: int, out: str | Path, split: str | None = None) -> int:
    """Write the next documents to read, in a reproducible random order. Returns how many remain in all."""
    documents = [d for d in load_documents(corpus) if split is None or d.get("split") == split]
    remaining = [d for d in documents if not archive_path(Path(archive), d["doc_id"]).exists()]
    remaining.sort(key=lambda d: hashlib.sha256(f"{seed}:{d['doc_id']}".encode()).hexdigest())
    rows = [{k: d.get(k) for k in ("doc_id", "title", "text", "year", "study_type")} for d in remaining[:size]]
    Path(out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return len(remaining)


def import_session(corpus: str | Path, responses: str | Path, prompt: str, archive: str | Path) -> int:
    documents = {d["doc_id"]: d for d in load_documents(corpus)}
    rows = read_jsonl(Path(responses))
    schema = extraction_output_schema()
    for row in rows:
        if row["doc_id"] not in documents:
            raise ValueError(f"{row['doc_id']} is not in this corpus")
        try:
            jsonschema.validate({"claims": row["claims"]}, schema)
        except jsonschema.ValidationError as error:
            raise ValueError(f"The response for {row['doc_id']} breaks the output schema: {error.message}") from error
    client = SessionClient(responses)
    # All rows are checked before anything is written, so a bad file leaves the archive untouched.
    run_extract(
        [documents[r["doc_id"]] for r in rows], prompt, json.dumps(schema, sort_keys=True), client, archive,
    )
    return len(rows)
