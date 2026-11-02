# Extract with an LLM and validate by sampling, not full curation

Reviewing every claim is not feasible with the available expert time, so v1 literature claims are extracted by `claude-opus-5-5` and quality is estimated on a human-reviewed random sample. The graph must therefore be described as "AI-extracted, with an estimated precision of X%", not as curated. Full curation may follow if resources allow.

Sampling is only defensible under these rules:

- Any claim without a verifiable evidence span is rejected.
- The prompt is adjusted only on a development set, then frozen before the test sample is drawn.
- The test sample has about 400 claims, stratified by predicate. Reviewers do not see the model's scores and judge whether the span supports the claim and whether the entities are correctly mapped, not whether the claim is biologically true.
- About 100 claims are reviewed by a second human, to give the human-AI agreement a baseline. The second reviewer cannot be replaced by another AI pass, and is required before paper submission.
- About 50 abstracts are fully annotated by a human to measure recall, which the sample cannot measure.
- A predicate whose precision stays below 70% after tuning is removed or marked experimental. The expert may adjust this threshold, but it must be set before the final test.
- The protocol is preregistered, and LLM use is declared in the paper.
