# Competency questions

**Status: draft v0, awaiting validation by the domain expert.** Named biology below is illustrative, drawn from general knowledge and not yet checked against sources. None of it is a graph result or a reference answer.

A v1 element belongs in the graph only if it helps answer one of these questions.

## How to use this list

Before the graph is queried, the expert should:

1. Keep, edit, remove or add questions. The aim is 15–25.
2. Write down a reference answer for each question that has a checkable answer.
3. Mark each question as **must** or **should**.

Questions marked "Exploratory" have no single right answer, so the expert judges whether the output is useful and traceable.

## Questions

The **Layer** column shows what a question needs: **Core** (disease core), **Background** (background layer) or **Both**.

### Molecular mechanisms

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ01 | Which genes have human genetic association evidence in SjD (such as HLA class II, IRF5, STAT4), and in which ancestry or cohort? | Core | Gene, variant, population context | Checkable |
| CQ02 | Which pathways are reported as dysregulated in SjD, in which tissue, and by which assay? | Core | Pathway, tissue, assay, sign | Checkable |
| CQ03 | Which claims support or contradict the involvement of type I interferon signalling, and do they differ by tissue or patient subgroup? | Core | Sign, context, contradictions | Checkable |
| CQ04 | Which paths connect a given genetic risk gene to a given clinical manifestation, and which steps rest on SjD evidence and which on general biology? | Both | Layer flag, direction, directness | Exploratory |

### Cells and tissues

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ05 | Which cell types are reported as altered in salivary gland tissue and in blood, and in which direction? | Core | Cell type, tissue, sign | Checkable |
| CQ06 | What is claimed about the role of salivary gland epithelial cells, and how much of it comes from human tissue rather than cell lines or animal models? | Core | Evidence model tag, cell type | Checkable |
| CQ07 | What evidence links ectopic germinal centres to clinical outcomes, including lymphoma? | Core | Tissue structure, outcome, evidence level | Checkable |

### Clinical manifestations

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ08 | Which molecular or cellular entities are linked to each ESSDAI domain? | Core | Clinical score domain, phenotype | Exploratory |
| CQ09 | Which mechanisms are proposed for fatigue and pain, and how does their evidence compare with that for glandular and systemic manifestations? | Core | Phenotype, evidence level, support | Exploratory |
| CQ10 | What are the reported risk factors for lymphoma in SjD, and in what type of study was each identified? | Core | Risk relation, study type | Checkable |

### Biomarkers

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ11 | Which biomarkers are reported for diagnosis, activity, prognosis and treatment response, respectively? | Core | Biomarker role, sample type | Checkable |
| CQ12 | Which biomarkers are linked to extraglandular manifestations, and through which pathways? | Both | Biomarker, phenotype, pathway | Exploratory |
| CQ13 | What clinical and molecular features are associated with anti-SSA/Ro and anti-SSB/La positivity? | Core | Autoantibody, phenotype, sign | Checkable |

### Therapeutic targets

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ14 | Which therapeutic targets have both human genetic and tissue-level evidence in SjD? | Core | Target, evidence type | Checkable |
| CQ15 | Which interventions have been tested in SjD trials, against which target and endpoint, and with what outcome, including failures (such as rituximab and abatacept)? | Core | Drug, target, trial, endpoint, null result | Checkable |
| CQ16 | For failed or mixed trials, what does the graph show about the target's mechanistic evidence, and do any patient subgroups show a different response? | Core | Null result, subgroup context | Exploratory |
| CQ17 | Which approved or investigational drugs act on pathways implicated in SjD but have no recorded SjD trial? | Both | Drug, target, pathway, trial | Exploratory |

### Stratification

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ18 | Which patient stratifications have been published (such as Tarn 2019 and Soret 2021), and what data and features define each one? | Core | Published stratification, cohort, features | Checkable |
| CQ19 | Which pathways, biomarkers and targets are associated with each subgroup of a published stratification? | Core | Subgroup, pathway, target | Checkable |
| CQ20 | Which features could be applied to an external cohort to assign patients to a published stratification? | Core | Features, measurability | Exploratory |

### Evidence quality

| ID | Question | Layer | Requires | Type |
|---|---|---|---|---|
| CQ21 | For a given claim, what are the sources, passages, context, status and evidence level? | Core | Claim, evidence span, quality fields | Checkable |
| CQ22 | Which relationships have contradictory claims in compatible contexts, and how could those contexts explain the disagreement? | Core | Contradiction, context | Exploratory |
| CQ23 | Which SjD claims rest only on animal or in vitro evidence, with no human evidence? | Core | Evidence model tag | Checkable |

## Proposed vocabulary

The entity types and predicates are now proposed in the [schema](../schema/sdkg.yaml), each traced to these questions and checked against Biolink Model 4.4.6. The expert reviews them alongside the questions. These choices need the most attention:

- **Regulation:** `regulates` plus a sign replaces `increases`, `decreases`, `activates` and `inhibits`. Biolink has deprecated its directional predicates.
- **Null results:** these use a `negated` property on any claim, replacing `no_effect_on`.
- **Biomarker roles:** these use a `biomarker_role` property on `biomarker_for` claims.
- **Biolink gaps:** `altered_in`, `drug_acts_on` and `characterised_by` have no exact Biolink predicate, so they use close mappings.
- **Evidence levels:** the grades and their rule are proposals.

## Questions deliberately excluded from v1

- **Patient-level analysis:** "Which endotype does this patient belong to?"
- **Causal validation:** "Is this mechanism truly causal?" The graph reports what sources claim.
- **Treatment advice:** "Which treatment should this patient receive?" SDKG is not a clinical decision tool.
