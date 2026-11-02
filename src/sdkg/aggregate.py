"""Group claims and find contradictions, keeping every underlying claim (ADR-0001, ADR-0005)."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

GROUP_KEY = ("subject", "predicate", "object", "species", "tissue", "population", "assay", "evidence_model", "negated")
COMPATIBLE_EXACT = ("evidence_model",)
COMPATIBLE_UNLESS_UNSTATED = ("species", "tissue", "population", "assay")


def group_claims(claims: list[dict[str, Any]], pmid_of: dict[str, str]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        groups[tuple(claim[k] for k in GROUP_KEY)].append(claim)
    result = []
    for key, members in groups.items():
        signs = [m["sign"] for m in members]
        result.append({
            **dict(zip(GROUP_KEY, key)),
            "support": len({pmid_of[m["claim_id"]] for m in members}),
            "positive_claims": signs.count("positive"),
            "negative_claims": signs.count("negative"),
            "claim_ids": sorted(m["claim_id"] for m in members),
        })
    return sorted(result, key=lambda g: g["claim_ids"][0])


def compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if any(a[k] != b[k] for k in COMPATIBLE_EXACT):
        return False
    return all(a[k] is None or b[k] is None or a[k] == b[k] for k in COMPATIBLE_UNLESS_UNSTATED)


def find_contradictions(claims: list[dict[str, Any]]) -> list[tuple[str, str]]:
    by_relationship: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        if claim["sign"] in ("positive", "negative") and not claim["negated"]:
            by_relationship[(claim["subject"], claim["predicate"], claim["object"])].append(claim)
    pairs = []
    for members in by_relationship.values():
        for a, b in combinations(sorted(members, key=lambda c: c["claim_id"]), 2):
            if a["sign"] != b["sign"] and compatible(a, b):
                pairs.append((a["claim_id"], b["claim_id"]))
    return sorted(pairs)


def evidence_level(document: dict[str, Any], evidence_model: str | None) -> str:
    """PROPOSAL for expert review. Model evidence never takes a human study's grade."""
    if evidence_model in ("animal", "in_vitro"):
        return "animal_or_in_vitro"
    if evidence_model is None:
        return "unspecified"
    return document.get("study_type") or "human_observational"
