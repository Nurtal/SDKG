# Take open modelling decisions without an expert, by delegation

The project lead asked Claude to answer the open expert questions so that work could continue without waiting for a domain expert. These decisions are provisional and are **not expert validation**. They must not be described as validated in the paper, and an expert can overturn any of them.

1. **MONDO or HPO:** when a name is shared, the category assigned at extraction decides, because a name such as `lymphoma` can be a disease in one abstract and a finding in another. Common clinical findings in Sjögren's disease are curated to HPO, such as thrombocytopenia and keratoconjunctivitis sicca, because there they are manifestations.
2. **Disease core:** a literature claim must be marked by extraction as observed in Sjögren's disease patients, samples or models (`sjd_context`). Other claims are rejected and counted, because the disease core must not depend on screening alone.
3. **Unmatched concepts:** a local identifier is acceptable, and the concept is listed for review. No curated list of measures is added before the pilot shows which are frequent.
4. **Complexes:** dimeric cytokines such as IL-35 get a local identifier, because mapping them to one gene would be false. Their components can be linked later.
5. **Trial identifiers:** claims can carry a `trial_id`, kept only if it appears in the abstract, so that a model cannot add an identifier the source does not contain.

## What this does not replace

Delegation cannot supply independent human judgement, and Claude is also the extractor. These stay human, and issue #9 stays open for them:

- Reference answers to the competency questions, written before the graph is queried
- Validation of the competency questions and the final schema
- The human review, double review and recall annotation in ADR-0004

The paper's claims should be weakened if an expert never validates the schema.
