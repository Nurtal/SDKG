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
        "subject_category": "gene_or_protein", "object_category": "disease",
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
                 "--prompt", str(REPO / "pipeline/prompts/extract-v3.md"), "--archive", str(ws / "archive")])


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


def write_topic(ws: Path, *terms: str) -> Path:
    path = ws / "topic.txt"
    path.write_text("# A comment\n" + "\n".join(terms) + "\n", "utf-8")
    return path


def set_text(ws: Path, texts: dict[str, str]) -> None:
    path = ws / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").split("\n") if l]
    for row in rows:
        if row["doc_id"] in texts:
            row["text"] = texts[row["doc_id"]]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def topic_batch(ws: Path, topic: Path, size=5, split=None) -> list[str]:
    args = ["next-batch", "--corpus", str(ws / "sample/corpus"), "--archive", str(ws / "archive"),
            "--size", str(size), "--seed", "5", "--out", str(ws / "t.jsonl"), "--topic", str(topic)]
    if split:
        args += ["--split", split]
    assert main(args) == 0
    return [json.loads(l)["doc_id"] for l in (ws / "t.jsonl").read_text("utf-8").split("\n") if l]


def test_a_topic_keeps_only_abstracts_that_match_its_terms(workspace):
    set_text(workspace, {"SAMPLE:0001": "Rituximab was studied.", "SAMPLE:0002": "Nothing relevant.", "SAMPLE:0003": "BAFF levels rose."})

    assert set(topic_batch(workspace, write_topic(workspace, "rituximab", "BAFF"))) == {"SAMPLE:0001", "SAMPLE:0003"}


@pytest.mark.parametrize("text,matches", [("IL-6 rose", True), ("IL-60 rose", False), ("JAK inhibitors", True), ("Jakarta cohort", False), ("(BAFF)", True)])
def test_topic_terms_match_whole_words_only(workspace, text, matches):
    set_text(workspace, {"SAMPLE:0001": text})

    assert ("SAMPLE:0001" in topic_batch(workspace, write_topic(workspace, "IL-6", "JAK", "BAFF"))) is matches


def test_a_topic_also_matches_the_title(workspace):
    path = workspace / "sample/corpus/documents.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").split("\n") if l]
    rows[0]["title"] = "A BAFF study"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")

    assert topic_batch(workspace, write_topic(workspace, "BAFF")) == ["SAMPLE:0001"]


def test_topic_terms_with_greek_letters_match_their_names(workspace):
    set_text(workspace, {"SAMPLE:0001": "TNF-α was raised."})

    assert topic_batch(workspace, write_topic(workspace, "TNF-alpha")) == ["SAMPLE:0001"]


def test_topic_order_is_reproducible_and_read_documents_leave_it(workspace):
    set_text(workspace, {k: "BAFF" for k in ("SAMPLE:0001", "SAMPLE:0002", "SAMPLE:0003")})
    topic = write_topic(workspace, "BAFF")
    first = topic_batch(workspace, topic)

    assert first == topic_batch(workspace, topic)
    import_session(workspace, [{"doc_id": first[0], "claims": []}])
    assert first[0] not in topic_batch(workspace, topic)


def test_the_published_topic_exists_and_the_prompt_freeze_matches():
    from sdkg.extraction import text_hash

    freeze = json.loads((REPO / "pipeline/prompt-freeze.json").read_text("utf-8"))

    assert freeze["prompt_hash"] == text_hash((REPO / freeze["prompt"]).read_text("utf-8"))
    assert "BAFF" in (REPO / "topics/therapeutic-targets-and-mechanisms.txt").read_text("utf-8")


def test_the_published_topic_avoids_ordinary_words():
    lines = (REPO / "topics/therapeutic-targets-and-mechanisms.txt").read_text("utf-8").split("\n")
    terms = {l.strip().casefold() for l in lines if l.strip() and not l.startswith("#")}

    assert not terms & {"april", "sting", "may", "march"}
