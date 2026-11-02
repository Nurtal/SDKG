"""Turn frozen documents into archived raw LLM outputs. Only this module calls an LLM."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Protocol


class ExtractionClient(Protocol):
    model: str
    model_version: str

    def extract(self, document: dict[str, Any], prompt: str) -> dict[str, Any]: ...


class RecordedClient:
    """Replays saved responses, so tests and CI never call an LLM."""

    model = "recorded"
    model_version = "replay"

    def __init__(self, path: str | Path):
        self.responses = {row["doc_id"]: row for row in read_jsonl(Path(path))}

    def extract(self, document: dict[str, Any], prompt: str) -> dict[str, Any]:
        return {"claims": self.responses[document["doc_id"]]["claims"]}


class RecordedDecisions(RecordedClient):
    """Replays saved relevance screening decisions."""

    def extract(self, document: dict[str, Any], prompt: str) -> dict[str, Any]:
        row = self.responses[document["doc_id"]]
        return {"relevant": row["relevant"], "reason": row.get("reason")}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def load_documents(corpus: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(Path(corpus) / "documents.jsonl")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_hash(document: dict[str, Any]) -> str:
    return text_hash(json.dumps(document, sort_keys=True, ensure_ascii=False))


def archive_path(archive: Path, doc_id: str) -> Path:
    return archive / (doc_id.replace(":", "_").replace("/", "_") + ".json")


def write_atomic(path: Path, text: str) -> None:
    """Write so that an interruption can never leave a partial file under the final name."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, "utf-8")
    os.replace(temporary, path)


def _check_resumable(existing: dict[str, Any], expected: dict[str, str], doc_id: str) -> None:
    labels = {
        "prompt_hash": "prompt", "schema_hash": "schema", "document_hash": "document",
        "model": "model", "model_version": "model version",
    }
    for key, label in labels.items():
        if existing[key] != expected[key]:
            raise ValueError(
                f"{doc_id} is archived with a different {label}. Use a new archive directory "
                "instead of mixing extraction runs."
            )


def run_extract(
    documents: Iterable[dict[str, Any]],
    prompt: str,
    schema: str,
    client: ExtractionClient,
    out: str | Path,
) -> None:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for document in documents:
        trace = {
            "model": client.model,
            "model_version": client.model_version,
            "prompt_hash": text_hash(prompt),
            "schema_hash": text_hash(schema),
            "document_hash": document_hash(document),
        }
        path = archive_path(out, document["doc_id"])
        if path.exists():
            _check_resumable(json.loads(path.read_text("utf-8")), trace, document["doc_id"])
            continue
        record = {"doc_id": document["doc_id"], **trace, "response": client.extract(document, prompt)}
        write_atomic(path, json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
