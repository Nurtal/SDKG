"""Pipeline commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sdkg.build import run_build
from sdkg.hydrate import hydrate
from sdkg.session import import_session, next_batch
from sdkg.site import run_site
from sdkg.lexicon import build_lexicon
from sdkg.schema_tools import SCHEMA_DIR, generate_all
from sdkg.validation import run_evaluate, run_sample
from sdkg.corpus import fetch_pubmed_xml, freeze_corpus, reported_total, run_screen, screening_sample
from sdkg.evaluations import open_targets_comparison, score_competency_questions, temporal_test
from sdkg.extraction import RecordedClient, RecordedDecisions, read_jsonl, load_documents, run_extract


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdkg")
    commands = p.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Archive raw LLM outputs for frozen documents")
    extract.add_argument("--corpus", required=True)
    extract.add_argument("--prompt", required=True)
    extract.add_argument("--schema", required=True)
    extract.add_argument("--recorded", required=True, help="Saved responses to replay")
    extract.add_argument("--out", required=True)

    build = commands.add_parser("build", help="Build a release from archived outputs")
    build.add_argument("--corpus", required=True)
    build.add_argument("--archive", required=True)
    build.add_argument("--licences", required=True)
    build.add_argument("--lexicon", required=True, help="TSV of mention, entity_id, label and category")
    build.add_argument("--out", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--databases", help="Configuration of frozen database snapshots")
    build.add_argument(
        "--allow-unconfirmed", action="store_true",
        help="Allow sources with unconfirmed licences for private use, and mark the release not publishable",
    )

    schema = commands.add_parser("generate-schema", help="Regenerate schema artefacts (requires the dev extra)")
    schema.add_argument("--source", default=str(SCHEMA_DIR / "sdkg.yaml"))
    schema.add_argument("--out", default=str(SCHEMA_DIR / "generated"))

    spans = commands.add_parser("spans", help="Retrieve evidence span text from source abstracts")
    spans.add_argument("--release", required=True)
    spans.add_argument("--pmid", action="append", help="Limit to this PMID; can be repeated")
    spans.add_argument("--out", required=True, help="Output JSONL file")

    corpus = commands.add_parser("corpus", help="Freeze the literature corpus")
    corpus.add_argument("--query-file", required=True)
    corpus.add_argument("--frozen-on", required=True, help="Freeze date, as YYYY-MM-DD")
    corpus.add_argument("--from-xml", action="append", help="Use saved PubMed XML instead of querying PubMed")
    corpus.add_argument("--cache", help="Directory that keeps fetched pages, so an interrupted fetch can resume")
    corpus.add_argument("--limit", type=int, help="Fetch at most this many records from PubMed")
    corpus.add_argument("--licences", help="TSV of pmid and licence for open-access articles")
    corpus.add_argument("--development", required=True, type=int, help="Number of documents in the development set")
    corpus.add_argument("--development-include", help="File of PMIDs that must be in the development set")
    corpus.add_argument("--seed", required=True, type=int)
    corpus.add_argument("--out", required=True)

    screen = commands.add_parser("screen", help="Apply relevance screening to a frozen corpus")
    screen.add_argument("--corpus", required=True)
    screen.add_argument("--prompt", required=True)
    screen.add_argument("--recorded", required=True, help="Saved decisions to replay")
    screen.add_argument("--archive", required=True)
    screen.add_argument("--out", required=True)

    screen_sample = commands.add_parser("screen-sample", help="Draw a sample for measuring screening errors")
    screen_sample.add_argument("--screened", required=True)
    screen_sample.add_argument("--seed", required=True, type=int)
    screen_sample.add_argument("--size", required=True, type=int)
    screen_sample.add_argument("--out", required=True)

    lexicon = commands.add_parser("lexicon", help="Build the lexicon from frozen gene and ontology snapshots")
    lexicon.add_argument("--config", required=True)
    lexicon.add_argument("--licences", required=True)
    lexicon.add_argument("--out", required=True)
    lexicon.add_argument("--allow-unconfirmed", action="store_true", help="Private use only: the report is marked not publishable")

    batch = commands.add_parser("next-batch", help="Write the next documents to read in a session")
    batch.add_argument("--corpus", required=True)
    batch.add_argument("--archive", required=True)
    batch.add_argument("--size", required=True, type=int)
    batch.add_argument("--seed", required=True, type=int)
    batch.add_argument("--split", choices=["development", "evaluation"])
    batch.add_argument("--out", required=True)

    session = commands.add_parser("import-session", help="Archive claims extracted in a session, with no paid API")
    session.add_argument("--corpus", required=True)
    session.add_argument("--responses", required=True)
    session.add_argument("--prompt", required=True)
    session.add_argument("--archive", required=True)

    site = commands.add_parser("site", help="Generate the static website from a release")
    site.add_argument("--release", required=True)
    site.add_argument("--out", required=True)
    site.add_argument("--data-notice", help="A prominent notice, for example that the data is a synthetic sample")
    site.add_argument("--downloads-url", help="Link to the versioned release instead of copying exports")

    temporal = commands.add_parser("temporal-test", help="Predict later relationships from earlier publications")
    temporal.add_argument("--release", required=True)
    temporal.add_argument("--corpus", required=True)
    temporal.add_argument("--cutoff-year", required=True, type=int)
    temporal.add_argument("--k", required=True, type=int)
    temporal.add_argument("--include-null-results", action="store_true")
    temporal.add_argument("--out", required=True)

    comparison = commands.add_parser("compare-targets", help="Compare literature targets with held-out Open Targets associations")
    comparison.add_argument("--release", required=True)
    comparison.add_argument("--out", required=True)

    questions = commands.add_parser("score-questions", help="Score competency questions against reference answers")
    questions.add_argument("--references", required=True)
    questions.add_argument("--judgements", required=True)
    questions.add_argument("--out", required=True)

    sample = commands.add_parser("sample", help="Draw the blinded, stratified test sample")
    sample.add_argument("--release", required=True)
    sample.add_argument("--corpus", required=True)
    sample.add_argument("--freeze", required=True, help="Record of the frozen prompt")
    sample.add_argument("--seed", required=True, type=int)
    sample.add_argument("--size", required=True, type=int)
    sample.add_argument("--double", required=True, type=int, help="Items also given to the second reviewer")
    sample.add_argument("--out", required=True)

    evaluation = commands.add_parser("evaluate", help="Compute precision, agreement, recall and predicate status")
    evaluation.add_argument("--key", required=True)
    evaluation.add_argument("--judgements-a", required=True)
    evaluation.add_argument("--judgements-b")
    evaluation.add_argument("--annotations", help="Claims annotated blind, for recall")
    evaluation.add_argument("--predictions", help="Model claims for the annotated documents")
    evaluation.add_argument("--threshold", type=float, default=0.7)
    evaluation.add_argument("--out", required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "extract":
        run_extract(
            load_documents(args.corpus),
            Path(args.prompt).read_text("utf-8"),
            Path(args.schema).read_text("utf-8"),
            RecordedClient(args.recorded),
            args.out,
        )
    elif args.command == "build":
        run_build(args.corpus, args.archive, args.licences, args.lexicon, args.out, args.version, args.allow_unconfirmed, args.databases)
    elif args.command == "corpus":
        query = Path(args.query_file).read_text("utf-8").strip()
        pages = (
            [Path(p).read_text("utf-8") for p in args.from_xml] if args.from_xml
            else fetch_pubmed_xml(query, args.frozen_on, args.limit, args.cache)
        )
        # A limited or file-based run is partial by design, so only a full fetch is checked for completeness.
        expected = reported_total(query, args.frozen_on) if not args.from_xml and args.limit is None else None
        freeze_corpus(query, args.frozen_on, pages, args.out, args.development, args.seed, args.licences, args.development_include, expected)
    elif args.command == "screen":
        run_screen(args.corpus, Path(args.prompt).read_text("utf-8"), RecordedDecisions(args.recorded), args.archive, args.out)
    elif args.command == "screen-sample":
        screening_sample(args.screened, args.seed, args.size, args.out)
    elif args.command == "lexicon":
        build_lexicon(args.config, args.licences, args.out, args.allow_unconfirmed)
    elif args.command == "next-batch":
        remaining = next_batch(args.corpus, args.archive, args.size, args.seed, args.out, args.split)
        print(f"{remaining} documents remain before this batch")
    elif args.command == "import-session":
        print(f"{import_session(args.corpus, args.responses, Path(args.prompt).read_text('utf-8'), args.archive)} documents archived")
    elif args.command == "site":
        run_site(args.release, args.out, args.data_notice, args.downloads_url)
    elif args.command == "temporal-test":
        report = temporal_test(args.release, args.corpus, args.cutoff_year, args.k, args.include_null_results)
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    elif args.command == "compare-targets":
        Path(args.out).write_text(json.dumps(open_targets_comparison(args.release), indent=2, sort_keys=True) + "\n", "utf-8")
    elif args.command == "score-questions":
        report = score_competency_questions(read_jsonl(Path(args.references)), read_jsonl(Path(args.judgements)))
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    elif args.command == "sample":
        run_sample(args.release, args.corpus, args.freeze, args.seed, args.size, args.double, args.out)
    elif args.command == "evaluate":
        run_evaluate(args.key, args.judgements_a, args.out, args.judgements_b, args.threshold, args.annotations, args.predictions)
    elif args.command == "generate-schema":
        generate_all(args.source, args.out)
    elif args.command == "spans":
        rows = hydrate(args.release, pmids=args.pmid)
        Path(args.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return 0
