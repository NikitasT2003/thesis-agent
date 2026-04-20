---
name: thesis-writer
description: >
  Use this skill when the user asks you to draft, write, or expand a thesis
  section, chapter, paragraph, or the whole thesis. Enforces the grounding
  rule (every factual claim cites an indexed source), loads the user's writing
  style from `style/STYLE.md`, navigates the wiki for supporting material, and
  writes to `thesis/chapters/<NN>.md` matching `thesis/outline.md` numbering.
  Triggers "draft", "write section", "expand outline", "write chapter",
  "flesh out 2.1", "continue writing".
---

# thesis-writer

## Procedure (non-negotiable order)

1. **Style check.** Read `style/STYLE.md`. If it does not exist, STOP and tell the user: "Run `thesis style` first to compile your writing-style guide from `style/samples/`." Do not draft without a style guide.

2. **Outline check.** Read `thesis/outline.md`. Find the section the user asked for. If missing, ask the user to add it to the outline first.

3. **Wiki navigation.** Read `research/wiki/index.md`. Identify pages relevant to the section (match on tags, entity names, section keywords). Read each relevant wiki page.

4. **Drill-down (only if needed).** If a wiki page's summary/key-claims do not cover a point you need, read the corresponding `research/raw/<file>.md` for verbatim context. Prefer wiki-first.

5. **Delegate to drafter.** Hand off to the `drafter` subagent with:
   - Section identifier + outline excerpt.
   - The list of wiki pages that will ground the draft.
   - A reminder to follow `style/STYLE.md`.

6. **Drafter writes** `thesis/chapters/<NN>.md` where `NN` matches the outline's numbering (e.g. section 2.1 → chapter 02). If the chapter file already exists, extend it — do not overwrite silently.

7. **Self-lint before returning.** Every paragraph with a factual statement has at least one `[src:<filename>]`. Grab-bag transitions without factual content are fine.

## Hard rules
- **Never write a factual claim without `[src:<raw_filename>]`.** If wiki + raw don't support it, output "no grounding in indexed sources — add material or remove claim" and stop.
- **Never use pretraining knowledge** for facts, statistics, quotes, author attributions, or dates. The indexed sources are the only truth.
- **Never fabricate** a source filename. Every `[src:X]` must correspond to an actual file under `research/raw/`.
- **Match the style guide**: sentence length, hedging, jargon density, POV, transitions. The drafter should re-read `STYLE.md` before every handoff.
- **Respect write scope**: drafter writes only under `thesis/**`.

## Output
After drafting, report to the user: file written, approximate word count, and a 2-line summary of what you drafted. Do not paste the full chapter back into chat unless asked.
