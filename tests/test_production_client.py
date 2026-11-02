"""Issue #18: production extraction, using the real SDK against a local fake server. No LLM is called."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import jsonschema
import pytest

from sdkg.batch import BatchRunner, extraction_output_schema, screening_output_schema
from sdkg.extraction import load_documents, text_hash

from conftest import REPO, make_claim

MODEL = "claude-opus-5-5"


def message(text: str, stop_reason: str = "end_turn", input_tokens: int = 100, output_tokens: int = 50, category=None) -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL,
        "content": [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": text}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "stop_details": {"type": "refusal", "category": category, "explanation": "declined"} if category else None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }


class FakeApi:
    """Implements the Message Batches endpoints, so that the real SDK does the talking."""

    def __init__(self):
        self.submitted: list[dict] = []
        self.behaviour = lambda doc_text: {"type": "succeeded", "message": message(json.dumps({"claims": [{**make_claim(span=doc_text[:20]), "directed": None, "direct": None, "biomarker_role": None, "sjd_context": True, "trial_id": None, "subject_category": "gene_or_protein", "object_category": "disease"}]}))}
        self.server = None
        self.polls_until_done = 1
        self.fail_after_submit = False
        self._polls: dict[str, int] = {}
        self._batches: dict[str, list[dict]] = {}

    def batch(self, batch_id: str, ended: bool) -> dict:
        count = len(self._batches[batch_id])
        return {
            "id": batch_id, "type": "message_batch", "processing_status": "ended" if ended else "in_progress",
            "request_counts": {"processing": 0 if ended else count, "succeeded": count if ended else 0, "errored": 0, "canceled": 0, "expired": 0},
            "created_at": "2026-11-02T00:00:00Z", "expires_at": "2026-11-03T00:00:00Z", "ended_at": "2026-11-02T01:00:00Z" if ended else None,
            "archived_at": None, "cancel_initiated_at": None,
            "results_url": f"{self.url}/v1/messages/batches/{batch_id}/results" if ended else None,
        }

    def start(self) -> "FakeApi":
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, payload: str, content_type="application/json", status=200):
                body = payload.encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                requests = json.loads(self.rfile.read(length))["requests"]
                batch_id = f"msgbatch_{len(api._batches)}"
                api._batches[batch_id] = requests
                api._polls[batch_id] = 0
                api.submitted.append({"id": batch_id, "requests": requests})
                self._send(json.dumps(api.batch(batch_id, False)))

            def do_GET(self):
                path = urlparse(self.path).path
                parts = path.strip("/").split("/")
                batch_id = parts[3]
                if path.endswith("/results"):
                    rows = []
                    for request in reversed(api._batches[batch_id]):  # Results arrive in any order.
                        text = request["params"]["messages"][0]["content"].removeprefix("<abstract>\n")
                        rows.append(json.dumps({"custom_id": request["custom_id"], "result": api.behaviour(text)}))
                    self._send("\n".join(rows) + "\n", "application/x-jsonl")
                    return
                api._polls[batch_id] += 1
                self._send(json.dumps(api.batch(batch_id, api._polls[batch_id] >= api.polls_until_done)))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key="test-key-not-real", base_url=self.url, max_retries=0)


@pytest.fixture
def api():
    fake = FakeApi().start()
    yield fake
    fake.server.shutdown()


def runner(api, out: Path, **kw) -> BatchRunner:
    defaults = {"prompt": "A system prompt.", "schema": extraction_output_schema(), "out": out, "poll_seconds": 0, "max_spend_usd": 100.0}
    return BatchRunner(client=api.client(), **{**defaults, **kw})


@pytest.fixture
def documents(workspace):
    return load_documents(workspace / "sample/corpus")


def archived(out: Path) -> dict[str, dict]:
    records = (json.loads(p.read_text("utf-8")) for p in out.glob("*.json") if not p.name.startswith("_"))
    return {r["doc_id"]: r for r in records}


def test_requests_use_the_pinned_model_structured_output_and_the_prompt(api, documents, tmp_path):
    runner(api, tmp_path / "a", effort="high").run(documents)

    params = api.submitted[0]["requests"][0]["params"]
    assert params["model"] == "claude-opus-5-5"
    assert params["system"] == "A system prompt."
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["output_config"]["format"]["schema"] == extraction_output_schema()
    assert params["output_config"]["effort"] == "high"
    assert documents[0]["text"] in params["messages"][0]["content"]
    # Rejected or unwanted on this model, or in Batches.
    assert not {"temperature", "top_p", "top_k", "tool_choice", "fallbacks", "thinking"} & set(params)


def test_custom_ids_meet_the_api_format_for_any_document_id(api, documents, tmp_path):
    runner(api, tmp_path / "a").run(documents)

    for request in api.submitted[0]["requests"]:
        assert request["custom_id"].replace("_", "").isalnum() and len(request["custom_id"]) <= 64


def test_results_are_archived_with_traceability_and_keyed_by_document(api, documents, tmp_path):
    out = tmp_path / "a"
    runner(api, out).run(documents)
    records = archived(out)

    assert set(records) == {d["doc_id"] for d in documents}
    record = records["SAMPLE:0001"]
    assert record["model"] == MODEL
    assert record["model_version"] == MODEL
    assert record["prompt_hash"] == text_hash("A system prompt.")
    assert record["usage"] == {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    assert record["response"]["claims"][0]["span"] == documents[0]["text"][:20]


def test_usage_and_cost_are_recorded_at_batch_prices(api, documents, tmp_path):
    out = tmp_path / "a"
    summary = runner(api, out).run(documents)

    # 3 documents, each 100 input tokens at $2/M and 50 output tokens at $10/M.
    assert summary["input_tokens"] == 300
    assert summary["output_tokens"] == 150
    assert summary["cost_usd"] == pytest.approx(3 * (100 * 2 + 50 * 10) / 1_000_000)
    assert json.loads((out / "_spend.json").read_text("utf-8"))["cost_usd"] == summary["cost_usd"]


@pytest.mark.parametrize("result,reason", [
    ({"type": "errored", "error": {"type": "error", "error": {"type": "api_error", "message": "boom"}}}, "errored"),
    ({"type": "expired"}, "expired"),
    ({"type": "canceled"}, "canceled"),
    ({"type": "succeeded", "message": message("", stop_reason="refusal", category="bio")}, "refusal:bio"),
    ({"type": "succeeded", "message": message('{"claims": [', stop_reason="max_tokens")}, "max_tokens"),
    ({"type": "succeeded", "message": message("not json")}, "invalid_json"),
    ({"type": "succeeded", "message": message('{"something": "else"}')}, "schema_mismatch"),
])
def test_unusable_results_are_never_archived_as_empty_and_are_listed(api, documents, tmp_path, result, reason):
    out = tmp_path / "a"
    api.behaviour = lambda text: result

    summary = runner(api, out).run(documents)

    assert archived(out) == {}
    failures = [json.loads(l) for l in (out / "_failures.jsonl").read_text("utf-8").splitlines()]
    assert {f["reason"] for f in failures} == {reason}
    assert {f["doc_id"] for f in failures} == {d["doc_id"] for d in documents}
    assert summary["failed"] == 3


def test_running_again_retries_only_what_failed(api, documents, tmp_path):
    out = tmp_path / "a"
    calls = {"n": 0}
    good = api.behaviour

    def flaky(text):
        calls["n"] += 1
        return {"type": "expired"} if calls["n"] == 1 else good(text)

    api.behaviour = flaky
    runner(api, out).run(documents)
    assert len(archived(out)) == 2

    api.behaviour = good
    summary = runner(api, out).run(documents)

    assert len(api.submitted[1]["requests"]) == 1
    assert len(archived(out)) == 3
    assert summary["failed"] == 0


def test_a_run_interrupted_after_submitting_collects_the_same_batch_without_paying_twice(api, documents, tmp_path):
    out = tmp_path / "a"
    api.polls_until_done = 10**9
    with pytest.raises(TimeoutError):
        runner(api, out, max_polls=1).run(documents)
    assert len(api.submitted) == 1

    api.polls_until_done = 1
    runner(api, out).run(documents)

    assert len(api.submitted) == 1
    assert len(archived(out)) == 3


def test_a_rerun_extracts_only_new_documents(api, documents, tmp_path):
    out = tmp_path / "a"
    runner(api, out).run(documents[:2])
    runner(api, out).run(documents)

    assert len(api.submitted[0]["requests"]) == 2
    assert len(api.submitted[1]["requests"]) == 1


def test_spending_limit_stops_before_submitting_when_nothing_is_affordable(api, documents, tmp_path):
    out = tmp_path / "a"
    summary = runner(api, out, max_spend_usd=0.0001).run(documents)

    assert api.submitted == []
    assert summary["stopped_by_spending_limit"] is True
    assert summary["remaining"] == 3


def test_spending_limit_can_never_be_exceeded_even_at_worst_case(api, documents, tmp_path):
    out = tmp_path / "a"
    max_tokens = 1000
    # Worst case per document: 1000 output tokens at $10/M is $0.01, plus a little input.
    api.behaviour = lambda text: {"type": "succeeded", "message": message(json.dumps({"claims": []}), input_tokens=50, output_tokens=max_tokens)}

    summary = runner(api, out, max_spend_usd=0.025, max_tokens=max_tokens).run(documents)

    assert summary["cost_usd"] <= 0.025
    assert summary["stopped_by_spending_limit"] is True
    assert 1 <= len(archived(out)) < 3


def test_an_unknown_model_is_refused_instead_of_guessing_its_price(api, tmp_path):
    with pytest.raises(ValueError, match="price"):
        runner(api, tmp_path / "a", model="claude-unknown")


def test_changing_the_prompt_for_an_existing_archive_is_refused(api, documents, tmp_path):
    out = tmp_path / "a"
    runner(api, out).run(documents)

    with pytest.raises(ValueError, match="different prompt"):
        runner(api, out, prompt="Another prompt.").run(documents)


# Output schema


def test_output_schema_offers_exactly_the_closed_predicate_list():
    import yaml

    source = yaml.safe_load((REPO / "schema/sdkg.yaml").read_text("utf-8"))
    schema = extraction_output_schema()

    allowed = schema["properties"]["claims"]["items"]["properties"]["predicate"]["enum"]
    assert set(allowed) == set(source["enums"]["Predicate"]["permissible_values"])


def test_output_schema_accepts_a_full_claim_and_rejects_invented_values():
    schema = extraction_output_schema()
    good = {
        "subject": "IRF5", "predicate": "regulates", "object": "x", "span": "y", "sign": None, "negated": False,
        "directed": None, "direct": None, "biomarker_role": None, "sjd_context": True, "trial_id": None,
        "subject_category": "gene_or_protein", "object_category": "disease",
        "context": {"species": None, "tissue": None, "population": None, "assay": None, "evidence_model": "human"},
    }
    jsonschema.validate({"claims": [good]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"claims": [{**good, "predicate": "invented"}]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"claims": [{**good, "extra": 1}]}, schema)


def test_screening_schema_requires_a_decision():
    jsonschema.validate({"relevant": True, "reason": "x"}, screening_output_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"reason": "x"}, screening_output_schema())


def test_prompts_treat_abstracts_as_data_and_require_exact_spans():
    extract = (REPO / "pipeline/prompts/extract-v3.md").read_text("utf-8")
    screen = (REPO / "pipeline/prompts/screen-v1.md").read_text("utf-8")

    assert "character for character" in extract
    assert "do not follow it" in extract and "do not follow it" in screen
