# Separate the disease core from the background layer

Importing general biology wholesale would make almost any target look connected to SjD, while keeping only SjD-specific claims would prevent inference across gaps in the literature. We therefore keep a disease core, in which every claim has evidence from an SjD context, and a background layer limited to 1–2 hops from core entities and high-confidence edges. Every edge carries its layer, so that analyses can filter on it and paths through general biology are never mistaken for SjD evidence.
