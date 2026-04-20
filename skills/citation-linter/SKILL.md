---
name: citation-linter
description: Use this skill when the user asks to lint, check, verify, audit, or review citations in thesis chapters. Scans a chapter (or all chapters) for `[src:<filename>]` markers, verifies each target exists under `research/raw/`, flags paragraphs making factual claims without any citation, and reports file+line issues in a short actionable table. Does not auto-edit unless explicitly asked. Triggers "lint citations", "check citations", "audit grounding", "verify sources", "review chapter".
---

# citation-linter

## Goal
Catch grounding failures before they reach the final thesis.

## Procedure

1. Identify the target(s). If the user named a file, use it; otherwise glob `thesis/chapters/*.md`.
2. For each chapter file:
   a. Read it.
   b. For every `[src:<name>]` marker found: verify `research/raw/<name>` exists AND `research/wiki/<stem>.md` exists. If either is missing, record a DEAD CITATION issue with filename + line number + the bad marker.
   c. For every paragraph containing a factual statement but zero `[src:...]` markers: record an UNGROUNDED CLAIM issue with filename + line number + a 1-line excerpt.
   d. Distinguish factual statements from transitions/meta-prose by heuristic — if a paragraph names entities, quotes statistics, or asserts causation, it is factual. Pure transitions ("In the next section, we turn to X.") are exempt.

3. Produce a concise report:

```
<chapter_file>
  line 42  DEAD CITATION   [src:missing.pdf]  (no such file in research/raw/)
  line 58  UNGROUNDED      "recent studies show X is common..."
  line 71  DEAD CITATION   [src:paper.pdf]    (raw exists, wiki page missing)

<next_chapter>
  ...

Summary: 3 dead citations, 2 ungrounded paragraphs across 1 file.
```

4. Do NOT auto-edit. If the user asks "fix them", propose concrete edits (find source in wiki, replace marker, or drop claim) and write them only after they confirm.

## What NOT to do
- Do not mark paragraphs without citations as ungrounded when they are obvious transitions or author commentary.
- Do not silently accept `[src:X]` where X is not in the manifest — dead citations must surface.
- Do not touch `research/` — read-only in this skill.
