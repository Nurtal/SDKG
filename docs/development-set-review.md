# Development set review

On 2026-11-02, Claude read all 200 development-set abstracts in a Claude Code session (ADR-0013). Abstract text, claims and the resulting graph are not committed, because source licences and the legal review are unresolved.

**These figures do not measure extraction quality.** Claude judged its own reading, and no human has reviewed a claim. Precision and recall remain unknown until the review in ADR-0004 happens. The prompt also changed during the work: the first 60 abstracts used an earlier wording of `extract-v3`, so the set does not have one prompt hash.

## Results

| Measure | Result |
|---|---|
| Abstracts read | 200 of 12,408 primary records (1.6%) |
| Abstracts with no qualifying claim | 99 (50%) |
| Claims kept | 209 |
| Claims rejected for being outside a Sjögren's context | 2 |
| Null results | 26 |
| Entities without an ontology match | 49% |
| Edges in the disease core, collapsed | 175, of which 135 rest on human evidence |
| Published stratifications captured | 2 |

| Evidence model | Claims |
|---|---|
| Human | 165 |
| Animal | 31 |
| In vitro | 10 |
| Secondary SjD | 3 |

## Predicates in use

`altered_in` (66), `associated_with` (38), `affects` (30), `biomarker_for` (18), `regulates` (14), `increases_likelihood_of` (8), `has_member` (8), `correlated_with` (8), `gene_associated_with_condition` (7), `contributes_to` (4), `decreases_likelihood_of` (3), and one each of `expressed_in`, `studied_to_treat`, `has_phenotype`, `located_in` and `manifestation_of`.

Seven predicates were never used. Under the 70% rule in ADR-0004, a predicate with too few claims cannot be assessed, so the list may need pruning. `treats` was never used, because abstracts report effects on endpoints.

## What the set shows

- **Half the corpus yields nothing.** Causes include passing mentions, other diseases, and reviews or opinion pieces that PubMed does not tag as such. The filter on publication type is not enough on its own.
- **The graph is sparse so far.** Almost every claim connects directly to the disease, and only one claim group has support from more than one publication. No contradiction was found. Paths between concepts mostly run through the disease node, which limits what the temporal test could show at this size.
- **Most unmatched entities are measures.** 40 of 45 clinical endpoints have local identifiers, such as tear production or fat fraction. Genes and cell types mostly resolve (43 of 48, and 11 of 13).
- **Older abstracts are thin.** Many report descriptive findings with no molecular content.

## Risks found

- **PubMed tags can mislead.** PMID 8194411 is tagged as a randomised trial but compares a sialography technique, so its claim gets the `randomised_trial` evidence level. Evidence levels need checking.
- **Systematic reviews can slip through.** PMID 30871019 describes a systematic review but is not tagged as one.
- **"Sicca syndrome" can mislead.** MONDO lists it as an exact synonym of Sjögren syndrome, but some abstracts use it for sicca without Sjögren's. In PMID 9041352, for example, "SS" means sicca syndrome in HTLV-I infection.
- **Sjögren's-like models are a judgement call.** Lupus-prone mice and induced models are often described as resembling the disease. They were included as `animal` evidence, which the expert should review.
- **One reader.** A single reader made every extraction, relevance and category decision.

## Scale

At this yield, the full corpus would give roughly 13,000 claims. That figure assumes the development set is typical, and it is only an extrapolation. About 12,200 abstracts remain.
