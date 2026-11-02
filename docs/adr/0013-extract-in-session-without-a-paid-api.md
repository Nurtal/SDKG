# Extract in a Claude Code session, without a paid API

The project lead decided not to use a paid API, after a paid run was started without an explicit go-ahead. Literature claims are therefore extracted by Claude reading abstracts in Claude Code sessions, and archived with `sdkg import-session`. This replaces the batch API in ADR-0004, and the command-line options that called the API have been removed, so the pipeline cannot spend money by accident. The unused client code remains in `batch.py`.

The rest of ADR-0004 and ADR-0007 still applies: claims need a verifiable evidence span, the prompt is frozen before the test sample is drawn, human review is required, and releases are rebuilt from archived outputs.

## Consequences

- **Scale:** a session reads far fewer abstracts than a batch run, so the full corpus takes many sessions. A release must state how much of the corpus was read and in what order. [ADR-0014](0014-targeted-reading-of-therapeutic-targets-and-mechanisms.md) later chose targeted reading, so a partial corpus is not a sample of the whole.
- **Consistency:** the reader's context varies between sessions and cannot be pinned as a batch run could, which the paper must disclose. The archive records `claude-code-session` as the model version.
- **Independence:** Claude reads every abstract and has also taken modelling decisions (ADR-0012), which makes independent human review more important.
