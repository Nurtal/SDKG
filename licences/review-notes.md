# Licence review notes

**These notes are preparation for the legal review in issue #4. They are not legal advice, and no source is confirmed by them.** Every source stays `unconfirmed` in the manifest until a person with the authority to decide has reviewed it.

The terms below were read on 2026-11-02. Check them again before relying on them, because they can change.

The planned release licence is CC BY 4.0 (ADR-0006).

## Terms by source

| Source | Terms observed | Possible issue for a CC BY 4.0 release |
|---|---|---|
| ChEMBL | CC BY-SA 3.0 Unported | **Likely conflict.** See question 1 |
| HPO, including annotations | Custom terms. Free use on three conditions: acknowledgement and citation, showing file dates or versions in public displays, and no alteration of content or logical relationships. Products must display an acknowledgement | **Needs review.** See question 2 |
| PubMed abstracts | NLM provides no legal advice on copyright, and abstracts may remain under publisher copyright | **Needs review.** See question 3 |
| PMC open-access articles | Licence varies per article | Handled per article, and only compatible licences are allowed |
| ClinicalTrials.gov | Not read, because the terms page did not return readable text | **Needs reading** |
| HGNC | Free to use, with a request to reference HGNC and its website | Low, but no formal licence is named |
| UBERON | CC BY 3.0, per the OBO Foundry registry | Low. Attribution needed |
| UniProt | CC BY 4.0 for copyrightable parts. Warns that some data may be covered by patents or other rights | Low. Attribution needed |
| MONDO, CL, ChEBI | CC BY 4.0, per the OBO Foundry registry | Low. Attribution needed |
| GO | CC BY 4.0 | Low. Attribution needed |
| Reactome | Data under CC0. Illustrations and branding under CC BY 4.0. Only the data would be used | Low |
| Open Targets | Data marked CC0 1.0, and citation requested | Low |

Where terms come from the OBO Foundry registry, the ontology's own repository should also be checked.

## Questions for the reviewer

1. **ChEMBL.** ShareAlike normally requires adapted material to keep a compatible licence. Can drug-target claims from ChEMBL be part of a CC BY 4.0 release? If not, which of these options is acceptable?
   - Leave ChEMBL out of the main release.
   - Publish ChEMBL-derived claims as a separate CC BY-SA add-on. This is the current recommendation, because it keeps the main release simple and users can still join the add-on themselves.
   - Release the whole graph under CC BY-SA, which would reverse ADR-0006.

   Also: can ChEMBL names and identifiers be used in the lexicon if only identifiers reach the release?

2. **HPO.** Is mapping HPO annotations into SDKG claims an alteration of "content or logical relationships"? Can a CC BY 4.0 release include them, or must they be redistributed under HPO's own terms? The release would need to show HPO versions and an acknowledgement in any case.

3. **Abstracts.** Can short evidence spans from abstracts under publisher copyright be published? Can raw LLM outputs containing such text be archived publicly? The default is that neither happens: releases publish only the PMID and offsets.

4. **Facts and claims.** Are claims extracted from abstracts, without quoted text, free of the abstracts' copyright? The whole project relies on this, so it should be confirmed explicitly.

5. **EU database right.** Does extracting and republishing substantial parts of a database raise a separate issue under the EU sui generis database right, given that the project may be based in the EU? This also applies to the release itself, which should state how CC BY 4.0 covers it.

6. **Attribution.** What form of attribution does each source need in the release, on the website and in the paper?

## Before a source can be marked `allowed`

- The reviewer's decision is recorded with its date and the terms version that was reviewed.
- Its `status` in the manifest changes to `allowed`, and its `licence` field is filled in.
- Any attribution requirement is added to the release's attribution file.
