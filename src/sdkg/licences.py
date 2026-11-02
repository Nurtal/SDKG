"""Enforce the licence manifest. Anything not explicitly allowed fails closed (ADR-0006)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Licences compatible with redistribution under CC BY 4.0. NC and ND variants are deliberately absent.
OPEN_SPAN_LICENCES = frozenset({"CC0-1.0", "PDM-1.0", "CC-BY-2.0", "CC-BY-2.5", "CC-BY-3.0", "CC-BY-4.0"})


@dataclass(frozen=True)
class LicenceManifest:
    publish_span_text: bool
    sources: dict[str, dict[str, Any]]

    @classmethod
    def read(cls, path: str | Path) -> "LicenceManifest":
        data = json.loads(Path(path).read_text("utf-8"))
        return cls(publish_span_text=data.get("publish_span_text", False), sources=data.get("sources", {}))

    def check(self, used: Iterable[str], allow_unconfirmed: bool = False) -> bool:
        """Stop on any disallowed source, and return whether the result may be published."""
        publishable = True
        for source in sorted(set(used)):
            if source not in self.sources:
                raise ValueError(f"Source {source} is not in the licence manifest")
            status = self.sources[source].get("status")
            if status == "allowed":
                continue
            if status == "unconfirmed" and allow_unconfirmed:
                publishable = False
                continue
            raise ValueError(f"Source {source} has licence status {status} and cannot be used in this build")
        return publishable

    def may_publish_span(self, document_licence: str | None) -> bool:
        return self.publish_span_text and document_licence in OPEN_SPAN_LICENCES
