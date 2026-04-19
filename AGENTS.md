# AGENTS.md — Thesis Agent Schema

This file is loaded into the main agent's system prompt on every run. It defines how to organise knowledge, write the thesis, and stay grounded. Follow it exactly.

---

## Three layers

1. **`research/raw/`** — immutable source material (PDFs, DOCX, EPUB, MD, URLs). Never edit these. The `thesis ingest` CLI command normalises each file to `research/raw/<filename>.md` (same stem as the original) and records it in `research/raw/_index.json` with `status: pending`.
2. **`research/wiki/`** — LLM-compiled knowledge. **One wiki page per source file**, named `research/wiki/<filename>.md` (matching the raw file's stem). Plus `research/wiki/index.md` which groups pages by topic/tag.
3. **This file (`AGENTS.md`)** — the schema that turns the raw layer into the wiki layer, and the wiki layer into grounded thesis prose.

The wiki is the index. **There is no vector search, no embeddings, no RAG.** To find information you navigate `research/wiki/index.md` → entity pages → drill into the raw file only if the wiki page is insufficient. Use `read_file`, `glob`, and `grep` — nothing else.

---

## Wiki page template

Every file under `research/wiki/<name>.md` (except `index.md`) must follow this template exactly. Use the raw source's stem as the filename.

```markdown
---
source: <raw_filename_with_ext>
title: <best-effort title from the source; filename if unknown>
authors: [<author1>, <author2>]   # empty list if unknown
date: <YYYY or YYYY-MM-DD if known; "unknown" otherwise>
tags: [<topic1>, <topic2>, ...]   # 3-8 short lowercase tags
---

# <title>

## Summary
3–5 sentences capturing the source's thesis / core contribution / relevance. Every sentence must be supported by the source. Inline-cite with `[src:<raw_filename>]`.

## Key claims
- Claim 1. [src:<raw_filename>]
- Claim 2. [src:<raw_filename>]
- ...
(5–15 bullet points. Each bullet is a discrete factual claim quotable in the thesis.)

## Methods / datasets
- <method or dataset name>: <one-line description>. [src:<raw_filename>]
(Omit this section if the source is not empirical.)

## Key terms
- <term>: <one-line definition as used in this source>. [src:<raw_filename>]

## See also
- [[<other_source_stem>]] — <one-line reason for the link>
(Cross-references to other wiki pages. Add reciprocally on the other page.)

## Conflicts
- ⚠ conflicts with [[<other_source_stem>]] on <claim topic>
(Flag only — do NOT quote both sides, do NOT merge. User resolves manually.)
```

---

## Citation format

Any factual claim — in a wiki page, in a thesis chapter, in chat — must carry `[src:<raw_filename>]` where `<raw_filename>` is the name (with extension) of the file in `research/raw/`. Example: `[src:attention-is-all-you-need.pdf]`.

Never invent a citation. If no source supports a claim, reply: **"no grounding in indexed sources — add material or remove claim."** Do not use pretraining knowledge. Do not use web search (you have no web tools anyway).

---

## Workflows

### Ingest (user-initiated via `thesis ingest`)
1. The CLI runs `thesis_agent.ingest` — pure Python, no agent involvement. You do not run this.
2. After it finishes, new entries appear in `research/raw/_index.json` with `status: pending`.

### Curate (agent — triggered by `thesis curate` or user request)
1. Read `research/raw/_index.json`. Collect entries where `status == "pending"`.
2. For each pending entry, delegate to the `wiki-curator` subagent with the raw filename. The subagent:
   - Reads `research/raw/<name>.md`.
   - Produces `research/wiki/<name>.md` following the template above.
   - Updates `research/wiki/index.md` to list the new page under the right topic cluster.
   - Flips `status` to `curated` in `_index.json`.
3. When all pending entries are processed, report a one-line summary: `curated N sources; M conflicts flagged`.

### Write (user-initiated via `thesis write <section>` or chat)
1. Read `style/STYLE.md`. If missing, stop and tell the user to run `thesis style` first.
2. Read `research/wiki/index.md`. Identify wiki pages relevant to the requested section.
3. Read those wiki pages.
4. For any claim you plan to make, verify it appears in a wiki page's "Key claims" or can be read out of the raw file. Drill into `research/raw/<file>.md` only when the wiki page is insufficient.
5. Delegate drafting to the `drafter` subagent. The drafter writes to `thesis/chapters/<NN>.md` (matching the outline numbering in `thesis/outline.md`).
6. Every paragraph must contain at least one `[src:...]` citation. Paragraphs with no citable claim (transitions, meta-prose) are allowed but must not make factual statements.

### Lint (agent — triggered by `thesis lint` or user request)
1. Read the target chapter file.
2. For every `[src:<name>]` citation, verify `research/raw/<name>` exists and `research/wiki/<name>.md` exists with `status: curated`.
3. Flag paragraphs that make factual claims without any citation.
4. Output a short report: file, line, issue, suggested fix. Do not auto-edit unless asked.

### Style learning (agent — triggered by `thesis style`)
1. Read every file in `style/samples/`.
2. Produce/update `style/STYLE.md` with sections: Voice, Sentence rhythm, Lexicon (jargon density, hedging words, favoured transitions), POV and tense, Citation placement habits, Structural patterns (how the user opens/closes sections).
3. Be specific and prescriptive (e.g., "average sentence length 22–28 words; avoid sentences under 10 words except in conclusions"). The drafter will follow this verbatim.

---

## Write scopes (enforced by the sandbox middleware — do not attempt violations)

- `researcher` subagent: **read-only**. Cannot write anywhere.
- `wiki-curator` subagent: may write only to `research/wiki/**` and update `research/raw/_index.json`.
- `drafter` subagent: may write only to `thesis/**`.
- The main agent: may write to `research/wiki/index.md`, `style/STYLE.md`, and the user's explicit targets. Never write to `research/raw/` (sources are immutable). Never write to `data/` (reserved for memory databases).
- No tool can reach outside the project workspace.

---

## Hard rules (non-negotiable)

1. **Every factual claim** in `research/wiki/**` and `thesis/**` has a `[src:...]` citation.
2. **Never fabricate** sources, quotes, author names, dates, or statistics.
3. **Never write** to `research/raw/` or `data/`.
4. **Always read** `style/STYLE.md` before any `thesis/**` write.
5. **Contradictions are flagged, not resolved.** Add `⚠ conflicts with [[other]]` on both pages; move on.
6. When the wiki has no answer, say so. Do not fill the gap from memory.
