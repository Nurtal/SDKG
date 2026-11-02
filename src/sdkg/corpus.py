"""Freeze a reproducible literature corpus (ADR-0010), and apply relevance screening."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from sdkg.extraction import ExtractionClient, load_documents, read_jsonl, run_extract
from sdkg.hydrate import abstract_text
from sdkg.normalise import normal_form

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH = 200


def _article_fields(article: ET.Element) -> dict[str, Any]:
    citation = article.find("MedlineCitation")
    info = citation.find("Article")
    title = info.find("ArticleTitle")
    types = [t.text or "" for t in info.findall("PublicationTypeList/PublicationType")]
    mesh = [d.text or "" for d in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")]
    year = None
    for tag in ("Journal/JournalIssue/PubDate/Year", "Journal/JournalIssue/PubDate/MedlineDate"):
        element = info.find(tag)
        match = re.search(r"\d{4}", element.text or "") if element is not None else None
        if match:
            year = int(match.group())
            break
    return {
        "doc_id": citation.findtext("PMID"),
        "title": "".join(title.itertext()).strip() if title is not None else "",
        "text": abstract_text(article),
        "year": year,
        "publication_types": types,
        "mesh": mesh,
    }


def parse_articles(xml: str) -> Iterable[dict[str, Any]]:
    for article in ET.fromstring(xml).iter("PubmedArticle"):
        yield _article_fields(article)


SJOGREN_LARSSON = re.compile(r"sjogren\W+larsson")
MARINESCO_SJOGREN = re.compile(r"marinesco\W+sjogren")


def _searchable(fields: dict[str, Any]) -> str:
    return normal_form(f"{fields['title']} {fields['text'] or ''}")


def _is_sjogren_larsson(fields: dict[str, Any]) -> bool:
    return bool(SJOGREN_LARSSON.search(_searchable(fields))) or "Sjogren-Larsson Syndrome" in fields["mesh"]


def classify(fields: dict[str, Any]) -> str:
    """Exclusions come first, so a Sjögren-Larsson review is never kept as a lead."""
    if _is_sjogren_larsson(fields):
        return "sjogren_larsson"
    if MARINESCO_SJOGREN.search(_searchable(fields)):
        return "other_disease"
    if not fields["text"]:
        return "no_abstract"
    types = {t.lower() for t in fields["publication_types"]}
    if "case reports" in types:
        return "case_report"
    if types & {"review", "systematic review", "meta-analysis"}:
        return "leads_only"
    return "primary"


def fetch_pubmed_xml(query: str, frozen_on: str, limit: int | None = None) -> Iterable[str]:
    """Yield efetch pages for records entered in PubMed up to the freeze date."""
    params = {
        "db": "pubmed", "term": query, "usehistory": "y", "retmode": "json", "retmax": 0,
        "datetype": "edat", "mindate": "1800/01/01", "maxdate": frozen_on.replace("-", "/"),
    }
    with urllib.request.urlopen(f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}", timeout=60) as response:
        result = json.load(response)["esearchresult"]
    total = int(result["count"]) if limit is None else min(limit, int(result["count"]))
    for start in range(0, total, BATCH):
        page = {
            "db": "pubmed", "WebEnv": result["webenv"], "query_key": result["querykey"],
            "retstart": start, "retmax": min(BATCH, total - start), "retmode": "xml",
        }
        with urllib.request.urlopen(f"{EUTILS}/efetch.fcgi?{urllib.parse.urlencode(page)}", timeout=120) as response:
            yield response.read().decode("utf-8")
        time.sleep(0.4)  # NCBI allows three requests a second without an API key.


def _read_licences(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["pmid"]: row["licence"] for row in csv.DictReader(handle, delimiter="\t")}


def _rank(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")


def freeze_corpus(
    query: str,
    frozen_on: str,
    pages: Iterable[str],
    out: str | Path,
    development: int,
    seed: int,
    licences: str | Path | None = None,
    development_include: str | Path | None = None,
) -> None:
    open_licences = _read_licences(licences)
    records: dict[str, tuple[dict[str, Any], str]] = {}
    for page in pages:
        for fields in parse_articles(page):
            records[fields["doc_id"]] = (fields, classify(fields))

    documents, leads, excluded = [], [], []
    counts = {"retrieved": len(records), "primary": 0, "leads_only": 0, "case_reports": 0, "sjogren_larsson": 0, "other_disease": 0, "no_abstract": 0}
    labels = {"case_report": "case_reports"}
    for doc_id in sorted(records):
        fields, kind = records[doc_id]
        counts[labels.get(kind, kind)] += 1
        if kind in ("primary", "leads_only"):
            row = {
                "doc_id": doc_id, "title": fields["title"], "text": fields["text"], "year": fields["year"],
                "publication_type": kind, "licence": open_licences.get(doc_id, "unknown"),
            }
            if "Randomized Controlled Trial" in fields["publication_types"]:
                row["study_type"] = "randomised_trial"
            (documents if kind == "primary" else leads).append(row)
        else:
            excluded.append({"doc_id": doc_id, "reason": kind})

    # Documents already used for prompt work can never enter the test sample.
    known = {d["doc_id"] for d in documents}
    forced = set(Path(development_include).read_text("utf-8").split()) & known if development_include else set()
    others = sorted(known - forced, key=lambda k: _rank(seed, k))
    held = forced | set(others[: max(0, development - len(forced))])
    for row in documents:
        row["split"] = "development" if row["doc_id"] in held else "evaluation"

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "documents.jsonl", documents)
    _write_jsonl(out / "leads.jsonl", leads)
    _write_jsonl(out / "excluded.jsonl", excluded)
    info = {
        "source": "pubmed", "query": query, "frozen_on": frozen_on, "counts": counts,
        "development": {"size": len(held), "seed": seed},
    }
    (out / "corpus.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", "utf-8")


def run_screen(corpus: str | Path, prompt: str, client: ExtractionClient, archive: str | Path, out: str | Path) -> None:
    schema = '{"type":"object","required":["relevant","reason"]}'
    run_extract(load_documents(corpus), prompt, schema, client, archive)
    apply_screening(corpus, archive, out)


def apply_screening(corpus: str | Path, archive: str | Path, out: str | Path) -> None:
    corpus, out = Path(corpus), Path(out)
    documents = load_documents(corpus)
    decisions = {}
    for path in Path(archive).glob("*.json"):
        if path.name.startswith("_"):
            continue
        record = json.loads(path.read_text("utf-8"))
        decisions[record["doc_id"]] = record["response"]
    missing = [d["doc_id"] for d in documents if d["doc_id"] not in decisions]
    if missing:
        raise ValueError(f"{len(missing)} documents have no screening decision, for example {missing[0]}. Finish screening first.")
    kept = [d for d in documents if decisions[d["doc_id"]]["relevant"]]
    dropped = [
        {"doc_id": d["doc_id"], "title": d["title"], "text": d["text"], "reason": decisions[d["doc_id"]].get("reason")}
        for d in documents if not decisions[d["doc_id"]]["relevant"]
    ]
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "documents.jsonl", kept)
    _write_jsonl(out / "screened_out.jsonl", dropped)
    info = json.loads((corpus / "corpus.json").read_text("utf-8"))
    info["counts"].update({"screened_in": len(kept), "screened_out": len(dropped)})
    (out / "corpus.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", "utf-8")


def screening_sample(screened: str | Path, seed: int, size: int, out: str | Path) -> None:
    """Draw from kept and dropped documents evenly, so that both kinds of error can be measured."""
    screened = Path(screened)
    kept = [dict(d, screening_decision=True) for d in read_jsonl(screened / "documents.jsonl")]
    dropped = [dict(d, screening_decision=False) for d in read_jsonl(screened / "screened_out.jsonl")]
    half = size // 2
    pick = lambda rows, n: sorted(rows, key=lambda d: _rank(seed, d["doc_id"]))[:n]
    chosen = pick(kept, size - half) + pick(dropped, half)
    _write_jsonl(Path(out), sorted(chosen, key=lambda d: _rank(seed, "order" + d["doc_id"])))
