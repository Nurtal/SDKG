# Claims are the fundamental unit of the graph

An evidence-based resource must represent that a source asserted a relationship in a given context, including null results and contradictions. We therefore store each relationship as a claim linked to its evidence, and derive plain graphs by collapsing claims. This is harder to build than a plain graph, but it would be very costly to retrofit. Simple formats such as GraphML are therefore lossy by design, and must not be treated as the source of truth.
