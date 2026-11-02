"""Freeze a reproducible literature corpus (ADR-0010), and apply relevance screening."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from sdkg.extraction import ExtractionClient, load_documents, read_jsonl, run_extract
from sdkg.hydrate import abstract_text
from sdkg.normalise import normal_form

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH = 200
MAX_PAGED = 9000


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
    root = ET.fromstring(xml)
    for article in root.iter("PubmedArticle"):
        yield _article_fields(article)
    # Books and chapters count towards PubMed's total, so they must be accounted for.
    for book in root.iter("PubmedBookArticle"):
        yield {"doc_id": book.findtext("BookDocument/PMID"), "title": "", "text": None, "year": None,
               "publication_types": ["Book"], "mesh": []}


SJOGREN_LARSSON = re.compile(r"sjogren\W+larsson")
MARINESCO_SJOGREN = re.compile(r"marinesco\W+sjogren")


def _searchable(fields: dict[str, Any]) -> str:
    return normal_form(f"{fields['title']} {fields['text'] or ''}")


def _is_sjogren_larsson(fields: dict[str, Any]) -> bool:
    return bool(SJOGREN_LARSSON.search(_searchable(fields))) or "Sjogren-Larsson Syndrome" in fields["mesh"]


def classify(fields: dict[str, Any]) -> str:
    """Exclusions come first, so a Sjögren-Larsson review is never kept as a lead."""
    if "Book" in fields["publication_types"]:
        return "book"
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


def date_windows(count: Callable[[date, date], int], start: date, end: date, limit: int) -> list[tuple[date, date]]:
    """Split a period until each part has at most `limit` records. Ranges include both ends."""
    if count(start, end) <= limit:
        return [(start, end)]
    if start == end:
        raise ValueError(f"PubMed has more than {limit} records on {start.isoformat()}, so they cannot all be fetched")
    middle = start + (end - start) // 2
    return date_windows(count, start, middle, limit) + date_windows(count, middle + timedelta(days=1), end, limit)


def check_complete(reported: int, received: int) -> None:
    if received != reported:
        raise ValueError(f"PubMed reported {reported} records but {received} arrived, so the corpus is incomplete")


def _get(url: str, attempts: int = 5) -> bytes:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise
            problem = error
        except OSError as error:
            problem = error
        time.sleep(2 * (attempt + 1))
    raise problem


def _search(query: str, start: date, end: date) -> dict[str, Any]:
    params = {
        "db": "pubmed", "term": query, "usehistory": "y", "retmode": "json", "retmax": 0, "datetype": "edat",
        "mindate": start.strftime("%Y/%m/%d"), "maxdate": end.strftime("%Y/%m/%d"),
    }
    time.sleep(0.4)  # NCBI allows three requests a second without an API key.
    return json.loads(_get(f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}"))["esearchresult"]


def fetch_page(
    search: Callable[[], dict[str, Any]],
    result: dict[str, Any],
    offset: int,
    size: int,
    get: Callable[[str], bytes] = _get,
    attempts: int = 4,
    pause: float = 5.0,
) -> tuple[bytes, dict[str, Any]]:
    """Fetch one page. PubMed sometimes rejects a page from a stale session, so retry with a fresh one."""
    for attempt in range(attempts):
        page = {
            "db": "pubmed", "WebEnv": result["webenv"], "query_key": result["querykey"],
            "retstart": offset, "retmax": size, "retmode": "xml",
        }
        try:
            return get(f"{EUTILS}/efetch.fcgi?{urllib.parse.urlencode(page)}"), result
        except urllib.error.HTTPError as error:
            problem = error
        time.sleep(pause)
        result = search()
    raise ValueError(f"PubMed kept rejecting the page at offset {offset}: {problem}")


def fetch_pubmed_xml(query: str, frozen_on: str, limit: int | None = None, cache: str | Path | None = None) -> Iterable[str]:
    """Yield efetch pages up to the freeze date, by date windows, because PubMed stops paging at 10,000.

    With a cache directory, finished pages are kept, so an interrupted fetch can resume.
    """
    windows = date_windows(
        lambda a, b: int(_search(query, a, b)["count"]), date(1800, 1, 1), date.fromisoformat(frozen_on), MAX_PAGED
    )
    cache_dir = Path(cache) if cache else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for start, end in windows:
        search = lambda s=start, e=end: _search(query, s, e)
        result = search()
        total = int(result["count"])
        for offset in range(0, total, BATCH):
            if limit is not None and fetched >= limit:
                return
            size = min(BATCH, total - offset) if limit is None else min(BATCH, total - offset, limit - fetched)
            path = cache_dir / f"{start}_{end}_{total}_{offset}_{size}.xml" if cache_dir else None
            if path and path.exists():
                yield path.read_text("utf-8")
            else:
                data, result = fetch_page(search, result, offset, size)
                text = data.decode("utf-8")
                if path:
                    path.write_text(text, "utf-8")
                yield text
                time.sleep(0.4)
            fetched += size


def reported_total(query: str, frozen_on: str) -> int:
    return int(_search(query, date(1800, 1, 1), date.fromisoformat(frozen_on))["count"])


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
    expected_total: int | None = None,
) -> None:
    open_licences = _read_licences(licences)
    records: dict[str, tuple[dict[str, Any], str]] = {}
    for page in pages:
        for fields in parse_articles(page):
            records[fields["doc_id"]] = (fields, classify(fields))

    if expected_total is not None:
        check_complete(expected_total, len(records))
    documents, leads, excluded = [], [], []
    counts = {"retrieved": len(records), "primary": 0, "leads_only": 0, "case_reports": 0, "sjogren_larsson": 0, "other_disease": 0, "no_abstract": 0, "books": 0}
    labels = {"case_report": "case_reports", "book": "books"}
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
