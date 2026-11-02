"""ADR-0013: extraction in a Claude Code session, with no paid API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sdkg
from sdkg.cli import main

from conftest import REPO


def valid_claim(span="Synthetic test abstract", subject="IRF5") -> dict:
    return {
        "subject": subject, "predicate": "associated_with", "object": "Sjögren's disease", "span": span,
        "sign": None, "negated": False, "directed": None, "direct": None, "biomarker_role": None,
        "sjd_context": True, "trial_id": None,
        "context": {"species": "human", "tissue": None, "population": None, "assay": None, "evidence_model": "human"},
    }


def next_batch(ws: Path, size=2, split=None, seed=5, out="batch.jsonl") -> list[dict]:
    args = ["next-batch", "--corpus", str(ws / "sample/corpus"), "--archive", str(ws / "archive"),
            "--size", str(size), "--seed", str(seed), "--out", str(ws / out)]
    if split:
        args += ["--split", split]
    assert main(args) == 0
    return [json.loads(l) for l in (ws / out).read_text("utf-8").splitlines()]


def import_session(ws: Path, rows: list[dict]) -> int:
    path = ws / "responses.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return main(["import-session", "--corpus", str(ws / "sample/corpus"), "--responses", str(path),
                 "--prompt", str(REPO / "pipeline/prompts/extract-v2.md"), "--archive", str(ws / "archive")])


def build(ws: Path) -> sdkg.Release:
    assert main(["build", "--corpus", str(ws / "sample/corpus"), "--archive", str(ws / "archive"),
                 "--licences", str(ws / "sample/licences.json"), "--lexicon", str(ws / "sample/lexicon.tsv"),
                 "--out", str(ws / "release"), "--version", "t"]) == 0
    return sdkg.load(ws / "release")


def test_next_batch_is_reproducible_and_contains_what_is_needed_to_read(workspace):
    first, second = next_batch(workspace, out="a.jsonl"), next_batch(workspace, out="b.jsonl")

    assert first == second and len(first) == 2
    assert {"doc_id", "title", "text"} <= set(first[0])


def test_imported_documents_leave_the_queue(workspace):
    first = next_batch(workspace, size=1)
    import_session(workspace, [{"doc_id": first[0]["doc_id"], "claims": []}])

    remaining = next_batch(workspace, size=5)

    assert first[0]["doc_id"] not in {d["doc_id"] for d in remaining}
    assert len(remaining) == 2


def test_import_records_that_the_work_was_done_in_a_session(workspace):
    import_session(workspace, [{"doc_id": "SAMPLE:0001", "claims": [valid_claim()]}])
    record = json.loads((workspace / "archive/SAMPLE_0001.json").read_text("utf-8"))

    assert record["model"] == "claude-opus-5-5"
    assert record["model_version"] == "claude-code-session"
    assert len(record["prompt_hash"]) == 64


def test_imported_claims_reach_a_release(workspace):
    import_session(workspace, [{"doc_id": "SAMPLE:0001", "claims": [valid_claim()]}])

    assert build(workspace).claims()[0]["subject_label"] == "IRF5"


def test_response_that_breaks_the_output_schema_is_refused_with_nothing_written(workspace):
    bad = {**valid_claim(), "predicate": "invented"}

    with pytest.raises(ValueError, match="SAMPLE:0002"):
        import_session(workspace, [{"doc_id": "SAMPLE:0001", "claims": [valid_claim()]}, {"doc_id": "SAMPLE:0002", "claims": [bad]}])
    assert not list((workspace / "archive").glob("*.json")) if (workspace / "archive").exists() else True


def test_unknown_document_is_refused(workspace):
    with pytest.raises(ValueError, match="NOPE"):
        import_session(workspace, [{"doc_id": "NOPE", "claims": []}])


def test_import_needs_no_api_key_or_network(workspace, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert import_session(workspace, [{"doc_id": "SAMPLE:0003", "claims": []}]) == 0


def test_development_documents_come_first_when_asked(workspace):
    path = workspace / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    rows[1]["split"] = "development"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")

    assert [d["doc_id"] for d in next_batch(workspace, size=5, split="development")] == [rows[1]["doc_id"]]


@pytest.mark.parametrize("command", ["extract", "screen"])
def test_no_command_can_call_a_paid_api(command, capsys):
    with pytest.raises(SystemExit):
        main([command, "--help"])

    assert "max-spend" not in capsys.readouterr().out


@pytest.mark.parametrize("char", [" ", " ", "\x85", "\x0b", "\x0c"])
def test_unicode_line_separators_in_an_abstract_do_not_break_the_corpus(workspace, char):
    from sdkg.extraction import load_documents

    path = workspace / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").split("\n") if l]
    rows[0]["text"] = f"First part.{char}Second part."
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8", newline="\n")

    assert load_documents(workspace / "sample/corpus")[0]["text"] == f"First part.{char}Second part."
