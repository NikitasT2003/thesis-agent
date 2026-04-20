---
name: thesis-writer
description: >
  Use this skill to draft, write, or expand a thesis section, chapter,
  paragraph, or the whole thesis. Enforces the grounding rule (every
  factual claim cites an indexed source), loads the user's writing style
  from `style/STYLE.md`, navigates the LLM-Wiki-pattern knowledge base
  (index.md → concept pages → entity pages → source pages → raw), and
  writes to `thesis/chapters/<NN>.md` matching `thesis/outline.md`
  numbering. When the drafting surfaced substantive synthesis worth
  keeping, also files a query/synthesis page back into the wiki.
  Triggers "draft", "write section", "expand outline", "write chapter",
  "flesh out 2.1", "continue writing".
---

# thesis-writer

## Procedure (non-negotiable order)

1. **Style check.** Read `style/STYLE.md`. If missing, STOP and tell the
   user: "Run `thesis style` first to compile your writing-style guide from
   `style/samples/`." Do not draft without a style guide.

2. **Outline check.** Read `thesis/outline.md`. Locate the requested section.
   If absent, ask the user to add it to the outline before drafting.

3. **Wiki navigation** (do this in order; do NOT jump straight to raw files):
   a. Read `research/wiki/index.md` and identify the concept pages relevant
      to the section.
   b. Read those concept pages. Follow their `See also` links to
      entity pages.
   c. Read the entity pages. Follow their `See also` links to source-summary
      pages where you need the source's exact wording.
   d. Drill into `research/raw/<file>.md` ONLY when a source page lacks a
      specific detail. Prefer wiki-first.

4. **Delegate to the `drafter` subagent** with:
   - Section identifier + outline excerpt.
   - The list of wiki pages (concept → entity → source) you consulted.
   - A reminder to follow `style/STYLE.md` exactly.

5. **Drafter writes** to `thesis/chapters/<NN>.md` (where `NN` matches the
   outline numbering). If the chapter file already exists, extend it —
   use `edit_file`, not `write_file` (which refuses to overwrite).

6. **Self-lint before returning.** Every paragraph making a factual
   statement has at least one `[src:<raw_filename>]`. Transitions and
   author commentary without facts are fine.

7. **File-back check.** If the drafting required non-trivial synthesis —
   a cross-source comparison, a new connection, a causal argument the
   sources didn't state outright — file that reasoning back into the wiki
   as a query/synthesis page:
   `research/wiki/queries/<YYYY-MM-DD>-<slug>.md`. Why: the reasoning
   compounds if it's in the wiki, but disappears if it's only in a chapter
   (where future questions can't reach it easily). Update `index.md` under
   Queries and append to `log.md`:
   ```
   ## [YYYY-MM-DD] query | wrote section <N.M>
   - Filed: [[queries/YYYY-MM-DD-<slug>]]
   - Pages read: [[…]], [[…]]
   ```
   For routine drafting that just restates what sources already say, skip
   this step.

## Hard rules
- **Never a factual claim without `[src:<raw_filename>]`.** Refuse with
  "no grounding in indexed sources — add material or remove claim."
- **No pretraining facts, no web.** The wiki is the truth.
- **Never fabricate** a source filename. Every `[src:X]` corresponds to
  an actual file in `research/raw/`.
- **Match `STYLE.md`** — sentence length, hedging, POV, citation placement,
  transitions. Re-read it at the start of each drafting turn.
- **Respect scope**: drafter writes only under `thesis/**`; file-back
  queries go under `research/wiki/queries/**`.
- **Use `edit_file` to extend** existing chapters. `write_file` refuses
  to overwrite.

## Output
Report back: the chapter file written, approximate word count, number of
citations, and (if filed) the query page path. Do not paste the full chapter
into chat unless asked.
