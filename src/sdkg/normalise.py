"""Map mentions to identifiers deterministically. Close matches are never accepted."""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


HYPHENS = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")


# Abstracts write IFN-γ and IFN-gamma interchangeably.
GREEK = str.maketrans({
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "κ": "kappa",
    "λ": "lambda", "σ": "sigma", "τ": "tau", "θ": "theta", "ω": "omega",
})
# A mention of these categories can match an entity of any listed category.
COMPATIBLE = {"drug": {"drug", "chemical"}, "chemical": {"drug", "chemical"}}


def normal_form(mention: str) -> str:
    text = unicodedata.normalize("NFKD", mention)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("‘", "'")
    text = HYPHENS.sub("-", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.translate(GREEK)


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

    def resolve(self, mention: str, category: str | None = None) -> Resolution:
        """Map a mention. With a category, only entities of that category can match."""
        matches = self._entries.get(normal_form(mention), set())
        # A biomarker is a role, so the concept itself can be of any category.
        if category and category not in ("unclassified", "biomarker"):
            allowed = COMPATIBLE.get(category, {category})
            typed = {m for m in matches if m[2] in allowed}
            if matches and not typed:
                return Resolution(local_id(mention), mention, category, False, "other_category")
            matches = typed
        if len(matches) == 1:
            entity_id, label, found = next(iter(matches))
            return Resolution(entity_id, label, found, True)
        reason = "ambiguous" if matches else "no_match"
        return Resolution(local_id(mention), mention, category or "unclassified", False, reason)
