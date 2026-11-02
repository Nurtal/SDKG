"use strict";

const byId = (id) => document.getElementById(id);
let entities = [];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function humanise(value) {
  return String(value).replaceAll("_", " ");
}

function sourceLink(pmid) {
  // Only numeric PMIDs become links, so extracted data cannot choose an address.
  if (!/^\d+$/.test(pmid)) return element("span", pmid);
  const link = element("a", `PMID ${pmid}`);
  link.href = `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
  link.rel = "noopener noreferrer";
  return link;
}

function renderClaim(claim) {
  const box = element("div", null, "claim");
  box.append(element("span", humanise(claim.layer), `tag ${claim.layer}`));
  box.append(element("span", humanise(claim.claim_status), "tag"));
  if (claim.negated) box.append(element("span", "null result", "tag"));
  if (claim.sign) box.append(element("span", claim.sign, "tag"));
  if (claim.span_text) box.append(element("p", claim.span_text, "span"));

  const details = element("dl");
  const add = (term, value) => {
    if (value === null || value === undefined || value === "") return;
    details.append(element("dt", term));
    const description = element("dd");
    description.append(value instanceof Node ? value : document.createTextNode(humanise(value)));
    details.append(description);
  };
  add("Source", claim.pmid ? sourceLink(claim.pmid) : claim.source);
  add("Evidence level", claim.evidence_level);
  add("Extraction reliability", claim.extraction_reliability);
  for (const field of ["species", "tissue", "population", "assay", "evidence_model", "trial_phase", "trial_status", "endpoint"]) {
    add(humanise(field), claim[field]);
  }
  box.append(details);
  return box;
}

async function showEntity(entry) {
  const section = byId("entity");
  section.hidden = false;
  section.replaceChildren(element("p", "Loading…", "meta"));
  let page;
  try {
    const response = await fetch(`data/entities/${entry.file}`);
    if (!response.ok) throw new Error(`${response.status}`);
    page = await response.json();
  } catch (error) {
    section.replaceChildren(element("p", "This entity could not be loaded. Try again."));
    return;
  }
  const heading = element("h2", page.label);
  heading.tabIndex = -1;
  section.replaceChildren(heading, element("p", `${page.id} · ${humanise(page.category)}`, "id"));
  if (!page.resolved) section.append(element("p", "This concept has no ontology match yet and uses a local identifier."));
  if (!page.relationships.length) section.append(element("p", "No relationships are recorded."));
  for (const relation of page.relationships) {
    const arrow = relation.direction === "out"
      ? `${page.label} — ${humanise(relation.predicate)} → ${relation.other.label}`
      : `${relation.other.label} — ${humanise(relation.predicate)} → ${page.label}`;
    section.append(element("h3", arrow));
    for (const claim of relation.claims) section.append(renderClaim(claim));
  }
  heading.focus();
}

function search(term) {
  const list = byId("results");
  const query = term.trim().toLowerCase();
  list.replaceChildren();
  if (!query) {
    byId("status").textContent = "";
    return;
  }
  const matches = entities.filter((e) => e.label.toLowerCase().includes(query) || e.id.toLowerCase().includes(query));
  matches.sort((a, b) => b.claims - a.claims || a.label.localeCompare(b.label));
  byId("status").textContent = matches.length ? `${matches.length} found` : "No matching entity";
  for (const entry of matches.slice(0, 50)) {
    const item = element("li");
    const button = element("button");
    button.type = "button";
    button.append(element("span", entry.label), document.createTextNode(" "), element("span", `${entry.id} · ${entry.claims} ${entry.claims === 1 ? "claim" : "claims"}`, "id"));
    button.addEventListener("click", () => showEntity(entry));
    item.append(button);
    list.append(item);
  }
}

function renderRelease(release) {
  if (release.data_notice) {
    byId("data-notice").textContent = release.data_notice;
    byId("data-notice").hidden = false;
  }
  byId("meta").textContent = `Version ${release.version} · ${release.claims} claims · ${release.entities} entities`;
  const downloads = byId("downloads");
  if (release.downloads.url) {
    const link = element("a", "Get the versioned release");
    link.href = release.downloads.url;
    downloads.append(link);
  } else {
    const list = element("ul");
    for (const file of release.downloads.files) {
      const item = element("li");
      const link = element("a", file);
      link.href = `downloads/${file}`;
      item.append(link);
      list.append(item);
    }
    downloads.append(list);
  }
}

async function start() {
  try {
    const [index, release] = await Promise.all([
      fetch("data/index.json").then((r) => r.json()),
      fetch("data/release.json").then((r) => r.json()),
    ]);
    entities = index.entities;
    renderRelease(release);
    byId("search").addEventListener("input", (event) => search(event.target.value));
  } catch (error) {
    byId("status").textContent = "The graph data could not be loaded.";
  }
}

start();
