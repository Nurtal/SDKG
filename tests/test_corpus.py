"""Issue #17: a reproducible, frozen literature corpus (ADR-0010)."""
from __future__ import annotations

import json
from pathlib import Path

import sdkg
from sdkg.cli import main
from sdkg.extraction import read_jsonl

from conftest import REPO, make_claim

SOURCE = REPO / "sample/pubmed"


def freeze(ws: Path, out: str = "corpus", development: int = 1, seed: int = 11) -> Path:
    target = ws / out
    code = main([
        "corpus", "--query-file", str(REPO / "corpus/query.txt"), "--frozen-on", "2026-11-02",
        "--from-xml", str(SOURCE / "efetch.xml"), "--licences", str(SOURCE / "licences.tsv"),
        "--development", str(development), "--seed", str(seed), "--out", str(target),
    ])
    assert code == 0
    return target


def docs(corpus: Path) -> dict[str, dict]:
    return {d["doc_id"]: d for d in read_jsonl(corpus / "documents.jsonl")}


def test_query_date_and_counts_are_saved_with_the_corpus(workspace):
    info = json.loads((freeze(workspace) / "corpus.json").read_text("utf-8"))

    assert info["query"] == (REPO / "corpus/query.txt").read_text("utf-8").strip()
    assert info["frozen_on"] == "2026-11-02"
    assert info["source"] == "pubmed"
    assert info["counts"] == {
        "retrieved": 8, "primary": 3, "leads_only": 1, "case_reports": 1,
        "sjogren_larsson": 2, "other_disease": 0, "no_abstract": 1,
    }


def test_primary_documents_keep_their_metadata_and_a_predictable_text(workspace):
    document = docs(freeze(workspace))["9000001"]

    assert document["text"] == "Synthetic background about Sjögren's disease. Synthetic results."
    assert document["title"] == "Synthetic primary study"
    assert document["year"] == 2015
    assert document["publication_type"] == "primary"


def test_year_is_read_from_a_medline_date(workspace):
    assert docs(freeze(workspace))["9000002"]["year"] == 2019


def test_randomised_trials_are_recorded_as_such(workspace):
    corpus = docs(freeze(workspace))

    assert corpus["9000002"]["study_type"] == "randomised_trial"
    assert "study_type" not in corpus["9000001"]


def test_sjogren_larsson_records_are_excluded_by_title_or_mesh(workspace):
    corpus = freeze(workspace)
    excluded = {r["doc_id"]: r["reason"] for r in read_jsonl(corpus / "excluded.jsonl")}

    assert excluded["9000005"] == "sjogren_larsson"
    assert excluded["9000008"] == "sjogren_larsson"
    assert not {"9000005", "9000008"} & set(docs(corpus))


def test_reviews_are_for_leads_only_and_cannot_become_evidence(workspace):
    corpus = freeze(workspace)

    assert "9000003" not in docs(corpus)
    assert [d["doc_id"] for d in read_jsonl(corpus / "leads.jsonl")] == ["9000003"]


def test_case_reports_and_records_without_abstracts_are_excluded(workspace):
    corpus = freeze(workspace)
    excluded = {r["doc_id"]: r["reason"] for r in read_jsonl(corpus / "excluded.jsonl")}

    assert excluded["9000004"] == "case_report"
    assert excluded["9000006"] == "no_abstract"


def test_licence_status_is_recorded_and_unknown_when_not_listed(workspace):
    corpus = docs(freeze(workspace))

    assert corpus["9000001"]["licence"] == "CC-BY-4.0"
    assert corpus["9000007"]["licence"] == "CC-BY-NC-4.0"
    assert corpus["9000002"]["licence"] == "unknown"


def test_a_development_set_is_held_apart_reproducibly(workspace):
    first, second = docs(freeze(workspace, "one")), docs(freeze(workspace, "two"))

    assert [k for k, d in first.items() if d["split"] == "development"] == [k for k, d in second.items() if d["split"] == "development"]
    assert sum(d["split"] == "development" for d in first.values()) == 1
    assert sum(d["split"] == "evaluation" for d in first.values()) == 2


def test_freezing_twice_gives_identical_files(workspace):
    one, two = freeze(workspace, "one"), freeze(workspace, "two")

    for name in ("documents.jsonl", "corpus.json", "excluded.jsonl", "leads.jsonl"):
        assert (one / name).read_bytes() == (two / name).read_bytes()


# Relevance screening


def write_screening(ws: Path, decisions: dict[str, bool]) -> Path:
    path = ws / "screening.jsonl"
    path.write_text("".join(json.dumps({"doc_id": k, "relevant": v, "reason": "synthetic"}) + "\n" for k, v in decisions.items()), "utf-8")
    return path


def screen(ws: Path, corpus: Path, recorded: Path, out: str = "screened") -> Path:
    prompt = ws / "screen-prompt.md"
    prompt.write_text("Synthetic screening prompt.", "utf-8")
    target = ws / out
    code = main([
        "screen", "--corpus", str(corpus), "--prompt", str(prompt), "--recorded", str(recorded),
        "--archive", str(ws / (out + "-archive")), "--out", str(target),
    ])
    assert code == 0
    return target


def test_screening_keeps_relevant_documents_and_records_the_others(workspace):
    corpus = freeze(workspace)
    screened = screen(workspace, corpus, write_screening(workspace, {"9000001": True, "9000002": False, "9000007": True}))

    assert set(docs(screened)) == {"9000001", "9000007"}
    assert [r["doc_id"] for r in read_jsonl(screened / "screened_out.jsonl")] == ["9000002"]
    assert json.loads((screened / "corpus.json").read_text("utf-8"))["counts"]["screened_out"] == 1


def test_screening_error_sample_is_reproducible_and_covers_both_decisions(workspace):
    corpus = freeze(workspace)
    screened = screen(workspace, corpus, write_screening(workspace, {"9000001": True, "9000002": False, "9000007": True}))

    def draw(name, seed=3):
        out = workspace / name
        assert main(["screen-sample", "--screened", str(screened), "--seed", str(seed), "--size", "2", "--out", str(out)]) == 0
        return out.read_text("utf-8")

    assert draw("s1.jsonl") == draw("s2.jsonl")
    rows = [json.loads(l) for l in draw("s3.jsonl").splitlines()]
    assert {r["screening_decision"] for r in rows} == {True, False}


def test_paid_screening_does_not_silently_drop_documents_without_a_decision(workspace):
    from sdkg.corpus import apply_screening

    corpus = freeze(workspace)
    archive = workspace / "partial"
    archive.mkdir()
    (archive / "9000001.json").write_text(json.dumps({"doc_id": "9000001", "response": {"relevant": True}}), "utf-8")

    try:
        apply_screening(corpus, archive, workspace / "out")
    except ValueError as error:
        assert "2 documents have no screening decision" in str(error)
    else:
        raise AssertionError("Expected screening to stop")


# The release and the test sample know about the development set


def test_test_sample_excludes_the_development_set(workspace):
    from sdkg.extraction import text_hash

    corpus = freeze(workspace, development=1)
    documents = docs(corpus)
    development = next(k for k, d in documents.items() if d["split"] == "development")
    evaluation = [k for k, d in documents.items() if d["split"] == "evaluation"]
    recorded = workspace / "rec.jsonl"
    span = "Synthetic"
    rows = [{"doc_id": k, "claims": [make_claim(span=span, tissue=k)]} for k in documents]
    recorded.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    prompt = workspace / "sample/prompts/extract-v0.md"
    schema = workspace / "sample/prompts/extraction-output.schema.json"
    manifest = workspace / "sample/licences.json"
    data = json.loads(manifest.read_text("utf-8"))
    data["sources"]["pubmed"] = {"status": "allowed"}
    manifest.write_text(json.dumps(data), "utf-8")
    assert main(["extract", "--corpus", str(corpus), "--prompt", str(prompt), "--schema", str(schema), "--recorded", str(recorded), "--out", str(workspace / "a")]) == 0
    release = workspace / "r"
    assert main(["build", "--corpus", str(corpus), "--archive", str(workspace / "a"), "--licences", str(manifest), "--lexicon", str(workspace / "sample/lexicon.tsv"), "--out", str(release), "--version", "t"]) == 0
    freeze_file = workspace / "freeze.json"
    freeze_file.write_text(json.dumps({"prompt_hash": text_hash(prompt.read_text("utf-8"))}), "utf-8")
    out = workspace / "sampled"
    assert main(["sample", "--release", str(release), "--corpus", str(corpus), "--freeze", str(freeze_file), "--seed", "1", "--size", "2", "--double", "1", "--out", str(out)]) == 0

    sampled = {json.loads(l)["source_id"] for l in (out / "review_a.jsonl").read_text("utf-8").splitlines()}
    assert development not in sampled
    assert sampled == set(evaluation)
    assert sdkg.load(release).metadata["development_documents"] == 1
