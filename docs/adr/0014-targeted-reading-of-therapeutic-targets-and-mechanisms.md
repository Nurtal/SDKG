# Read abstracts on therapeutic targets and mechanisms first

Reading all 12,408 abstracts in sessions is far off, and the development set showed that random reading gives a very flat graph. The project lead therefore chose targeted reading: abstracts that match a published keyword list on therapeutic targets and mechanisms (`topics/therapeutic-targets-and-mechanisms.txt`) are read first, in a reproducible random order within that list.

## Consequences

- **Not representative:** the graph over-represents this topic and is not a sample of the Sjögren's literature. It cannot support statements about the relative importance of topics, such as how much evidence exists for one mechanism compared with others outside the list.
- **Selection by keyword:** the list decides what is read, so a mechanism it omits is under-represented. Each release must publish the list, the number of matching abstracts, and how many were read.
- **Measures apply to what was read:** precision and recall from the test sample describe the targeted subset only, not the whole corpus. The test sample must be drawn from an evaluation-only build, excluding the development set.
- **Prompt frozen without a precision measure:** `extract-v3` is frozen in `pipeline/prompt-freeze.json` without the human judgement on the development set that ADR-0004 expects before freezing. If a human review later shows it performs poorly, the frozen prompt must be replaced and the affected abstracts read again.
- **Temporal test:** the keyword list was written with knowledge of recent literature, including drug names, so it could favour relationships published later. A temporal test on this subset must disclose this.
