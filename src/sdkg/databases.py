"""Turn frozen database snapshots into curated-source claims (ADR-0002)."""
from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from sdkg.normalise import Lexicon, Resolution, normal_form


@dataclass(frozen=True)
class Node:
    """An endpoint: resolved through the lexicon, unless the source's own identifier is authoritative."""

    mention: str
    entity_id: str | None = None
    label: str | None = None
    category: str | None = None
    allow_local: bool = False  # Keep an unmapped mention under a local identifier instead of skipping it.


@dataclass(frozen=True)
class Record:
    subject: Node
    predicate: str
    object: Node
    record_id: str
    sign: str | None = None
    negated: bool = False
    fields: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


def read_reactome(path: Path) -> Iterable[Record]:
    """UniProt2Reactome: accession, pathway, URL, name, evidence code, species. No header."""
    with path.open(encoding="utf-8", newline="") as handle:
        for accession, pathway, _url, name, evidence, species in csv.reader(handle, delimiter="\t"):
            # Electronically inferred (IEA) mappings are not high-confidence.
            if species != "Homo sapiens" or evidence == "IEA":
                continue
            yield Record(
                subject=Node(accession),
                predicate="participates_in",
                object=Node(pathway, f"REACTOME:{pathway}", name, "pathway_or_process"),
                record_id=f"{accession}|{pathway}",
            )


def read_hpo(path: Path) -> Iterable[Record]:
    """phenotype.hpoa, keeping phenotypic annotations (aspect P) not inferred electronically."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        for row in rows:
            if row["aspect"] != "P" or row["evidence"] == "IEA":
                continue
            yield Record(
                subject=Node(row["database_id"]),
                predicate="has_phenotype",
                object=Node(row["hpo_id"], row["hpo_id"], None, "phenotype"),
                record_id=f"{row['database_id']}|{row['hpo_id']}|{row['reference']}",
                negated=row["qualifier"] == "NOT",
            )


NEGATIVE_ACTIONS = {"INHIBITOR", "ANTAGONIST", "NEGATIVE ALLOSTERIC MODULATOR", "BLOCKER", "INVERSE AGONIST"}
POSITIVE_ACTIONS = {"AGONIST", "ACTIVATOR", "POSITIVE ALLOSTERIC MODULATOR", "PARTIAL AGONIST"}


def read_chembl(path: Path) -> Iterable[Record]:
    """ChEMBL drug mechanisms. Sign is given only for action types with a clear direction."""
    for row in json.loads(path.read_text("utf-8"))["mechanisms"]:
        if not row.get("target_chembl_id"):
            continue
        drug = row["molecule_chembl_id"]
        action = (row.get("action_type") or "").upper()
        sign = "negative" if action in NEGATIVE_ACTIONS else "positive" if action in POSITIVE_ACTIONS else None
        yield Record(
            subject=Node(drug, f"CHEMBL:{drug.removeprefix('CHEMBL')}", drug, "drug"),
            predicate="drug_acts_on",
            object=Node(row["target_chembl_id"]),
            record_id=f"mechanism:{row['mec_id']}",
            sign=sign,
            fields={"direct": bool(row["direct_interaction"]) if row.get("direct_interaction") is not None else None},
        )


def is_sjogrens_disease(condition: str) -> bool:
    text = normal_form(html.unescape(condition))
    return "sjogren" in text and "larsson" not in text and "marinesco" not in text


def read_clinicaltrials(path: Path) -> Iterable[Record]:
    """ClinicalTrials.gov API v2 studies. Registrations do not state whether a trial succeeded."""
    for study in json.loads(path.read_text("utf-8"))["studies"]:
        protocol = study["protocolSection"]
        if not any(is_sjogrens_disease(c) for c in protocol.get("conditionsModule", {}).get("conditions", [])):
            continue
        fields = {
            "trial_phase": "; ".join(protocol.get("designModule", {}).get("phases", [])) or None,
            "trial_status": protocol.get("statusModule", {}).get("overallStatus"),
            "endpoint": "; ".join(o["measure"] for o in protocol.get("outcomesModule", {}).get("primaryOutcomes", [])) or None,
        }
        nct = protocol["identificationModule"]["nctId"]
        for intervention in protocol.get("armsInterventionsModule", {}).get("interventions", []):
            if intervention.get("type") in ("DRUG", "BIOLOGICAL"):
                yield Record(
                    subject=Node(intervention["name"], allow_local=True),
                    predicate="studied_to_treat",
                    object=Node("Sjögren's disease"),
                    record_id=nct,
                    fields=fields,
                )


def read_open_targets(path: Path) -> Iterable[Record]:
    """Associated targets per disease, as returned by the Open Targets GraphQL API."""
    for disease in json.loads(path.read_text("utf-8"))["diseases"]:
        disease_id = disease["id"].replace("_", ":")
        for row in disease["associatedTargets"]["rows"]:
            symbol = row["target"]["approvedSymbol"]
            yield Record(
                subject=Node(symbol),
                predicate="target_for",
                object=Node(disease_id, disease_id, None, "disease"),
                record_id=f"{row['target']['id']}|{disease_id}",
                score=row["score"],
            )


def read_uniprot_xrefs(path: Path) -> Iterable[tuple[str, str, str]]:
    """UniProt accession, HGNC identifier and gene symbol, for human entries."""
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            hgnc = (row.get("HGNC") or "").split(";")[0].strip()
            if row["Organism (ID)"] == "9606" and hgnc:
                yield row["Entry"], hgnc, row["Gene Names (primary)"] or hgnc


ADAPTERS: dict[str, Callable[[Path], Iterable[Record]]] = {
    "reactome": read_reactome,
    "hpo": read_hpo,
    "chembl": read_chembl,
    "clinicaltrials": read_clinicaltrials,
    "open_targets": read_open_targets,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class DatabaseConfig:
    disease_id: str
    max_hops: int
    entries: list[dict[str, Any]]
    root: Path
    excluded: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def read(cls, path: str | Path) -> "DatabaseConfig":
        path = Path(path)
        data = json.loads(path.read_text("utf-8"))
        if data["max_hops"] not in (1, 2):
            raise ValueError("The background layer is limited to 1 or 2 hops from the disease core")
        return cls(data["disease_id"], data["max_hops"], data["databases"], path.parent, data.get("excluded", []))

    def sources(self) -> list[str]:
        return [e["source"] for e in self.entries]


@dataclass
class ResolvedRecord:
    source: str
    version: str
    record: Record
    subject: Resolution
    object: Resolution
    layer: str


@dataclass(frozen=True)
class HeldOutAssociation:
    target: str
    disease: str
    score: float
    record_id: str


def _resolve(node: Node, names: Lexicon) -> Resolution:
    if node.entity_id:
        return Resolution(node.entity_id, node.label or node.mention, node.category or "unclassified", True)
    return names.resolve(node.mention)


def load_records(
    config: DatabaseConfig, names: Lexicon
) -> tuple[list[ResolvedRecord], list[HeldOutAssociation], dict[str, int]]:
    """Read every snapshot. Records whose endpoints cannot be identified are skipped and counted."""
    records: list[ResolvedRecord] = []
    held_out: list[HeldOutAssociation] = []
    skipped: dict[str, int] = defaultdict(int)

    def verified(entry: dict[str, Any]) -> Path:
        path = config.root / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"The {entry['source']} snapshot does not match its recorded hash")
        return path

    # Cross-references load first, so that the order of entries does not matter.
    for entry in config.entries:
        if entry["adapter"] == "uniprot_xrefs":
            for accession, hgnc, symbol in read_uniprot_xrefs(verified(entry)):
                names.add(accession, hgnc, symbol, "gene_or_protein")

    for entry in config.entries:
        if entry["adapter"] == "uniprot_xrefs":
            continue
        for record in ADAPTERS[entry["adapter"]](verified(entry)):
            subject, obj = _resolve(record.subject, names), _resolve(record.object, names)
            usable = (subject.resolved or record.subject.allow_local) and (obj.resolved or record.object.allow_local)
            if not usable:
                skipped[entry["source"]] += 1
                continue
            is_sjd = config.disease_id in (subject.entity_id, obj.entity_id)
            if entry["adapter"] == "open_targets":
                # SjD associations are reserved for evaluation, whatever their score (ADR-0011).
                if is_sjd:
                    held_out.append(HeldOutAssociation(subject.entity_id, obj.entity_id, record.score, record.record_id))
                    continue
                if record.score < entry.get("min_score", 0.5):
                    continue
            layer = "disease_core" if is_sjd else "background"
            records.append(ResolvedRecord(entry["source"], entry["version"], record, subject, obj, layer))
    return records, held_out, dict(skipped)


def within_hops(records: list[ResolvedRecord], core: set[str], max_hops: int) -> list[ResolvedRecord]:
    """Keep background records reached by walking at most max_hops from a disease core entity."""
    adjacency: dict[str, list[ResolvedRecord]] = defaultdict(list)
    for item in records:
        adjacency[item.subject.entity_id].append(item)
        adjacency[item.object.entity_id].append(item)
    kept: dict[int, ResolvedRecord] = {}
    frontier, seen = set(core), set(core)
    for _ in range(max_hops):
        following: set[str] = set()
        for entity in sorted(frontier):
            for item in adjacency.get(entity, []):
                kept[id(item)] = item
                for endpoint in (item.subject.entity_id, item.object.entity_id):
                    if endpoint not in seen:
                        seen.add(endpoint)
                        following.add(endpoint)
        frontier = following
    return list(kept.values())
