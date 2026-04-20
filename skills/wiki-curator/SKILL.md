---
name: wiki-curator
description: >
  Use this skill to build or update the research wiki from newly-ingested raw
  sources following the Karpathy LLM Wiki pattern, one page per source file.
  Read the template from AGENTS.md and produce `research/wiki/<source_stem>.md`
  for every entry in `research/raw/_index.json` with status "pending", update
  `research/wiki/index.md`, flag contradictions (flag only, no merging), then
  flip status to "curated". Triggers include "curate", "build wiki",
  "compile wiki", "update the wiki", "after ingest".
---

# wiki-curator

## Goal
Turn normalised raw sources into a compound, navigable knowledge base. The wiki is the retrieval layer for thesis writing — quality here determines drafting quality downstream.

## Procedure (follow exactly)

1. Read `research/raw/_index.json`. Collect every entry with `status == "pending"`.
2. For each pending entry, in order:
   a. Read the raw normalised markdown at `research/raw/<entry.filename>`.
   b. Compose a wiki page at `research/wiki/<entry.filename>.md` (same stem + `.md`), following the template in AGENTS.md verbatim. Required sections: frontmatter (source, title, authors, date, tags), Summary, Key claims, Methods/datasets (if empirical), Key terms, See also, Conflicts.
   c. Every claim on the page MUST carry `[src:<entry.orig>]`.
   d. Update `research/wiki/index.md`: add a line under the appropriate topic tag cluster pointing to the new page (`- [[<stem>]] — <one-line teaser>`). Create the cluster if it doesn't exist yet.
   e. Contradiction check: for each key claim, glob existing `research/wiki/*.md` and check if any previously-curated page asserts a conflicting claim on the same topic. If so, append `- ⚠ conflicts with [[<other_stem>]] on <topic>` to the `Conflicts` section of BOTH pages. Flag only — do not quote sides, do not merge.
   f. Update `research/raw/_index.json`: set `entry.status = "curated"` and append `<entry.filename>.md` to `entry.curated_pages`.
3. After all pending entries are processed, write a one-line summary to the user: `curated N sources (M conflicts flagged, K cross-refs added)`.

## Tagging guidance
Tags should be short (1-2 words), lowercase, domain-specific. Reuse existing tags from `index.md` when possible; add new ones sparingly. Aim for 3–8 tags per page.

## Cross-references (`See also`)
Add a cross-reference when two sources discuss the same entity, method, or claim. Cross-references must be reciprocal: edit BOTH pages.

## What NOT to do
- Do NOT write to `research/raw/**`. Those files are immutable.
- Do NOT merge conflicting pages. Flag and move on; the user resolves.
- Do NOT invent authors, dates, or tags not supported by the source.
- Do NOT skip the status flip — the manifest is how the user knows curation is done.
