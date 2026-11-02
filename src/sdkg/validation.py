"""Draw the blinded test sample and compute results from human judgements (ADR-0004)."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from sdkg.extraction import load_documents
from sdkg.package import load

Z_95 = 1.959964

INSTRUCTIONS = """# Review instructions

For each item, read the evidence span and answer three questions:

1. `supported`: does this passage support the claim as stated?
2. `subject_mapping_correct`: is the subject identifier the concept the passage refers to?
3. `object_mapping_correct`: is the object identifier the concept the passage refers to?

Judge only whether the passage supports the claim and whether the entities are mapped correctly.
Do not judge biological truth. A claim can be supported by a passage and still be wrong about biology.

Work independently and do not discuss items with the other reviewer until all judgements are recorded.

Record one JSON line per item with `item_id`, `supported`, `subject_mapping_correct` and `object_mapping_correct`.
"""


def _rank(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _allocate(strata: dict[str, int], size: int) -> dict[str, int]:
    """Largest-remainder allocation, giving every stratum at least one item when possible."""
    total = sum(strata.values())
    if size > total:
        raise ValueError(f"Sample size {size} is larger than the {total} claims available")
    allocation = {k: min(1, n) for k, n in strata.items()}
    if sum(allocation.values()) > size:
        raise ValueError("Sample size is smaller than the number of predicates")
    quotas = {k: n * size / total for k, n in strata.items()}
    for key in strata:
        allocation[key] = max(allocation[key], math.floor(quotas[key]))
    remaining = size - sum(allocation.values())
    order = sorted(strata, key=lambda k: (allocation[k] - quotas[k], k))
    while remaining > 0:
        for key in order:
            if remaining and allocation[key] < strata[key]:
                allocation[key] += 1
                remaining -= 1
    while remaining < 0:
        for key in reversed(order):
            if remaining and allocation[key] > 1:
                allocation[key] -= 1
                remaining += 1
    return allocation


def _check_frozen(freeze: Path, prompt_hashes: list[str]) -> None:
    if not freeze.exists():
        raise ValueError("The prompt has not been frozen: no freeze record was found")
    frozen = json.loads(freeze.read_text("utf-8"))["prompt_hash"]
    if prompt_hashes != [frozen]:
        raise ValueError("This release was not extracted with the frozen prompt")


def run_sample(release: str | Path, corpus: str | Path, freeze: str | Path, seed: int, size: int, double: int, out: str | Path) -> None:
    loaded = load(release)
    _check_frozen(Path(freeze), loaded.metadata["extraction"]["prompt_hash"])
    if double > size:
        raise ValueError("The double-reviewed subset cannot be larger than the sample")
    documents = load_documents(corpus)
    texts = {d["doc_id"]: d["text"] for d in documents}
    development = {d["doc_id"] for d in documents if d.get("split") == "development"}
    # Only AI-extracted claims are under test, and never from documents used to tune the prompt.
    claims = [c for c in loaded.claims() if c["claim_status"] == "ai_extracted" and c["pmid"] not in development]
    if not claims:
        raise ValueError("No claims are available for the test sample outside the development set")

    by_predicate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        by_predicate[claim["predicate"]].append(claim)
    allocation = _allocate({k: len(v) for k, v in by_predicate.items()}, size)

    chosen: list[dict[str, Any]] = []
    for predicate in sorted(by_predicate):
        ranked = sorted(by_predicate[predicate], key=lambda c: _rank(seed, c["claim_id"]))
        for claim in ranked[: allocation[predicate]]:
            chosen.append({**claim, "_weight": len(by_predicate[predicate]) / len(claims)})

    items, key = [], []
    for claim in sorted(chosen, key=lambda c: _rank(seed, "item" + c["claim_id"])):
        item_id = f"R{len(items) + 1:04d}"
        items.append({
            "item_id": item_id,
            "subject": {"id": claim["subject"], "label": claim["subject_label"]},
            "predicate": claim["predicate"],
            "object": {"id": claim["object"], "label": claim["object_label"]},
            "sign": claim["sign"],
            "negated": claim["negated"],
            "context": {k: claim[k] for k in ("species", "tissue", "population", "assay", "evidence_model")},
            "source_id": claim["pmid"],
            "evidence_span": texts[claim["pmid"]][claim["span_start"] : claim["span_end"]],
        })
        key.append({"item_id": item_id, "claim_id": claim["claim_id"], "predicate": claim["predicate"], "stratum_weight": claim["_weight"]})

    second = sorted(sorted(items, key=lambda i: _rank(seed, "double" + i["item_id"]))[:double],
                    key=lambda i: _rank(seed, "order-b" + i["item_id"]))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("review_a.jsonl", items), ("review_b.jsonl", second), ("key.jsonl", key)):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")
    (out / "instructions.md").write_text(INSTRUCTIONS, "utf-8")
    (out / "sample.json").write_text(json.dumps({"seed": seed, "size": size, "double": double, "population": len(claims)}, sort_keys=True) + "\n", "utf-8")


def wilson(successes: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = Z_95**2
    denominator = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denominator
    margin = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _correct(judgement: dict[str, Any]) -> bool:
    return bool(judgement["supported"] and judgement["subject_mapping_correct"] and judgement["object_mapping_correct"])


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    p_a, p_b = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    chance = p_a * p_b + (1 - p_a) * (1 - p_b)
    return 1.0 if chance == 1 else (observed - chance) / (1 - chance)


def _read(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in Path(path).read_text("utf-8").splitlines() if l.strip()]


def evaluate(
    key: list[dict[str, Any]],
    judgements_a: list[dict[str, Any]],
    judgements_b: list[dict[str, Any]] | None = None,
    threshold: float = 0.7,
    annotations: list[dict[str, Any]] | None = None,
    predictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    a = {j["item_id"]: _correct(j) for j in judgements_a}
    missing = sorted(set(k["item_id"] for k in key) - set(a))
    if missing:
        raise ValueError(f"{len(missing)} sampled items have no judgement, for example {missing[0]}")

    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in key:
        strata[row["predicate"]].append(row)

    predicates, overall, variance = {}, 0.0, 0.0
    for predicate, rows in sorted(strata.items()):
        n = len(rows)
        correct = sum(a[r["item_id"]] for r in rows)
        low, high = wilson(correct, n)
        precision = correct / n
        predicates[predicate] = {
            "n": n, "correct": correct, "precision": precision, "ci_low": low, "ci_high": high,
            "status": "keep" if precision >= threshold else "remove_or_experimental",
        }
        weight = rows[0]["stratum_weight"]
        overall += weight * precision
        variance += weight**2 * precision * (1 - precision) / n

    report: dict[str, Any] = {
        "threshold": threshold,
        "overall": {
            "n": len(key), "precision": overall,
            "ci_low": max(0.0, overall - Z_95 * math.sqrt(variance)),
            "ci_high": min(1.0, overall + Z_95 * math.sqrt(variance)),
        },
        "predicates": predicates,
    }
    if judgements_b is not None:
        pairs = [(a[j["item_id"]], _correct(j)) for j in judgements_b]
        report["agreement"] = {
            "items": len(pairs), "kappa": cohens_kappa(pairs),
            "observed": sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
        }
    if annotations is not None:
        triple = lambda r: (r["doc_id"], r["subject"], r["predicate"], r["object"])
        gold, found = {triple(r) for r in annotations}, {triple(r) for r in predictions or []}
        matched = len(gold & found)
        low, high = wilson(matched, len(gold))
        report["recall"] = {"annotated": len(gold), "matched": matched, "recall": matched / len(gold) if gold else None, "ci_low": low, "ci_high": high}
    return report


def run_evaluate(key, judgements_a, out, judgements_b=None, threshold=0.7, annotations=None, predictions=None) -> None:
    report = evaluate(
        _read(key), _read(judgements_a), _read(judgements_b) if judgements_b else None, threshold,
        _read(annotations) if annotations else None, _read(predictions) if predictions else None,
    )
    Path(out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
