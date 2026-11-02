"""Read a release, as a user would."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import duckdb


class Release:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.metadata: dict[str, Any] = json.loads((self.path / "release.json").read_text("utf-8"))
        self._db = duckdb.connect()

    def _parquet(self, table: str) -> str:
        return str(self.path / f"{table}.parquet").replace("'", "''")

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        result = self._db.execute(sql, params or [])
        names = [d[0] for d in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]

    @staticmethod
    def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
        conditions, params = [], []
        for column, value in filters.items():
            if not column.isidentifier():
                raise ValueError(f"Invalid filter: {column}")
            conditions.append(f'"{column}" = ?')
            params.append(value)
        return (f"WHERE {' AND '.join(conditions)}" if conditions else "", params)

    def claims(self, **filters: Any) -> list[dict[str, Any]]:
        """Return claims joined to their evidence, filtered by exact column values."""
        clause, params = self._where(filters)
        return self._rows(
            f"""SELECT * FROM (
                  SELECT c.*, s.label AS subject_label, o.label AS object_label,
                         e.pmid, e.span_start, e.span_end, e.span_hash, e.span_text
                  FROM read_parquet('{self._parquet("claims")}') c
                  LEFT JOIN read_parquet('{self._parquet("evidence")}') e USING (claim_id)
                  JOIN read_parquet('{self._parquet("entities")}') s ON c.subject = s.entity_id
                  JOIN read_parquet('{self._parquet("entities")}') o ON c.object = o.entity_id
                ) {clause} ORDER BY claim_id""",
            params,
        )

    def claim_groups(self, **filters: Any) -> list[dict[str, Any]]:
        """Return grouped claims with their support and underlying claim IDs."""
        where, params = self._where(filters)
        rows = self._rows(
            f"SELECT * FROM read_parquet('{self._parquet('claim_groups')}') {where} ORDER BY group_id", params
        )
        for row in rows:
            row["claim_ids"] = json.loads(row["claim_ids"])
        return rows

    def held_out_associations(self) -> list[dict[str, Any]]:
        """Associations reserved for evaluation. They are never evidence in the graph (ADR-0011)."""
        path = self.path / "held_out" / "open_targets_sjd.parquet"
        if not path.exists():
            return []
        return self._rows(f"SELECT * FROM read_parquet('{str(path).replace(chr(39), chr(39) * 2)}') ORDER BY target")

    def contradictions(self) -> list[dict[str, Any]]:
        return self._rows(
            f"""SELECT x.claim_id_a, x.claim_id_b, a.pmid AS pmid_a, b.pmid AS pmid_b
                FROM read_parquet('{self._parquet("contradictions")}') x
                JOIN read_parquet('{self._parquet("evidence")}') a ON x.claim_id_a = a.claim_id
                JOIN read_parquet('{self._parquet("evidence")}') b ON x.claim_id_b = b.claim_id
                ORDER BY 1, 2"""
        )

    def _known_entities(self) -> set[str]:
        return {r["entity_id"] for r in self._rows(f"SELECT entity_id FROM read_parquet('{self._parquet('entities')}')")}

    def subgraph(self, entities: Iterable[str], hops: int = 1, **filters: Any) -> dict[str, Any]:
        """Return the claims within a number of hops of the chosen entities, including null results."""
        start = set(entities)
        unknown = sorted(start - self._known_entities())
        if unknown:
            raise KeyError(f"Unknown entities: {', '.join(unknown)}")
        claims = self.claims(**filters)
        reached, kept = set(start), {}
        frontier = set(start)
        for _ in range(hops):
            following: set[str] = set()
            for claim in claims:
                if claim["subject"] in frontier or claim["object"] in frontier:
                    kept[claim["claim_id"]] = claim
                    following |= {claim["subject"], claim["object"]} - reached
            reached |= following
            frontier = following
        return {"entities": reached, "claims": list(kept.values())}

    def paths(self, source: str, target: str, max_hops: int = 3, limit: int = 100, **filters: Any) -> list[dict[str, Any]]:
        """Find paths in either direction, shortest first, and report their background-layer steps.

        Null results are not used, because they do not assert a relationship. A step counts as
        background only when no disease core claim supports it.
        """
        steps: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        neighbours: dict[str, set[str]] = defaultdict(set)
        for claim in self.claims(**filters):
            if claim["negated"]:
                continue
            a, b = claim["subject"], claim["object"]
            steps[tuple(sorted((a, b)))].append(claim)
            neighbours[a].add(b)
            neighbours[b].add(a)

        found: list[list[str]] = []

        def walk(route: list[str]) -> None:
            if route[-1] == target:
                found.append(route)
                return
            if len(route) > max_hops:
                return
            for following in sorted(neighbours[route[-1]] - set(route)):
                walk(route + [following])

        walk([source])
        results = []
        for route in sorted(found, key=lambda r: (len(r), r))[:limit]:
            detail = []
            for a, b in zip(route, route[1:]):
                claims = steps[tuple(sorted((a, b)))]
                layer = "disease_core" if any(c["layer"] == "disease_core" for c in claims) else "background"
                detail.append({"from": a, "to": b, "layer": layer, "claim_ids": sorted(c["claim_id"] for c in claims)})
            results.append({
                "entities": route, "steps": detail,
                "background_steps": sum(s["layer"] == "background" for s in detail),
            })
        return results


def load(path: str | Path) -> Release:
    return Release(path)
