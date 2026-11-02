"""ADR-0012: decisions taken without an expert, by delegation from the project lead."""
from __future__ import annotations

import csv

import pytest

import sdkg
from sdkg.batch import extraction_output_schema

from conftest import REPO, build_with, make_claim

A = "SAMPLE:0001"
TEXT_SPAN = "Synthetic test abstract"


def curated() -> dict[str, dict]:
    with (REPO / "lexicon/curated.tsv").open(encoding="utf-8", newline="") as handle:
        return {r["mention"]: r for r in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)}


@pytest.mark.parametrize("mention,entity", [
    ("thrombocytopenia", "HP:0001873"), ("leukopenia", "HP:0001882"), ("lymphopenia", "HP:0001888"),
    ("neutropenia", "HP:0001875"), ("anemia", "HP:0001903"), ("hypokalemia", "HP:0002900"),
    ("keratoconjunctivitis sicca", "HP:0001097"), ("arthritis", "HP:0001369"), ("purpura", "HP:0000979"),
    ("peripheral neuropathy", "HP:0009830"), ("cryoglobulinemia", "HP:0100778"), ("renal tubular acidosis", "HP:0001947"),
])
def test_clinical_findings_shared_with_mondo_are_curated_as_phenotypes(mention, entity):
    row = curated()[mention]
    assert row["entity_id"] == entity
    assert row["category"] == "phenotype"


@pytest.mark.parametrize("mention", ["IL-12", "IL-23", "IL-27", "IL-35"])
def test_dimeric_cytokines_are_not_mapped_to_one_gene(mention):
    row = curated()[mention]
    assert row["entity_id"].startswith("sdkg:")
    assert row["category"] == "gene_or_protein"


def test_claim_outside_a_sjd_context_is_rejected_and_counted(workspace):
    outside = {**make_claim(), "sjd_context": False}
    inside = {**make_claim(subject="STAT4"), "sjd_context": True}

    loaded = sdkg.load(build_with(workspace, {A: [outside, inside]}))

    assert [c["subject_label"] for c in loaded.claims()] == ["STAT4"]
    assert loaded.metadata["rejected_claims"] == {"outside_sjd_context": 1}


def test_trial_identifier_is_kept_when_it_appears_in_the_abstract(workspace):
    path = workspace / "sample/corpus/documents.jsonl"
    path.write_text(path.read_text("utf-8").replace("Synthetic test abstract.", "Synthetic test abstract. NCT01234567.", 1), "utf-8")

    claim = sdkg.load(build_with(workspace, {A: [{**make_claim(), "trial_id": "NCT01234567"}]})).claims()[0]

    assert claim["trial_id"] == "NCT01234567"


@pytest.mark.parametrize("value", ["NCT99999999", "not a trial"])
def test_trial_identifier_not_in_the_abstract_is_dropped(workspace, value):
    claim = sdkg.load(build_with(workspace, {A: [{**make_claim(), "trial_id": value}]})).claims()[0]

    assert claim["trial_id"] is None


def test_structured_output_requires_the_new_fields():
    item = extraction_output_schema()["properties"]["claims"]["items"]

    assert {"sjd_context", "trial_id"} <= set(item["required"])


def test_the_prompt_explains_the_new_fields():
    prompt = (REPO / "pipeline/prompts/extract-v3.md").read_text("utf-8")

    assert "`sjd_context`" in prompt and "`trial_id`" in prompt


def test_the_decisions_say_they_are_not_expert_validation():
    text = (REPO / "docs/adr/0012-delegated-decisions-without-an-expert.md").read_text("utf-8")

    assert "not expert validation" in text
