"""Run extraction through the Message Batches API, with recorded costs and a hard spending limit."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from sdkg.extraction import archive_path, document_hash, text_hash, write_atomic
from sdkg.schema_tools import GENERATED_JSON_SCHEMA

DEFAULT_MODEL = "claude-opus-5-5"
# Batch prices in USD per million tokens, half of the standard rate. Check them before a paid run.
BATCH_PRICES = {"claude-opus-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10, "cache_write": 2.50}}
# Upper bound on input tokens per character, used only to keep the spending limit conservative.
TOKENS_PER_CHARACTER_UPPER_BOUND = 1.0
MAX_BATCH = 1000


def _enum(name: str, nullable: bool = True) -> dict[str, Any]:
    schema = json.loads(GENERATED_JSON_SCHEMA.read_text("utf-8"))
    values = list(schema["$defs"][name]["enum"])
    return {"type": ["string", "null"], "enum": values + [None]} if nullable else {"type": "string", "enum": values}


def extraction_output_schema() -> dict[str, Any]:
    """The structured output for extraction. The closed lists come from the LinkML schema."""
    nullable_text = {"type": ["string", "null"]}
    nullable_bool = {"type": ["boolean", "null"]}
    context = {
        "species": nullable_text, "tissue": nullable_text, "population": nullable_text,
        "assay": nullable_text, "evidence_model": _enum("EvidenceModel"),
    }
    claim = {
        "subject": {"type": "string"}, "predicate": _enum("Predicate", nullable=False),
        "object": {"type": "string"}, "span": {"type": "string"}, "sign": _enum("Sign"),
        "negated": {"type": "boolean"}, "directed": nullable_bool, "direct": nullable_bool,
        "biomarker_role": _enum("BiomarkerRole"), "sjd_context": {"type": "boolean"},
        "trial_id": nullable_text,
        "context": {"type": "object", "properties": context, "required": list(context), "additionalProperties": False},
    }
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {"type": "object", "properties": claim, "required": list(claim), "additionalProperties": False},
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    }


def screening_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"relevant": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["relevant", "reason"],
        "additionalProperties": False,
    }


def _custom_id(doc_id: str) -> str:
    return "doc_" + hashlib.sha256(doc_id.encode()).hexdigest()[:40]


def _user_message(document: dict[str, Any]) -> str:
    return f"<abstract>\n{document['text']}\n</abstract>"


class BatchRunner:
    def __init__(
        self,
        client: Any,
        prompt: str,
        schema: dict[str, Any],
        out: str | Path,
        max_spend_usd: float,
        model: str = DEFAULT_MODEL,
        effort: str = "medium",
        max_tokens: int = 8000,
        poll_seconds: float = 60.0,
        max_polls: int | None = None,
    ):
        if model not in BATCH_PRICES:
            raise ValueError(f"No batch price is recorded for {model}, so the spending limit cannot be enforced")
        self.client, self.prompt, self.schema, self.model = client, prompt, schema, model
        self.out, self.max_spend_usd = Path(out), max_spend_usd
        self.effort, self.max_tokens = effort, max_tokens
        self.poll_seconds, self.max_polls = poll_seconds, max_polls
        self.prices = BATCH_PRICES[model]
        self.trace = {
            "model": model, "model_version": model, "prompt_hash": text_hash(prompt),
            "schema_hash": text_hash(json.dumps(schema, sort_keys=True)),
        }
        self.out.mkdir(parents=True, exist_ok=True)
        self.spend = self._read_spend()

    # State on disk, so that any interruption is safe.

    def _read_spend(self) -> dict[str, Any]:
        path = self.out / "_spend.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0}

    def _save_spend(self) -> None:
        write_atomic(self.out / "_spend.json", json.dumps(self.spend, indent=2, sort_keys=True) + "\n")

    def _pending_path(self) -> Path:
        return self.out / "_pending_batches.json"

    def _pending(self) -> list[dict[str, Any]]:
        path = self._pending_path()
        return json.loads(path.read_text("utf-8")) if path.exists() else []

    def _save_pending(self, pending: list[dict[str, Any]]) -> None:
        write_atomic(self._pending_path(), json.dumps(pending, indent=1) + "\n")

    # Costs

    def _cost(self, usage: dict[str, int]) -> float:
        return (
            usage["input_tokens"] * self.prices["input"]
            + usage["output_tokens"] * self.prices["output"]
            + usage["cache_read_input_tokens"] * self.prices["cache_read"]
            + usage["cache_creation_input_tokens"] * self.prices["cache_write"]
        ) / 1_000_000

    def _worst_case(self, document: dict[str, Any]) -> float:
        characters = len(self.prompt) + len(_user_message(document)) + len(json.dumps(self.schema))
        input_tokens = math.ceil(characters * TOKENS_PER_CHARACTER_UPPER_BOUND)
        return (input_tokens * self.prices["input"] + self.max_tokens * self.prices["output"]) / 1_000_000

    def _reserved(self, pending: list[dict[str, Any]]) -> float:
        return sum(batch["worst_case_usd"] for batch in pending)

    # The run

    def _check_archive(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        remaining = []
        for document in documents:
            path = archive_path(self.out, document["doc_id"])
            if not path.exists():
                remaining.append(document)
                continue
            record = json.loads(path.read_text("utf-8"))
            labels = {"prompt_hash": "prompt", "schema_hash": "schema", "model": "model", "model_version": "model version"}
            for key, label in labels.items():
                if record[key] != self.trace[key]:
                    raise ValueError(f"{document['doc_id']} is archived with a different {label}. Use a new archive directory.")
            if record["document_hash"] != document_hash(document):
                raise ValueError(f"{document['doc_id']} is archived with a different document. Use a new archive directory.")
        return remaining

    def _request(self, document: dict[str, Any]) -> dict[str, Any]:
        return {
            "custom_id": _custom_id(document["doc_id"]),
            "params": {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.prompt,
                "output_config": {
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": self.schema},
                },
                "messages": [{"role": "user", "content": _user_message(document)}],
            },
        }

    def _submit_affordable(self, documents: list[dict[str, Any]], pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Submit only what the limit covers even if every request costs its worst case."""
        available = self.max_spend_usd - self.spend["cost_usd"] - self._reserved(pending)
        chosen, worst_case = [], 0.0
        for document in documents[:MAX_BATCH]:
            cost = self._worst_case(document)
            if worst_case + cost > available:
                break
            chosen.append(document)
            worst_case += cost
        if not chosen:
            return []
        batch = self.client.messages.batches.create(requests=[self._request(d) for d in chosen])
        pending.append({"id": batch.id, "documents": [d["doc_id"] for d in chosen], "worst_case_usd": worst_case})
        # Saved at once, so that an interrupted run collects this batch instead of paying for it again.
        self._save_pending(pending)
        return chosen

    def _wait(self, batch_id: str) -> None:
        polls = 0
        while True:
            if self.client.messages.batches.retrieve(batch_id).processing_status == "ended":
                return
            polls += 1
            if self.max_polls is not None and polls >= self.max_polls:
                raise TimeoutError(f"Batch {batch_id} has not ended. Run again to keep waiting.")
            time.sleep(self.poll_seconds)

    def _usable(self, message: Any) -> tuple[dict[str, Any] | None, str | None]:
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            return None, f"refusal:{getattr(details, 'category', None)}"
        if message.stop_reason != "end_turn":
            return None, str(message.stop_reason)
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None, "invalid_json"
        try:
            jsonschema.validate(parsed, self.schema)
        except jsonschema.ValidationError:
            return None, "schema_mismatch"
        return parsed, None

    def _collect(self, batch: dict[str, Any], by_custom_id: dict[str, dict[str, Any]], failures: list[dict[str, Any]]) -> None:
        self._wait(batch["id"])
        for item in self.client.messages.batches.results(batch["id"]):
            document = by_custom_id[item.custom_id]
            result = item.result
            if result.type != "succeeded":
                failures.append({"doc_id": document["doc_id"], "reason": result.type})
                continue
            message = result.message
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
                "cache_read_input_tokens": message.usage.cache_read_input_tokens or 0,
                "cache_creation_input_tokens": message.usage.cache_creation_input_tokens or 0,
            }
            for key, value in usage.items():
                self.spend[key] += value
            self.spend["cost_usd"] += self._cost(usage)
            parsed, problem = self._usable(message)
            if problem:
                # Never archived, because an empty archive entry would read as "no claims found".
                failures.append({"doc_id": document["doc_id"], "reason": problem})
                continue
            record = {
                "doc_id": document["doc_id"], **self.trace, "document_hash": document_hash(document),
                "served_model": message.model, "batch_id": batch["id"], "usage": usage, "response": parsed,
            }
            write_atomic(archive_path(self.out, document["doc_id"]), json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._save_spend()

    def run(self, documents: Iterable[dict[str, Any]]) -> dict[str, Any]:
        documents = list(documents)
        by_custom_id = {_custom_id(d["doc_id"]): d for d in documents}
        known = {d["doc_id"] for d in documents}
        failures: list[dict[str, Any]] = []

        pending = self._pending()
        while pending:
            batch = pending[0]
            if not set(batch["documents"]) <= known:
                raise ValueError(f"Batch {batch['id']} contains documents outside this corpus")
            self._collect(batch, by_custom_id, failures)
            pending = pending[1:]
            self._save_pending(pending)

        retried: set[str] = {f["doc_id"] for f in failures}
        limited = False
        while True:
            remaining = [d for d in self._check_archive(documents) if d["doc_id"] not in retried]
            if not remaining:
                break
            chosen = self._submit_affordable(remaining, pending)
            if not chosen:
                limited = True
                break
            self._collect(pending[0], by_custom_id, failures)
            pending = pending[1:]
            self._save_pending(pending)
            # Failed documents wait for the next run, so that one run cannot loop on a persistent failure.
            retried |= {f["doc_id"] for f in failures}

        write_atomic(
            self.out / "_failures.jsonl",
            "".join(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in failures),
        )
        return {
            **self.spend,
            "failed": len(failures),
            "remaining": len(self._check_archive(documents)) - len(failures),
            "stopped_by_spending_limit": limited,
        }
