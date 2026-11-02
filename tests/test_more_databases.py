"""Issue #14: remaining databases, and the Open Targets hold-out (ADR-0011)."""
from __future__ import annotations

import json

import duckdb

import sdkg

from conftest import build_with, make_claim, write_databases

CORE = {"SAMPLE:0001": [make_claim()]}
HPO = {"source": "hpo", "adapter": "hpo", "path": "phenotype.hpoa"}
CHEMBL = {"source": "chembl", "adapter": "chembl", "path": "chembl.json"}
TRIALS = {"source": "clinicaltrials-gov", "adapter": "clinicaltrials", "path": "clinicaltrials.json"}
TARGETS = {"source": "open-targets", "adapter": "open_targets", "path": "open_targets.json", "min_score": 0.5}
UNIPROT = {"source": "uniprot", "adapter": "uniprot_xrefs", "path": "uniprot.tsv"}
REACTOME = {"source": "reactome", "adapter": "reactome", "path": "reactome.tsv"}


def build(ws, *entries, **kw):
    return sdkg.load(build_with(ws, CORE, databases=write_databases(ws, list(entries), **kw)))


def test_hpo_annotations_of_sjd_enter_the_disease_core(workspace):
    claims = build(workspace, HPO).claims(source="hpo", object="HP:0001097")

    assert claims[0]["layer"] == "disease_core"
    assert claims[0]["predicate"] == "has_phenotype"
    assert claims[0]["subject"] == "MONDO:0010030"
    assert claims[0]["source_record"] == "ORPHA:289390|HP:0001097|PMID:0000001"


def test_hpo_not_qualifier_is_a_null_result(workspace):
    assert build(workspace, HPO).claims(source="hpo", object="HP:0000001")[0]["negated"] is True


def test_hpo_inferred_inheritance_and_unrelated_records_stay_out(workspace):
    objects = {c["object"] for c in build(workspace, HPO).claims(source="hpo")}

    assert objects == {"HP:0001097", "HP:0000001"}


def test_chembl_mechanisms_carry_drug_target_and_sign(workspace):
    claims = build(workspace, CHEMBL, max_hops=2).claims(source="chembl", subject="CHEMBL:1201576", predicate="drug_acts_on")
    by_target = {c["object"]: c for c in claims}

    assert by_target["HGNC:6120"]["sign"] == "negative"
    assert by_target["HGNC:6120"]["direct"] is True
    assert by_target["HGNC:6120"]["layer"] == "background"
    assert by_target["HGNC:11929"]["sign"] is None


def test_trials_record_intervention_phase_status_and_endpoint(workspace):
    claims = build(workspace, TRIALS).claims(source="clinicaltrials-gov", subject="CHEMBL:1201576")

    assert len(claims) == 1
    claim = claims[0]
    assert claim["predicate"] == "studied_to_treat"
    assert claim["object"] == "MONDO:0010030"
    assert claim["layer"] == "disease_core"
    assert claim["source_record"] == "NCT00000001"
    assert claim["trial_phase"] == "PHASE3"
    assert claim["trial_status"] == "COMPLETED"
    assert claim["endpoint"] == "ESSDAI change; Symptom change"


def test_unmapped_intervention_keeps_a_local_identifier(workspace):
    claims = build(workspace, TRIALS).claims(source="clinicaltrials-gov", subject="sdkg:synthetic_compound_x")

    assert len(claims) == 1


def test_non_drug_interventions_and_sjogren_larsson_trials_stay_out(workspace):
    records = {c["source_record"] for c in build(workspace, TRIALS).claims(source="clinicaltrials-gov")}
    subjects = {c["subject"] for c in build(workspace, TRIALS).claims(source="clinicaltrials-gov")}

    assert records == {"NCT00000001"}
    assert "sdkg:education" not in subjects


def test_uniprot_cross_references_let_other_sources_resolve(workspace):
    assert build(workspace, REACTOME).metadata["database_records_skipped"] == {"reactome": 1}
    # The order of entries must not matter.
    assert build(workspace, REACTOME, UNIPROT).metadata["database_records_skipped"] == {}


def test_uniprot_entries_from_other_species_are_ignored(workspace):
    lexicon = workspace / "sample/databases/reactome.tsv"
    lexicon.write_text("Q66666\tR-HSA-0000007\tu\tn\tTAS\tHomo sapiens\n", "utf-8")

    assert build(workspace, UNIPROT, REACTOME).metadata["database_records_skipped"] == {"reactome": 1}


def test_open_targets_sjd_associations_are_written_to_a_separate_file(workspace):
    loaded = build(workspace, TARGETS)

    held = loaded.held_out_associations()
    assert {(r["target"], r["score"]) for r in held} == {("HGNC:11365", 0.51), ("HGNC:6120", 0.2)}
    assert all(r["disease"] == "MONDO:0010030" for r in held)
    assert loaded.claims(source="open-targets", layer="disease_core") == []


def test_open_targets_other_associations_enter_only_the_background_above_threshold(workspace):
    claims = build(workspace, TARGETS).claims(source="open-targets")

    assert [(c["subject"], c["object"], c["layer"], c["predicate"]) for c in claims] == [
        ("HGNC:6120", "MONDO:0000001", "background", "target_for"),
    ]


def test_unconfirmed_sources_are_recorded_as_excluded(workspace):
    config = write_databases(workspace, [REACTOME])
    data = json.loads(config.read_text("utf-8"))
    data["excluded"] = [{"source": "uniprot", "reason": "licence unconfirmed"}]
    config.write_text(json.dumps(data), "utf-8")

    loaded = sdkg.load(build_with(workspace, CORE, databases=config))

    assert loaded.metadata["excluded_sources"] == [{"source": "uniprot", "reason": "licence unconfirmed"}]


def test_held_out_file_is_not_mixed_into_canonical_claims(workspace):
    release = build_with(workspace, CORE, databases=write_databases(workspace, [TARGETS]))

    rows = duckdb.sql(f"SELECT subject, object FROM read_parquet('{release}/claims.parquet')").fetchall()
    assert ("HGNC:11365", "MONDO:0010030") not in rows
