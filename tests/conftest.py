from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from sdkg.cli import main

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "sample"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A private, editable copy of the sample inputs."""
    shutil.copytree(SAMPLE, tmp_path / "sample")
    return tmp_path


def run_extract(ws: Path, archive: str = "archive") -> Path:
    out = ws / archive
    code = main(
        [
            "extract",
            "--corpus", str(ws / "sample/corpus"),
            "--prompt", str(ws / "sample/prompts/extract-v0.md"),
            "--schema", str(ws / "sample/prompts/extraction-output.schema.json"),
            "--recorded", str(ws / "sample/recorded/responses.jsonl"),
            "--out", str(out),
        ]
    )
    assert code == 0
    return out


def write_databases(ws: Path, databases: list[dict], max_hops: int = 1) -> Path:
    """Write a database configuration, recording each snapshot's hash."""
    entries = []
    for entry in databases:
        snapshot = ws / "sample/databases" / entry["path"]
        entries.append({"version": "test", "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(), **entry})
    path = ws / "sample/databases/databases.json"
    path.write_text(json.dumps({"disease_id": "MONDO:0010030", "max_hops": max_hops, "databases": entries}), "utf-8")
    return path


def run_build(ws: Path, archive: Path, out: str = "release", databases: Path | None = None) -> Path:
    target = ws / out
    extra = ["--databases", str(databases)] if databases else []
    code = main(
        [
            "build",
            *extra,
            "--corpus", str(ws / "sample/corpus"),
            "--archive", str(archive),
            "--licences", str(ws / "sample/licences.json"),
            "--lexicon", str(ws / "sample/lexicon.tsv"),
            "--out", str(target),
            "--version", "0.0.0-test",
        ]
    )
    assert code == 0
    return target


@pytest.fixture
def release(workspace: Path) -> Path:
    return run_build(workspace, run_extract(workspace))


def make_claim(subject="IRF5", obj="Sjögren's disease", predicate="associated_with", span="Synthetic test abstract", sign=None, **context) -> dict:
    negated = context.pop("negated", False)
    full = {"species": "human", "tissue": None, "population": None, "assay": None, "evidence_model": "human", **context}
    return {"subject": subject, "predicate": predicate, "object": obj, "span": span, "sign": sign, "negated": negated, "context": full}


def build_with(ws: Path, by_document: dict[str, list[dict]], out: str = "release", archive: str = "archive", databases: Path | None = None) -> Path:
    """Replace the recorded responses for the given documents, then extract and build."""
    path = ws / "sample/recorded/responses.jsonl"
    rows = [json.loads(l) for l in path.read_text("utf-8").splitlines()]
    for row in rows:
        row["claims"] = by_document.get(row["doc_id"], [])
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    return run_build(ws, run_extract(ws, archive), out, databases)
