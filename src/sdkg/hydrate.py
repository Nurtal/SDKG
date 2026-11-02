"""Let users retrieve evidence span text that a release cannot republish."""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Iterable

from sdkg.extraction import text_hash
from sdkg.package import load

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def abstract_text(article: ET.Element) -> str | None:
    """The one definition of an abstract's text, so that offsets stay valid."""
    sections = ["".join(el.itertext()).strip() for el in article.iter("AbstractText")]
    return " ".join(s for s in sections if s) or None


def abstract_text_from_xml(xml: str) -> str | None:
    return abstract_text(ET.fromstring(xml))


def fetch_pubmed(pmid: str) -> str | None:
    query = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "xml"})
    with urllib.request.urlopen(f"{EFETCH}?{query}", timeout=30) as response:
        return abstract_text_from_xml(response.read().decode("utf-8"))


def hydrate(
    release: str | Path,
    fetch: Callable[[str], str | None] = fetch_pubmed,
    pmids: Iterable[str] | None = None,
) -> list[dict]:
    wanted = set(pmids) if pmids is not None else None
    cache: dict[str, str | None] = {}
    results = []
    for claim in load(release).claims():
        pmid = claim["pmid"]
        if pmid is None:  # Curated database claims have no evidence span.
            continue
        if wanted is not None and pmid not in wanted:
            continue
        if pmid not in cache:
            cache[pmid] = fetch(pmid)
        text = cache[pmid]
        span, status = None, "unavailable"
        if text is not None:
            candidate = text[claim["span_start"] : claim["span_end"]]
            if text_hash(candidate) == claim["span_hash"]:
                span, status = candidate, "verified"
            else:
                status = "text_changed"
        results.append({"claim_id": claim["claim_id"], "pmid": pmid, "span_text": span, "status": status})
    return results
