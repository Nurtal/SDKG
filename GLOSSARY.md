# SDKG

The vocabulary used to describe a knowledge graph of Sjögren's disease in which every relationship is a sourced claim.

## Language

### Disease and population

**Sjögren's disease (SjD)**:
The disease this graph describes.
_Avoid_: Sjögren-Larsson syndrome (an unrelated disease)

**Primary SjD**:
SjD occurring without an associated systemic autoimmune disease; the population at the centre of v1.
_Avoid_: Idiopathic SjD

**Secondary SjD**:
SjD occurring alongside another systemic autoimmune disease, such as lupus or rheumatoid arthritis.
_Avoid_: Overlap SjD

**Published stratification**:
A grouping of SjD patients proposed in a publication and represented in the graph as an entity, with the source's own definition.
_Avoid_: Discovered endotype, SDKG endotype

### Claims and evidence

**Claim**:
A statement that a given source asserts a relationship between two entities in a given context. The claim, not the relationship, is the fundamental unit of the graph.
_Avoid_: Fact, edge, triple

**Evidence span**:
The exact passage of a source that a claim rests on.
_Avoid_: Citation, snippet

**Context**:
The conditions under which a claim was made, including species, tissue, patient subgroup and assay.
_Avoid_: Metadata

**Null result**:
A claim that a source tested a relationship and did not find it.
_Avoid_: Absence of evidence

**Contradiction**:
Two claims about the same subject and object, in compatible contexts, with opposite signs.
_Avoid_: Disagreement, conflict

**Support**:
The number of distinct publications behind an aggregated claim.
_Avoid_: Independent sources, replication count

### Layers

**Disease core**:
The layer of claims with evidence from an SjD context.
_Avoid_: Sjögren subgraph

**Background layer**:
General biology that is not specific to SjD, imported only to connect entities in the disease core.
_Avoid_: Interactome, context layer

### Quality

**Claim status**:
How a claim entered the graph and whether a human has checked it: curated-source, AI-extracted or human-reviewed.
_Avoid_: Curated, validated (as generic labels)

**Extraction reliability**:
The estimated probability, for a given predicate, that an AI-extracted claim is supported by its evidence span and correctly mapped to its entities.
_Avoid_: Confidence score, truth probability

**Evidence level**:
An ordinal grade of how strong the underlying study is, based on study type and context.
_Avoid_: Confidence

**Development set**:
The documents used to adjust the extraction prompt, which are never used to report final performance.
_Avoid_: Training set, pilot set

**Test sample**:
The random sample of claims drawn after the prompt is frozen and judged by human reviewers.
_Avoid_: Validation set, gold standard

**Competency question**:
A question the graph must be able to answer, used to decide what belongs in a release.
_Avoid_: Use case, requirement

**Held-out associations**:
Open Targets SjD associations kept out of the disease core and reserved for evaluation.
_Avoid_: Ground truth

### Outputs

**Canonical tables**:
The complete representation of a release from which every export is derived.
_Avoid_: Database, master graph

**Lossless export**:
An export that keeps the full claim structure.
_Avoid_: Full graph

**Collapsed export**:
A simplified graph in which claims are merged into edges according to published rules.
_Avoid_: The graph, simple graph

**Release**:
A dated, citable version of the graph, with a report of what changed.
_Avoid_: Snapshot, dump
