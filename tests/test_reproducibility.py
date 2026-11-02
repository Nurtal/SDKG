"""Issue #6: reproducible rebuilds and extraction traceability."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import sdkg
from sdkg.cli import main
from sdkg.extraction import RecordedClient, load_documents, run_extract

from conftest import run_build, run_extract as cli_extract


def tree_hashes(path: Path) -> dict[str, str]:
    return {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*")) if p.is_file()
    }


def archived(archive: Path, doc_id: str = "SAMPLE:0001") -> dict:
    return json.loads((archive / f"{doc_id.replace(':', '_')}.json").read_text("utf-8"))


def add_recorded_claim(ws: Path) -> None:
    path = ws / "sample/recorded/responses.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    rows[2]["claims"].append({
        "subject": "study drug", "predicate": "affects", "object": "primary endpoint",
        "span": "did not improve the primary endpoint", "sign": None, "negated": True,
        "context": {"species": "human", "tissue": None, "population": "primary SjD", "assay": None, "evidence_model": "human"},
    })
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")


class CountingClient(RecordedClient):
    """Fails on a chosen document, as a dropped connection would."""

    model, model_version = "recorded", "test"

    def __init__(self, path, fail_on=None):
        super().__init__(path)
        self.calls: list[str] = []
        self.fail_on = fail_on

    def extract(self, document, prompt):
        if document["doc_id"] == self.fail_on:
            raise ConnectionError("dropped")
        self.calls.append(document["doc_id"])
        return super().extract(document, prompt)


def extract_with(ws: Path, client, out: str = "archive") -> Path:
    target = ws / out
    run_extract(
        load_documents(ws / "sample/corpus"),
        (ws / "sample/prompts/extract-v0.md").read_text("utf-8"),
        (ws / "sample/prompts/extraction-output.schema.json").read_text("utf-8"),
        client,
        target,
    )
    return target


def test_rebuilding_from_identical_inputs_gives_an_identical_release(workspace):
    archive = cli_extract(workspace)
    first = run_build(workspace, archive, "first")
    second = run_build(workspace, archive, "second")

    assert tree_hashes(first) == tree_hashes(second)


def test_each_raw_output_records_full_traceability(workspace):
    record = archived(cli_extract(workspace))
    prompt = (workspace / "sample/prompts/extract-v0.md").read_bytes()
    schema = (workspace / "sample/prompts/extraction-output.schema.json").read_bytes()

    assert record["model"] == "recorded"
    assert record["model_version"]
    assert record["prompt_hash"] == hashlib.sha256(prompt).hexdigest()
    assert record["schema_hash"] == hashlib.sha256(schema).hexdigest()
    assert len(record["document_hash"]) == 64


def test_interrupted_extraction_resumes_without_repeat_calls(workspace):
    responses = workspace / "sample/recorded/responses.jsonl"
    failing = CountingClient(responses, fail_on="SAMPLE:0002")
    with pytest.raises(ConnectionError):
        extract_with(workspace, failing)
    assert failing.calls == ["SAMPLE:0001"]

    resumed = CountingClient(responses)
    archive = extract_with(workspace, resumed)

    assert resumed.calls == ["SAMPLE:0002", "SAMPLE:0003"]
    assert len(list(archive.glob("*.json"))) == 3


def test_archive_from_another_prompt_is_not_silently_mixed(workspace):
    archive = cli_extract(workspace)
    (workspace / "sample/prompts/extract-v0.md").write_text("A changed prompt.", "utf-8")

    with pytest.raises(ValueError, match="different prompt"):
        extract_with(workspace, CountingClient(workspace / "sample/recorded/responses.jsonl"))
    assert archive.exists()


def test_claim_ids_do_not_change_when_unrelated_claims_are_added(workspace):
    before = run_build(workspace, cli_extract(workspace), "before")
    add_recorded_claim(workspace)
    after = run_build(workspace, cli_extract(workspace, "archive2"), "after")

    before_ids = {c["claim_id"] for c in sdkg.load(before).claims()}
    after_ids = {c["claim_id"] for c in sdkg.load(after).claims()}
    assert before_ids < after_ids


def test_build_refuses_an_archive_that_does_not_match_the_frozen_corpus(workspace):
    archive = cli_extract(workspace)
    documents = workspace / "sample/corpus/documents.jsonl"
    documents.write_text(documents.read_text("utf-8").replace("TNFSF13B expression", "TNFSF13B levels"), "utf-8")

    with pytest.raises(ValueError, match="SAMPLE:0001"):
        run_build(workspace, archive, "tampered")


def test_rebuild_needs_no_api_key(workspace, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    archive = cli_extract(workspace)

    code = main([
        "build", "--corpus", str(workspace / "sample/corpus"), "--archive", str(archive),
        "--licences", str(workspace / "sample/licences.json"),
        "--lexicon", str(workspace / "sample/lexicon.tsv"), "--out", str(workspace / "keyless"), "--version", "0.0.0-test",
    ])

    assert code == 0
    assert sdkg.load(workspace / "keyless").metadata["claims"] == 2
