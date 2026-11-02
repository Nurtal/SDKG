"""Map mentions to identifiers deterministically. Close matches are never accepted."""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


HYPHENS = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")


def normal_form(mention: str) -> str:
    text = unicodedata.normalize("NFKD", mention)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("‘", "'")
    text = HYPHENS.sub("-", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def local_id(mention: str) -> str:
    # \\w keeps letters of any script, so that TNF-α and TNF-β stay different concepts.
    form = normal_form(mention)
    slug = re.sub(r"[^\w]+", "_", form).strip("_")
    return f"sdkg:{slug or 'x' + hashlib.sha256(form.encode()).hexdigest()[:16]}"


@dataclass(frozen=True)
class Resolution:
    entity_id: str
    label: str
    category: str
    resolved: bool
    reason: str | None = None


class Lexicon:
    def __init__(self, path: str | Path):
        self._entries: dict[str, set[tuple[str, str, str]]] = {}
        with Path(path).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
                entry = (row["entity_id"], row["label"], row["category"])
                self._entries.setdefault(normal_form(row["mention"]), set()).add(entry)

    def add(self, mention: str, entity_id: str, label: str, category: str) -> None:
        self._entries.setdefault(normal_form(mention), set()).add((entity_id, label, category))

    def resolve(self, mention: str) -> Resolution:
        matches = self._entries.get(normal_form(mention), set())
        if len(matches) == 1:
            entity_id, label, category = next(iter(matches))
            return Resolution(entity_id, label, category, True)
        reason = "ambiguous" if matches else "no_match"
        return Resolution(local_id(mention), mention, "unclassified", False, reason)
