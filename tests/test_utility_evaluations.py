"""Issues #21 and #22: the three utility evaluations."""
from __future__ import annotations

import json

import pytest

from sdkg.cli import main
from sdkg.evaluations import open_targets_comparison, score_competency_questions, temporal_test

from conftest import build_with, make_claim, write_databases

A, B, C = "SAMPLE:0001", "SAMPLE:0002", "SAMPLE:0003"  # Published in 2015, 2019 and 2022.
SJD = "MONDO:0010030"


def claim(subject, obj="Sjögren's disease"):
    return make_claim(subject=subject, obj=obj)


@pytest.fixture
def timeline(workspace):
    """Before 2020: IRF5-SjD, STAT4-SjD, BAFF-STAT4. In 2022: BAFF-SjD and rituximab-prednisone."""
    return build_with(workspace, {
        A: [claim("IRF5"), claim("BAFF", "STAT4"), claim("BAFF", "IRF5")],
        B: [claim("STAT4")],
        C: [claim("BAFF"), claim("rituximab", "prednisone"), claim("IRF5")],
    }), workspace / "sample/corpus"


def test_cutoff_uses_only_earlier_publications(timeline):
    release, corpus = timeline
    result = temporal_test(release, corpus, cutoff_year=2020, k=1)

    assert result["train_edges"] == 4
    assert result["future_edges_reachable"] == 1  # BAFF-SjD. Rituximab-prednisone has unseen entities.
    assert result["future_edges_total"] == 2


def test_relationship_seen_before_and_after_the_cutoff_is_not_a_future_edge(timeline):
    release, corpus = timeline

    assert temporal_test(release, corpus, cutoff_year=2020, k=1)["future_edges_total"] == 2


def test_baseline_and_method_recall_match_a_hand_worked_example(timeline):
    """
    Undirected training graph: IRF5-SjD, STAT4-SjD, BAFF-STAT4, BAFF-IRF5.
    Degrees: all four entities have degree 2. Unconnected pairs: (BAFF, SjD), (IRF5, STAT4).
    Common neighbours: BAFF-SjD = 2 (IRF5, STAT4), IRF5-STAT4 = 2 (SjD, BAFF).
    Degree product: both 4. At k=2, each method ranks both pairs, so each finds BAFF-SjD.
    """
    release, corpus = timeline
    result = temporal_test(release, corpus, cutoff_year=2020, k=2)

    assert result["methods"]["common_neighbours"]["hits"] == 1
    assert result["methods"]["common_neighbours"]["recall_at_k"] == 1.0
    assert result["methods"]["node_degree_baseline"]["recall_at_k"] == 1.0
    assert result["candidates"] == 2


def test_results_are_labelled_as_recall_of_future_knowledge_not_discovery(timeline):
    release, corpus = timeline

    assert "not discovery" in temporal_test(release, corpus, cutoff_year=2020, k=1)["interpretation"]


def test_no_later_information_leaks_into_the_training_graph(workspace):
    """A predictor that cheated would see this edge. It must not appear in training."""
    release = build_with(workspace, {A: [claim("IRF5")], C: [claim("STAT4")]})

    result = temporal_test(release, workspace / "sample/corpus", cutoff_year=2020, k=1)
    assert result["train_edges"] == 1
    assert result["train_entities"] == 2


def test_failed_trials_count_as_a_reference_when_trials_are_used(workspace):
    release = build_with(workspace, {
        A: [claim("IRF5"), claim("STAT4"), claim("BAFF", "IRF5")],
        C: [make_claim(subject="BAFF", predicate="affects", negated=True)],
    })
    result = temporal_test(release, workspace / "sample/corpus", cutoff_year=2020, k=1, include_null_results=True)

    assert result["future_edges_total"] == 1
    assert result["future_null_results"] == 1


def test_null_results_are_not_counted_as_new_relationships_by_default(workspace):
    release = build_with(workspace, {
        A: [claim("IRF5")],
        C: [make_claim(subject="STAT4", negated=True)],
    })

    assert temporal_test(release, workspace / "sample/corpus", cutoff_year=2020, k=1)["future_edges_total"] == 0


def test_cli_writes_the_temporal_report(timeline, tmp_path):
    release, corpus = timeline
    out = tmp_path / "t.json"

    assert main(["temporal-test", "--release", str(release), "--corpus", str(corpus), "--cutoff-year", "2020", "--k", "1", "--out", str(out)]) == 0
    assert json.loads(out.read_text("utf-8"))["cutoff_year"] == 2020


# Open Targets comparison


@pytest.fixture
def compared(workspace):
    config = write_databases(workspace, [
        {"source": "open-targets", "adapter": "open_targets", "path": "open_targets.json"},
        {"source": "clinicaltrials-gov", "adapter": "clinicaltrials", "path": "clinicaltrials.json"},
        {"source": "chembl", "adapter": "chembl", "path": "chembl.json"},
    ])
    # Held out: STAT4 and IRF5. Literature: IRF5 (overlap) and BAFF (addition). STAT4 is a gap.
    return build_with(workspace, {A: [claim("IRF5"), claim("BAFF")], B: [make_claim(subject="STAT4", negated=True)]}, databases=config)


def test_comparison_reports_overlap_additions_and_gaps(compared):
    result = open_targets_comparison(compared)

    assert result["overlap"] == ["HGNC:6120"]
    assert result["additions"] == ["HGNC:11929"]
    assert result["gaps"] == ["HGNC:11365"]
    assert result["held_out_targets"] == 2
    assert result["literature_targets"] == 2


def test_comparison_uses_only_literature_derived_disease_core_claims(compared):
    # ClinicalTrials.gov puts a drug in the disease core. It must not count as a literature target.
    result = open_targets_comparison(compared)

    assert "CHEMBL:1201576" not in result["additions"]


def test_comparison_excludes_null_results(compared):
    assert "HGNC:11365" not in open_targets_comparison(compared)["overlap"]


def test_comparison_requires_held_out_associations(release):
    with pytest.raises(ValueError, match="held-out"):
        open_targets_comparison(release)


# Competency questions


def test_competency_question_score_uses_reference_answers():
    references = [{"id": "CQ01", "type": "checkable"}, {"id": "CQ02", "type": "checkable"}, {"id": "CQ04", "type": "exploratory"}]
    judgements = [{"id": "CQ01", "correct": True}, {"id": "CQ02", "correct": False}, {"id": "CQ04", "useful": True, "traceable": True}]

    result = score_competency_questions(references, judgements)

    assert result["checkable"] == {"total": 2, "correct": 1, "rate": 0.5}
    assert result["exploratory"] == {"total": 1, "useful_and_traceable": 1, "rate": 1.0}


def test_competency_question_score_refuses_missing_judgements():
    with pytest.raises(ValueError, match="CQ02"):
        score_competency_questions([{"id": "CQ02", "type": "checkable"}], [])
