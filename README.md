# SDKG: Sjögren's Disease Knowledge Graph

An open, evidence-linked knowledge graph of Sjögren's disease (SjD), built for computational use.

**Status: design stage.** There is no code or data yet. No extraction has been run, and no quality figures exist.

## Summary

SDKG will integrate molecular mechanisms, cellular processes, clinical manifestations, biomarkers and therapeutic targets into one graph. It will draw on curated public databases, biomedical ontologies and the scientific literature.

Every relationship is stored as a claim linked to its source, evidence and context. Most literature claims will be extracted by an LLM. Their quality will be estimated by human review of a random sample, not assumed from full curation.

The graph is intended to support network analysis, graph machine learning, and the generation and prioritisation of hypotheses. It does not validate those hypotheses and contains no patient-level data.

## Deliverables

| Deliverable | Role |
|---|---|
| Graph and computational exports | **Primary output** |
| Resource paper | Reports the method, validation and limitations |
| Python package and notebooks | Programmatic access and subgraph extraction |
| Static website | Secondary: entity search, neighbourhoods with evidence, downloads |

## Scope of v1

- **Content:** defined by the [competency questions](docs/competency-questions.md). Comprehensiveness is a long-term aim, not a v1 criterion.
- **Population:** human primary SjD. Secondary SjD, animal and in vitro evidence are included only when tagged and filterable.
- **Literature:** primary-research PubMed abstracts, with about 12,600 records before relevance screening. This count comes from a provisional query run on 2026-11-02. Open-access full text is used only on a comparison subset.
- **Databases:** UniProt, Reactome, ChEMBL, HPO annotations, ClinicalTrials.gov and Open Targets, all subject to licence confirmation.

### Out of scope for v1

- Patient-level data, or discovering endotypes
- Claims that the graph supports mechanistic modelling, until this is demonstrated on a real model
- A live query server
- Describing the whole graph as "curated"

## Planned exports

| Format | Content | Fidelity |
|---|---|---|
| Parquet/TSV | Entities, claims and evidence | Source of truth |
| RDF, JSON-LD | The same content, with claims reified | Lossless |
| GraphML, edge lists | Collapsed graph, using published filtering rules | Lossy |
| OWL | Schema only | No instances |

## Evaluation plan

Extraction quality follows the protocol in [ADR-0004](docs/adr/0004-llm-extraction-validated-by-sampling.md). The graph's utility is assessed in three ways, defined before results are seen:

1. **Competency questions:** the rate of correct answers, as judged by the expert.
2. **Temporal test:** a graph limited to publications before a given date predicts relationships published later, compared with simple baselines such as node degree. This measures recall of future knowledge, not discovery. If trials are used as a reference, failed trials count too.
3. **Open Targets comparison:** the overlap with, additions to and gaps against the SjD associations held out in [ADR-0011](docs/adr/0011-open-targets-sjd-associations-held-out.md).

## Engineering and release policy

- **Stack:** Python and DuckDB, with a single-command rebuild from archived LLM outputs.
- **Repository:** code, schema, prompts, manifests and a small sample graph. Full exports and raw LLM outputs go to Zenodo, subject to the legal review.
- **CI:** tests, validation and site publishing on the sample graph, with no LLM calls.
- **Extraction runs:** session-based prototyping, then the batch API with `claude-opus-5-5` and structured output for production.
- **Normalisation:** the LLM proposes a mention and a deterministic tool maps it to an identifier. Concepts missing from ontologies use a local `sdkg:` namespace, and the unresolved-entity rate is published.
- **Releases:** dated with a Zenodo DOI, stable claim IDs derived from normalised content, and a report of differences. The target is one release a year after v1.
- **Updates:** only new PMIDs are extracted. A full re-extraction means a new major version.

## Roadmap

1. **Framing:** draft the competency questions and have the domain expert validate them.
2. **Minimal end-to-end pipeline:** process 200 abstracts from extraction through to exports.
3. **Decision point:** measure precision on the development set and estimate total cost.
4. **Preregistration:** register the validation protocol and freeze the prompt.
5. **Full extraction:** run on the v1 corpus.
6. **Validation:** human review and the utility evaluations.
7. **Release:** publish v1 and submit the paper.

The internal target date will be set after step 3.

## Prerequisites

- [ ] Domain expert identified, with 1–2 days a month available
- [ ] Second human reviewer recruited (required before paper submission)
- [ ] Claude API key and budget
- [ ] Licence review of quoted abstract passages and archived raw LLM outputs
- [ ] Source licences confirmed in a manifest

## Documentation

- [Glossary](GLOSSARY.md): the project's vocabulary
- [Architecture decisions](docs/adr/): what was decided and why
- [Competency questions](docs/competency-questions.md): the draft that defines v1 content

## Licensing

Planned licences are Apache-2.0 for code and CC BY 4.0 for data. No licence files have been added yet.
