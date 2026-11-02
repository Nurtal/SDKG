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
- **Fragmented concepts:** the first prompt asked for concepts as written, which gave several names for one concept. Prompt v1 asks for short standard names and keeps direction and tissue in their own fields.
- **Predicate direction:** one predicate was used in both directions. Prompt v1 defines the subject and object of each predicate.
- **Evidence model:** abstracts often say only "Sjögren's disease". Prompt v1 treats this as `human` unless secondary disease is stated.

## Open questions for the expert

These need a decision in issue #9.

1. **MONDO over HPO:** `thrombocytopenia`, `hypokalemia` and `keratoconjunctivitis sicca` now resolve to MONDO diseases, although in Sjögren's disease they may be better treated as HPO phenotypes. Which should win, and which curated exceptions are needed?
2. **Is a disease core claim always about the disease?** Literature claims enter the disease core once they pass screening and extraction. Nothing checks this separately, so noise would appear there. Should claims need an explicit Sjögren's disease population?
3. **Remaining unmatched concepts:** these include measures such as `odor identification`, specific variants such as `Δ7 FoxP3`, and new products such as `T-IDLESTCE`. Is a local identifier acceptable for them? Measures may need a curated list.
4. **IL-35:** this cytokine is a dimer of two genes, so no single HGNC entry matches. How should complexes be represented?
5. **Trial identifiers:** abstracts often cite NCT numbers, which the extraction does not capture and which could link claims to ClinicalTrials.gov. Should a field be added?

## What the pilot must confirm

- **Corpus noise:** 5 of the 10 abstracts had no qualifying claim. Causes included untagged reviews, a gene name containing "Sjögren", and a score name used in another disease. The sample is small and contains only the newest records, so it needs measuring. Screening matters more than expected, and it saves cost.
- **Real API behaviour:** the structured output schema, refusal rate and token use are still unmeasured.
- **Real extraction:** session extraction may not match a batch run with the frozen prompt.
