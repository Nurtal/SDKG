"""The graph's utility evaluations, defined before results are seen."""
from __future__ import annotations

import heapq
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from sdkg.extraction import load_documents
from sdkg.package import load

INTERPRETATION = (
    "This measures recall of relationships published after the cutoff. It is recall of future knowledge, "
    "not discovery: the graph and its future test edges come from the same literature."
)


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _top_degree_pairs(adjacency: dict[str, set[str]], k: int) -> list[tuple[str, str]]:
    """The k unconnected pairs with the highest degree product, without scoring every pair."""
    nodes = sorted(adjacency, key=lambda n: (-len(adjacency[n]), n))
    heap = [(-len(adjacency[nodes[i]]) * len(adjacency[nodes[i + 1]]), i, i + 1) for i in range(len(nodes) - 1)]
    heapq.heapify(heap)
    found: list[tuple[str, str]] = []
    while heap and len(found) < k:
        _, i, j = heapq.heappop(heap)
        if nodes[j] not in adjacency[nodes[i]]:
            found.append(_pair(nodes[i], nodes[j]))
        if j + 1 < len(nodes):
            heapq.heappush(heap, (-len(adjacency[nodes[i]]) * len(adjacency[nodes[j + 1]]), i, j + 1))
    return found


def _top_common_neighbour_pairs(adjacency: dict[str, set[str]], k: int) -> list[tuple[str, str]]:
    scores: dict[tuple[str, str], int] = defaultdict(int)
    for neighbours in adjacency.values():
        for a, b in combinations(sorted(neighbours), 2):
            if b not in adjacency[a]:
                scores[(a, b)] += 1
    return sorted(scores, key=lambda pair: (-scores[pair], pair))[:k]


def temporal_test(
    release: str | Path,
    corpus: str | Path,
    cutoff_year: int,
    k: int,
    include_null_results: bool = False,
) -> dict[str, Any]:
    """Build a graph from publications before the cutoff, then rank pairs that appear later."""
    years = {d["doc_id"]: d.get("year") for d in load_documents(corpus)}
    claims = [c for c in load(release).claims(layer="disease_core") if c["pmid"] in years and years[c["pmid"]] is not None]

    before = [c for c in claims if years[c["pmid"]] < cutoff_year and not c["negated"]]
    train = {_pair(c["subject"], c["object"]) for c in before}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for a, b in train:
        adjacency[a].add(b)
        adjacency[b].add(a)

    after = [c for c in claims if years[c["pmid"]] >= cutoff_year and (include_null_results or not c["negated"])]
    future = {_pair(c["subject"], c["object"]) for c in after} - train
    reachable = {pair for pair in future if pair[0] in adjacency and pair[1] in adjacency}
    null_pairs = {_pair(c["subject"], c["object"]) for c in after if c["negated"]} - train

    methods = {}
    for name, ranked in (
        ("common_neighbours", _top_common_neighbour_pairs(adjacency, k)),
        ("node_degree_baseline", _top_degree_pairs(adjacency, k)),
    ):
        hits = len(set(ranked) & reachable)
        methods[name] = {"k": k, "hits": hits, "recall_at_k": hits / len(reachable) if reachable else None}

    entities = len(adjacency)
    return {
        "cutoff_year": cutoff_year,
        "train_edges": len(train),
        "train_entities": entities,
        "candidates": entities * (entities - 1) // 2 - len(train),
        "future_edges_total": len(future),
        "future_edges_reachable": len(reachable),
        "future_null_results": len(null_pairs & future),
        "methods": methods,
        "interpretation": INTERPRETATION,
    }


def open_targets_comparison(release: str | Path) -> dict[str, Any]:
    """Compare literature-derived disease core targets with the held-out associations (ADR-0011)."""
    loaded = load(release)
    held_out = loaded.held_out_associations()
    if not held_out:
        raise ValueError("This release has no held-out associations to compare with")
    diseases = {row["disease"] for row in held_out}
    held = {row["target"] for row in held_out}

    categories = {
        row["entity_id"]: row["category"]
        for row in loaded._rows(f"SELECT entity_id, category FROM read_parquet('{loaded._parquet('entities')}')")
    }
    literature: set[str] = set()
    for claim in loaded.claims(layer="disease_core"):
        if claim["negated"] or claim["claim_status"] == "curated_source":
            continue
        for entity, other in ((claim["subject"], claim["object"]), (claim["object"], claim["subject"])):
            if other in diseases and categories.get(entity) == "gene_or_protein":
                literature.add(entity)
    return {
        "held_out_targets": len(held),
        "literature_targets": len(literature),
        "overlap": sorted(literature & held),
        "additions": sorted(literature - held),
        "gaps": sorted(held - literature),
        "note": "Additions are not validated findings, and gaps are not errors. Both need expert reading.",
    }


def score_competency_questions(references: list[dict[str, Any]], judgements: list[dict[str, Any]]) -> dict[str, Any]:
    """Score the expert's judgements, made against reference answers recorded in advance."""
    by_id = {j["id"]: j for j in judgements}
    missing = sorted(r["id"] for r in references if r["id"] not in by_id)
    if missing:
        raise ValueError(f"Competency questions have no judgement: {', '.join(missing)}")
    checkable = [by_id[r["id"]] for r in references if r["type"] == "checkable"]
    exploratory = [by_id[r["id"]] for r in references if r["type"] == "exploratory"]
    correct = sum(bool(j["correct"]) for j in checkable)
    useful = sum(bool(j["useful"] and j["traceable"]) for j in exploratory)
    return {
        "checkable": {"total": len(checkable), "correct": correct, "rate": correct / len(checkable) if checkable else None},
        "exploratory": {"total": len(exploratory), "useful_and_traceable": useful, "rate": useful / len(exploratory) if exploratory else None},
    }
