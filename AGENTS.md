# AGENTS.md — Thesis Agent Schema

This file is loaded into every agent run as the operating schema. It implements
the Karpathy **LLM Wiki** pattern for the thesis-writing domain: a persistent,
compounding knowledge base the LLM builds and maintains in `research/wiki/`,
used to ground every line of thesis prose.

Read this completely. Follow it exactly.

---

## Three layers

1. **`research/raw/`** — immutable source material (PDFs, DOCX, EPUB, MD, URLs).
   Never edited by the agent. The `thesis ingest` CLI normalises each file to
   `research/raw/<filename>.md` alongside the original, and records it in
   `research/raw/_index.json` with `status: pending`.

2. **`research/wiki/`** — the LLM-owned knowledge base. A directory of
   cross-linked markdown pages. **You write and maintain all of this.** The
   user reads it; you don't ask for permission to update it.

3. **This file (`AGENTS.md`)** — the schema. You and the user co-evolve it as
   the thesis grows.

The wiki is the retrieval layer. **There is no vector search, no embeddings,
no RAG.** Navigate with `read_file`, `ls`, `glob`, `grep`. The
`research/wiki/index.md` catalog is your index; drill from there.

---

## Page types

Every ingest touches **multiple pages** across several categories. A single
source typically produces edits in 5-15 pages. These are the categories you
will create and maintain:

### A. Source summary pages (one per raw file)
Filename: `research/wiki/sources/<raw_filename>.md` (matching the raw file's
name). One per source. Captures what a single source says.

### B. Entity pages (one per concept/person/method/dataset)
Filename: `research/wiki/entities/<entity-slug>.md`. Example:
`research/wiki/entities/transformer-architecture.md`. Accretes what multiple
sources say about the same thing. This is where the synthesis compounds —
an entity page for a well-studied concept may reference 5-20 sources.

### C. Concept / theme pages (higher-level synthesis)
Filename: `research/wiki/concepts/<concept-slug>.md`. Example:
`research/wiki/concepts/attention-mechanisms.md`. Ties together multiple
entities into a coherent theme. Thesis chapters usually map ~1:1 with concept
pages.

### D. Query / synthesis pages (answers to user questions, filed back)
Filename: `research/wiki/queries/<YYYY-MM-DD>-<slug>.md`. When the user asks a
substantial question and you do real research to answer it, file the answer
back into the wiki as a new query page so the reasoning doesn't disappear
into chat history.

### E. Index and log (special pages — see below)
- `research/wiki/index.md` — content catalog
- `research/wiki/log.md` — chronological record

---

## Page template

Every source / entity / concept / query page follows this template:

```markdown
---
title: <human-readable title>
type: source | entity | concept | query
tags: [short, lowercase, 3-8 tags]
sources: [<raw_filename>, ...]          # for entity/concept pages
source: <raw_filename>                  # for source-summary pages only
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# <title>

## Summary
3-5 sentences. Every factual sentence cites: `[src:<raw_filename>]`.

## Key claims
- Claim. [src:<filename>]
- Claim. [src:<filename>]
(5-15 bullets for source pages; 10-40 for entity/concept pages that have
 accreted from multiple sources.)

## Methods / datasets          (if relevant — empirical work)
- <name>: <one-line description>. [src:<file>]

## Key terms                    (if relevant)
- <term>: <definition as used here>. [src:<file>]

## See also
- [[<other-page-slug>]] — <one-line reason for the link>
(Reciprocal: when you add a link here, add a reciprocal link on the
 target page too.)

## Conflicts                    (flag only — do NOT resolve or merge)
- ⚠ conflicts with [[<other-page-slug>]] on <topic>
```

---

## Citation format

Any factual claim — on a wiki page, in a thesis chapter, in chat — carries
`[src:<raw_filename>]` where `<raw_filename>` names a file in
`research/raw/`. Example: `[src:attention-is-all-you-need.pdf]`.

Never invent a citation. If no source supports a claim, reply:
**"no grounding in indexed sources — add material or remove claim."**
No pretraining facts. No web. You have no web tool anyway.

---

## `index.md` — the content catalog

`research/wiki/index.md` is the content-oriented directory of the wiki. Not
chronological. Organised by category. Read this first when answering a query;
drill into relevant pages from here.

Required structure:

```markdown
# Wiki Index

## Concepts
- [[concepts/<slug>]] — one-line description
- ...

## Entities
- [[entities/<slug>]] — one-line description
- ...

## Sources                      (grouped by topic, not by order of ingest)
### Topic: <tag>
- [[sources/<filename>]] — one-line teaser
...

## Queries                      (filed-back user questions)
- [[queries/YYYY-MM-DD-<slug>]] — question, one-line answer
...
```

You update `index.md` on every ingest and every filed-back query.

---

## `log.md` — the chronological record

`research/wiki/log.md` is append-only. Every ingest, substantial query, and
lint pass appends one entry. Entries use this exact prefix so the log is
grep-able:

```markdown
## [YYYY-MM-DD] ingest | <Source Title>
- New pages: [[sources/...]], [[entities/...]], [[concepts/...]]
- Updated pages: [[entities/...]] (2 new claims), [[concepts/...]] (cross-ref)
- Conflicts flagged: 0

## [YYYY-MM-DD] query | <User's question>
- Filed: [[queries/YYYY-MM-DD-<slug>]]
- Pages read: [[...]], [[...]]

## [YYYY-MM-DD] lint | pass <N>
- Orphans fixed: 2
- Stale claims marked: 1
- Missing cross-refs added: 5
- New questions suggested: 3 (see queries/YYYY-MM-DD-lint-followups.md)
```

Date format: `YYYY-MM-DD`. `grep "^## \[" log.md | tail -5` must give the last
5 entries — preserve the prefix exactly.

---

## Workflows

### Ingest (triggered by `thesis curate` or user request after `thesis ingest`)

For each entry in `research/raw/_index.json` with `status == "pending"`:

1. Read the raw normalised markdown at `research/raw/<entry.filename>`.
2. **Create the source-summary page** at `research/wiki/sources/<entry.filename>.md`
   following the template.
3. **For each entity** mentioned in the source (people, methods, datasets,
   defined concepts):
   - If `research/wiki/entities/<slug>.md` exists, read it and append the new
     claims from this source with `[src:...]` citations. Add a reciprocal
     `See also` link back to the source page.
   - If it doesn't exist, create it with this source's contributions as the
     starting content.
4. **For each major theme/concept** the source touches:
   - Update or create `research/wiki/concepts/<slug>.md` the same way.
5. **Update `research/wiki/index.md`**: add the new source under the right
   topic cluster; list any new entity/concept pages under their sections.
6. **Check for contradictions** (flag-only): for each new claim, glob existing
   entity/concept pages for conflicting claims. On match, add
   `⚠ conflicts with [[<other>]] on <topic>` to BOTH pages' Conflicts section.
   Do **not** quote both sides; do **not** merge.
7. **Append a log entry** to `research/wiki/log.md` with the exact prefix
   `## [YYYY-MM-DD] ingest | <title>`. List new + updated pages + conflict
   count.
8. **Flip status** in `research/raw/_index.json` from `pending` to `curated`
   and list the wiki pages you produced in `curated_pages`.

A typical ingest for one substantive paper touches **5-15 pages**. For a
narrow source (a short note, a single-topic article) 2-3 pages is fine.
Report honestly what you did — do not retry or restart to hit a page
count. The goal is to let entities and concepts compound over time; one
thin ingest today gets enriched by the next related source.

### Query (chat requests that require real research — not just routine Q&A)

1. Read `research/wiki/index.md` to find relevant pages.
2. Read the relevant concept/entity/source pages.
3. Synthesise the answer with `[src:...]` citations.
4. **File the answer back.** If the question took non-trivial reasoning
   (comparisons, causal analysis, connections the user hadn't seen), write
   `research/wiki/queries/<YYYY-MM-DD>-<slug>.md` with the question at the
   top, your answer below, and links to the pages you consulted. Update
   `index.md` under Queries and append to `log.md`.
5. For trivial Q&A, answer in chat without filing back.

### Write (triggered by `thesis write <section>`)

1. Read `style/STYLE.md`. If missing, stop and ask the user to run
   `thesis style` first.
2. Read `research/wiki/index.md` → the relevant concept page → relevant
   entity pages → relevant source-summary pages → raw sources (only when
   a wiki page lacks the needed detail).
3. Delegate to the `drafter` subagent with:
   - Section identifier + outline excerpt.
   - List of wiki pages that will ground the draft.
   - A reminder to follow `STYLE.md`.
4. Drafter writes `thesis/chapters/<NN>.md`, every paragraph cites at least
   one `[src:...]`.

### Lint (triggered by `thesis lint` — wiki health check)

1. Scan `research/wiki/**` for:
   - **Contradictions** between pages (flagged `⚠` but unresolved)
   - **Stale claims**: entity-page bullets a newer source contradicts but
     which weren't marked as conflicted when ingested
   - **Orphan pages**: no inbound `[[...]]` links from any other page
   - **Missing cross-refs**: pages referencing the same entity without
     linking each other
   - **Missing pages**: entities/concepts mentioned in source summaries that
     don't have their own page yet
   - **Data gaps**: topics the wiki covers thinly that could use a web
     search (report — do not run one; you have no web tool)
2. Output a short, grouped, actionable report. Numbered items the user can
   act on one at a time.
3. Suggest 2-5 follow-up questions the user might ask next given the shape
   of the wiki.
4. Append a `lint` entry to `log.md` with counts.

### Citation lint (narrow — triggered by `thesis lint <FILE>`)

Legacy narrow linter: scan a thesis chapter for `[src:...]` markers,
verify targets exist, flag paragraphs with factual claims but no citation.
Report file + line numbers. Do not auto-edit.

---

## Write scopes (soft conventions)

The filesystem tools are scoped to the workspace root. Two hard rules
inside it:

- Never write to `research/raw/**` — sources are immutable; use
  `thesis ingest` to add new ones.
- Never write to `data/**` — that's the agent's own memory databases.

By convention (subagent descriptions encode these):

- `wiki-curator` — writes under `research/wiki/**` and edits
  `research/raw/_index.json`.
- `drafter` — writes under `thesis/**`.
- `researcher` — read-only.

## Tools at runtime (all built in)

You get these for free from `deepagents`' `LocalShellBackend` +
`StoreBackend`, composed via `CompositeBackend`:

- `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep` —
  filesystem scoped to the workspace root. Virtual paths like
  `/research/wiki/x.md` map onto disk under the workspace.
- `execute` — shell commands run from the workspace root, 60 s
  timeout (`THESIS_SHELL_TIMEOUT_SEC`), 100 KB output cap. Use for
  `thesis ingest`, git, pandoc, pytest, anything deterministic you'd
  type at a shell prompt.
- `write_todos`, `read_todos` — task-list scratchpad for multi-step
  work.
- `task` — delegate to a subagent defined in `subagents.yaml`.
- Writes under `/memories/**` persist across chat sessions (routed
  through a SQLite-backed `StoreBackend`). Use for user preferences
  and long-running context; wiki + thesis content stay under their
  own trees.

Plus:

- **MCP tools** — any servers listed in `.thesis/mcp.json` (or
  `$THESIS_MCP_CONFIG`) are connected at boot via
  `langchain-mcp-adapters`. Supports stdio / SSE / streamable_http.
  You can modify the config file yourself when the user asks —
  `edit_file` on `.thesis/mcp.json` works, and the next `thesis chat`
  session picks up the change.

The agent is configured by three files in the workspace which the user
(or you, when asked) can edit:

- `AGENTS.md` — this schema.
- `skills/<name>/SKILL.md` — workflow definitions triggered by the
  user's ask. Description field decides when to fire; body loads on
  demand.
- `subagents.yaml` — delegated specialist configs. Edit a name,
  description, or system_prompt and the change takes effect next
  `thesis chat`.

---

## Hard rules (non-negotiable)

1. **Every factual claim** in `research/wiki/**` and `thesis/**` carries a
   `[src:...]` citation.
2. **Never fabricate** sources, quotes, author names, dates, or statistics.
3. **Never write** to `research/raw/` or `data/`.
4. **Always read** `style/STYLE.md` before any `thesis/**` write.
5. **Contradictions are flagged, not resolved.** Add `⚠ conflicts with [[other]]`
   on both pages and move on.
6. When the wiki has no answer, say so. Do not fill the gap from memory.
7. **One ingest touches many pages.** If you only wrote a source summary,
   redo the ingest: update entities, concepts, index, and log.
8. **Use `edit_file` for in-place updates.** `write_file` refuses to overwrite
   existing files by design (a guardrail against accidental clobbering).
9. **Reciprocal cross-references.** When you add `See also: [[X]]` on page A,
   add `See also: [[A]]` on page X.
10. **Log every substantive operation.** If you ingested, queried, or linted,
    there must be a matching entry in `log.md`.

---

## Page slug convention

`<lowercase-kebab-case>` — strip punctuation, replace spaces with `-`, keep
under 60 chars. Examples:
  - Paper "Attention Is All You Need" → `attention-is-all-you-need`
  - Entity "GPT-4" → `gpt-4`
  - Concept "Self-Supervised Learning" → `self-supervised-learning`

Wiki links use double-bracket format `[[sources/foo]]`, `[[entities/bar]]`,
`[[concepts/baz]]`. Paths are relative to `research/wiki/`.
