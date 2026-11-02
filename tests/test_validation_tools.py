"""Issue #12: sample and evaluate commands for the validation protocol (ADR-0004)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdkg.cli import main
from sdkg.extraction import text_hash

from conftest import build_with, make_claim

DOC = "SAMPLE:0001"


def freeze_prompt(ws: Path, prompt_hash: str | None = None) -> Path:
    prompt = (ws / "sample/prompts/extract-v0.md").read_text("utf-8")
    path = ws / "freeze.json"
    path.write_text(json.dumps({"prompt_hash": prompt_hash or text_hash(prompt), "frozen_on": "2026-11-02"}), "utf-8")
    return path


def large_release(ws: Path) -> Path:
    claims = [make_claim(tissue=f"tissue {i}", predicate="associated_with") for i in range(60)]
    claims += [make_claim(tissue=f"tissue {i}", predicate="regulates") for i in range(30)]
    claims += [make_claim(tissue=f"tissue {i}", predicate="treats") for i in range(10)]
    return build_with(ws, {DOC: claims})


def sample(ws: Path, release: Path, out: str = "sample_out", seed: int = 7, size: int = 20, double: int = 6, freeze: Path | None = None) -> Path:
    target = ws / out
    code = main([
        "sample", "--release", str(release), "--corpus", str(ws / "sample/corpus"),
        "--freeze", str(freeze or freeze_prompt(ws)), "--seed", str(seed), "--size", str(size),
        "--double", str(double), "--out", str(target),
    ])
    assert code == 0
    return target


def lines(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines()]


def test_same_release_and_seed_give_the_same_sample(workspace):
    release = large_release(workspace)
    first, second = sample(workspace, release, "one"), sample(workspace, release, "two")

    for name in ("key.jsonl", "review_a.jsonl", "review_b.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_a_different_seed_gives_a_different_sample(workspace):
    release = large_release(workspace)
    one, two = sample(workspace, release, "one", seed=1), sample(workspace, release, "two", seed=2)

    assert {r["claim_id"] for r in lines(one / "key.jsonl")} != {r["claim_id"] for r in lines(two / "key.jsonl")}


def test_sample_is_stratified_in_proportion_to_each_predicate(workspace):
    out = sample(workspace, large_release(workspace))
    counts: dict[str, int] = {}
    for row in lines(out / "key.jsonl"):
        counts[row["predicate"]] = counts.get(row["predicate"], 0) + 1

    assert counts == {"associated_with": 12, "regulates": 6, "treats": 2}


def test_small_predicates_are_still_represented(workspace):
    claims = [make_claim(tissue=f"t{i}") for i in range(99)] + [make_claim(predicate="treats")]
    release = build_with(workspace, {DOC: claims})
    rows = lines(sample(workspace, release, size=10, double=2) / "key.jsonl")

    assert len(rows) == 10
    assert "treats" in {r["predicate"] for r in rows}


def test_review_material_shows_what_a_reviewer_needs_and_hides_model_scores(workspace):
    out = sample(workspace, large_release(workspace))
    item = lines(out / "review_a.jsonl")[0]

    assert item["evidence_span"] == "Synthetic test abstract"
    assert item["subject"] == {"id": "HGNC:6120", "label": "IRF5"}
    assert item["object"]["id"] == "MONDO:0010030"
    assert item["context"]["tissue"].startswith("tissue")
    assert not {"extraction_reliability", "claim_status", "evidence_level", "claim_id"} & set(item)
    assert "biological truth" in (out / "instructions.md").read_text("utf-8")


def test_double_reviewed_subset_goes_independently_to_two_reviewers(workspace):
    out = sample(workspace, large_release(workspace))
    a, b = lines(out / "review_a.jsonl"), lines(out / "review_b.jsonl")

    assert len(a) == 20 and len(b) == 6
    assert {i["item_id"] for i in b} < {i["item_id"] for i in a}
    assert [i["item_id"] for i in b] != [i["item_id"] for i in a if i["item_id"] in {j["item_id"] for j in b}]


def test_sampling_refuses_to_run_until_the_prompt_is_frozen(workspace):
    release = large_release(workspace)
    missing = workspace / "not-frozen.json"

    with pytest.raises(ValueError, match="frozen"):
        sample(workspace, release, freeze=missing)
    with pytest.raises(ValueError, match="frozen"):
        sample(workspace, release, freeze=freeze_prompt(workspace, "another-prompt"))


# Evaluation


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    return path


def judgement(item: str, ok: bool = True, mapping_ok: bool = True) -> dict:
    return {"item_id": item, "supported": ok, "subject_mapping_correct": mapping_ok, "object_mapping_correct": True}


def evaluate(ws: Path, key: list[dict], a: list[dict], b: list[dict] | None = None, threshold: float | None = None, annotations: list[dict] | None = None, predictions: list[dict] | None = None) -> dict:
    args = [
        "evaluate", "--key", str(write_jsonl(ws / "k.jsonl", key)),
        "--judgements-a", str(write_jsonl(ws / "a.jsonl", a)), "--out", str(ws / "report.json"),
    ]
    if b is not None:
        args += ["--judgements-b", str(write_jsonl(ws / "b.jsonl", b))]
    if threshold is not None:
        args += ["--threshold", str(threshold)]
    if annotations is not None:
        args += ["--annotations", str(write_jsonl(ws / "ann.jsonl", annotations))]
        args += ["--predictions", str(write_jsonl(ws / "pred.jsonl", predictions or []))]
    assert main(args) == 0
    return json.loads((ws / "report.json").read_text("utf-8"))


def key_rows(n: int, predicate: str = "treats", start: int = 0, weight: float = 1.0) -> list[dict]:
    return [{"item_id": f"I{predicate}{i}", "claim_id": f"C{predicate}{i}", "predicate": predicate, "stratum_weight": weight} for i in range(start, start + n)]


def test_precision_with_wilson_interval_matches_a_hand_calculation(workspace):
    key = key_rows(10)
    a = [judgement(r["item_id"], ok=i < 8) for i, r in enumerate(key)]

    result = evaluate(workspace, key, a)["predicates"]["treats"]

    assert result["precision"] == pytest.approx(0.8)
    assert result["ci_low"] == pytest.approx(0.4902, abs=1e-3)
    assert result["ci_high"] == pytest.approx(0.9433, abs=1e-3)


def test_incorrect_mapping_counts_against_precision(workspace):
    key = key_rows(2)
    a = [judgement(key[0]["item_id"]), judgement(key[1]["item_id"], mapping_ok=False)]

    assert evaluate(workspace, key, a)["predicates"]["treats"]["precision"] == 0.5


def test_overall_precision_uses_stratum_weights(workspace):
    key = key_rows(10, "treats", weight=0.1) + key_rows(10, "regulates", weight=0.9)
    a = [judgement(r["item_id"], ok=r["predicate"] == "regulates") for r in key]

    assert evaluate(workspace, key, a)["overall"]["precision"] == pytest.approx(0.9)


def test_cohens_kappa_matches_a_worked_example(workspace):
    # 20 yes-yes, 5 yes-no, 10 no-yes, 15 no-no. Observed 0.7, chance 0.5, kappa 0.4.
    key = key_rows(50)
    pattern = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
    a = [judgement(r["item_id"], ok=p[0]) for r, p in zip(key, pattern)]
    b = [judgement(r["item_id"], ok=p[1]) for r, p in zip(key, pattern)]

    agreement = evaluate(workspace, key, a, b)["agreement"]

    assert agreement["kappa"] == pytest.approx(0.4)
    assert agreement["items"] == 50


def test_recall_compares_blind_annotations_with_model_claims(workspace):
    annotations = [
        {"doc_id": "D1", "subject": "A", "predicate": "treats", "object": "B"},
        {"doc_id": "D1", "subject": "C", "predicate": "treats", "object": "D"},
        {"doc_id": "D2", "subject": "E", "predicate": "regulates", "object": "F"},
        {"doc_id": "D2", "subject": "G", "predicate": "regulates", "object": "H"},
    ]
    predictions = [
        {"doc_id": "D1", "subject": "A", "predicate": "treats", "object": "B"},
        {"doc_id": "D1", "subject": "C", "predicate": "treats", "object": "D"},
        {"doc_id": "D2", "subject": "E", "predicate": "regulates", "object": "F"},
        {"doc_id": "D2", "subject": "X", "predicate": "regulates", "object": "Y"},
    ]
    key = key_rows(1)

    report = evaluate(workspace, key, [judgement(key[0]["item_id"])], annotations=annotations, predictions=predictions)

    assert report["recall"]["recall"] == 0.75


def test_predicates_below_threshold_are_marked(workspace):
    key = key_rows(10, "treats") + key_rows(10, "regulates")
    a = [judgement(r["item_id"], ok=(r["predicate"] == "regulates" or r["item_id"][-1] in "0123")) for r in key]

    report = evaluate(workspace, key, a)
    assert report["threshold"] == 0.7
    assert report["predicates"]["treats"]["status"] == "remove_or_experimental"
    assert report["predicates"]["regulates"]["status"] == "keep"


def test_threshold_is_configurable_before_the_final_test(workspace):
    key = key_rows(10)
    a = [judgement(r["item_id"], ok=i < 8) for i, r in enumerate(key)]

    assert evaluate(workspace, key, a, threshold=0.9)["predicates"]["treats"]["status"] == "remove_or_experimental"
    assert evaluate(workspace, key, a, threshold=0.75)["predicates"]["treats"]["status"] == "keep"
