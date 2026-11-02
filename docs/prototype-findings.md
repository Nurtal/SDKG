# Prototype findings

On 2026-11-02, the pipeline ran on 10 real abstracts, with extraction done in a Claude Code session instead of through the API. Nothing was published, and abstract text and outputs were not committed.

**These are not quality results.** It was one model judging its own work on 10 abstracts, the second run knew what the lexicon contained, and no human reviewed anything. The figures show defects in the pipeline. They do not estimate precision or recall, which remain for the validation protocol in ADR-0004.

The 10 PMIDs are in `pipeline/prototype-pmids.txt`. Prompts were changed after reading them, so they must stay in the development set. Pass that file to `sdkg corpus --development-include`.

## Results

| Measure | First run | After fixes |
|---|---|---|
| Claims rejected with a valid passage | 4 of 25 | 0 of 23 |
| Entities without an ontology match | 82% | 46% |

## Defects fixed

- **Typographic characters:** 28 of 72 real abstracts contain thin spaces, non-breaking spaces or special hyphens, so strict matching rejected valid passages. Matching now allows these differences, while words and numbers must still match.
- **Plural cell names:** `B cells` and `T cells` did not resolve. Cell Ontology names now also match their plural.
- **Disease and phenotype conflicts:** `lymphoma` and `rheumatoid arthritis` were ambiguous because both MONDO and HPO list them. MONDO now takes priority, unless a curated mention says otherwise.
- **Missing instruments:** ESSDAI, ESSPRI, ClinESSDAI, anti-SSA/Ro and anti-SSB/La now have curated entries with local identifiers.
- **Fragmented concepts:** the first prompt asked for concepts as written, which gave several names for one concept. The prompt asks for short standard names and keeps direction and tissue in their own fields.
- **Predicate direction:** one predicate was used in both directions. The prompt defines the subject and object of each predicate.
- **Evidence model:** abstracts often say only "Sjögren's disease". The prompt treats this as `human` unless secondary disease is stated.

## Open questions for the expert

These five questions were answered by delegation, without an expert, in [ADR-0012](adr/0012-delegated-decisions-without-an-expert.md). An expert can overturn them.

## What the pilot must confirm

- **Corpus noise:** 5 of the 10 abstracts had no qualifying claim. Causes included untagged reviews, a gene name containing "Sjögren", and a score name used in another disease. The sample is small and contains only the newest records, so it needs measuring. Screening matters more than expected, and it saves cost.
- **Real API behaviour:** the structured output schema, refusal rate and token use are still unmeasured.
- **Real extraction:** session extraction may not match a batch run with the frozen prompt.
