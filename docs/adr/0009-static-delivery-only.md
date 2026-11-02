# Deliver statically, with no live query server

GitHub Pages serves only static files, and a live query server would need funding and maintenance beyond any grant. We therefore deliver versioned bulk exports with Zenodo DOIs, plus precomputed JSON for each entity. Complex graph queries run offline on the downloaded data. Subgraph extraction moves from the web interface, as first proposed, to a Python package and notebooks, because the graph is the deliverable and the website is secondary. A live SPARQL endpoint remains an optional later addition.
