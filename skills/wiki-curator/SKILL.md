---
name: wiki-curator
description: >
  Use this skill to curate newly-ingested raw sources into the LLM Wiki
  following AGENTS.md. A single ingest must touch multiple pages —
  create/update the source-summary page, every relevant entity page,
  every relevant concept page, update `index.md`, append to `log.md`,
  flag contradictions, and flip the manifest status. One source typically
  touches 5-15 pages. Triggers include "curate", "build wiki",
  "compile wiki", "ingest into wiki", "update the wiki", "after ingest".
---

# wiki-curator

## Goal
Turn normalised raw sources into a persistent, compounding knowledge base
per the Karpathy LLM Wiki pattern. **The knowledge must accumulate across
entity and concept pages — not sit in isolated one-per-source pages.**

## Procedure (follow for every pending source)

1. Read `research/raw/_index.json`. Collect entries where `status == "pending"`.

2. For each pending entry, read the raw normalised markdown at
   `research/raw/<entry.filename>`.

3. **Write the source-summary page** at
   `research/wiki/sources/<entry.filename>.md` following the AGENTS.md
   page template. Sections: frontmatter, Summary, Key claims, Methods/datasets,
   Key terms, See also, Conflicts. Every claim cites `[src:<entry.orig>]`.

4. **Identify entities** in the source: named people, specific methods,
   datasets, well-defined concepts, tools, systems. For each:
   - Use `read_file` on `research/wiki/entities/<slug>.md` (via `ls` first to
     check existence).
   - If the page exists, **extend it**: use `edit_file` to append new claims
     from this source, each carrying `[src:<entry.orig>]`. Add a reciprocal
     `See also: [[sources/<entry.filename>]]` link.
   - If it doesn't exist, **create it** with the new claims as seed content.
     Include a `See also: [[sources/<entry.filename>]]` link back.

5. **Identify major themes/concepts** the source touches (usually 2-5).
   For each, same pattern as entities but under
   `research/wiki/concepts/<slug>.md`.

6. **Update `research/wiki/index.md`**:
   - Add the new source under its topic cluster.
   - List any new entity pages under `## Entities`.
   - List any new concept pages under `## Concepts`.
   - Preserve existing entries. Use `edit_file`.

7. **Check for contradictions**: for each new claim, glob existing
   entity/concept pages and `grep` for conflicting claims on the same topic.
   On match, add `⚠ conflicts with [[<other>]] on <topic>` to the `Conflicts`
   section of **both** pages. **Flag only** — do not quote both sides, do not
   merge.

8. **Append to `research/wiki/log.md`** using the exact grep-friendly prefix:
   ```
   ## [YYYY-MM-DD] ingest | <Source Title>
   - New pages: [[sources/…]], [[entities/…]], [[concepts/…]]
   - Updated pages: [[entities/…]] (+N claims), …
   - Conflicts flagged: N
   ```
   Use `edit_file` to append (read current log, add new entry at the end).

9. **Flip manifest status**: `edit_file` on `research/raw/_index.json` to
   change `"status": "pending"` to `"status": "curated"` for the entry, and
   populate `curated_pages` with the list of wiki pages you touched for that
   source.

10. After all pending entries processed, report:
    `curated N sources, touched M pages, flagged K conflicts, suggested J questions`.

## What a good ingest looks like

For a single paper on, say, "attention mechanisms in transformers":
- 1 source page: `sources/attention-is-all-you-need.pdf.md`
- 3-5 entity pages (created or updated): `entities/transformer-architecture.md`,
  `entities/self-attention.md`, `entities/multi-head-attention.md`,
  `entities/vaswani.md` (author), `entities/machine-translation.md`
- 1-2 concept pages: `concepts/attention-mechanisms.md`,
  `concepts/sequence-to-sequence-models.md`
- `index.md` (updated)
- `log.md` (appended)

**Total: 7-10 pages touched.** If you only wrote 1-2 pages, you're not
building a wiki — you're making isolated summaries.

## Slug convention (AGENTS.md §Slug)

`<lowercase-kebab-case>`, under 60 chars, strip punctuation. Examples:
- "Self-Supervised Learning" → `self-supervised-learning`
- "GPT-4" → `gpt-4`

## What NOT to do

- Do NOT write to `research/raw/**` (sources are immutable). The exception is
  updating `research/raw/_index.json` via `edit_file`.
- Do NOT use `write_file` to overwrite an existing wiki page. It will refuse.
  Use `edit_file` for in-place updates.
- Do NOT merge conflicting claims. Flag on both pages and move on.
- Do NOT invent authors, dates, or tags not supported by the source.
- Do NOT stop after the source page. The value of this pattern is that
  entity and concept pages compound — that's what the wiki is for.
- Do NOT skip the `log.md` append. Every ingest must leave a chronological
  trace.

## Reciprocal cross-refs

When you add `See also: [[X]]` on page A, also add `See also: [[A]]` on page
X. Use `edit_file` on both. This is not optional — the graph breaks otherwise.
