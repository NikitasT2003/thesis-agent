---
name: wiki-linter
description: >
  Use this skill to health-check the LLM Wiki under `research/wiki/`.
  Scans every page and reports: unresolved contradictions, stale claims
  newer sources contradict, orphan pages with no inbound links, pages
  that reference an entity without linking its page, entities/concepts
  mentioned in source summaries but lacking their own page, thinly-covered
  topics that would benefit from more sources, and 2-5 suggested follow-up
  questions. Appends a `lint` entry to `log.md`. Triggers include
  "lint wiki", "check wiki", "wiki health", "audit the wiki",
  "review the knowledge base", "find orphans", "find gaps".
---

# wiki-linter

## Goal
Keep the wiki healthy as it grows. Humans give up on wikis because the
maintenance burden outpaces the value. Your job is to keep that burden near
zero by catching the things that silently break a compound knowledge base:
orphan pages, stale claims, broken cross-refs, data gaps.

## Procedure

1. Read `research/wiki/index.md` and `research/wiki/log.md` to orient.

2. Enumerate pages: `glob("research/wiki/**/*.md")`.

3. For each category below, scan + build a list of issues. Numbered, so the
   user can act on them one at a time.

### Contradictions (unresolved)
Glob for `⚠ conflicts with` markers. Report file + line + the conflicting
pages. **Do not resolve** — surface them for the user to decide.

### Stale claims
An entity page may assert claim X from source A, and a later source B may
contradict it. If neither page flagged the conflict, the old claim is stale.
Strategy: read each entity page's `Key claims` section; for each claim, grep
other pages that cite the same topic; if wording clearly disagrees, flag
`⚠ possibly stale` on the older claim (and record both pages in the report).

### Orphan pages
A page is an orphan if no other page links to it via `[[...]]`. Expected
orphans: `index.md`, `log.md`. Everything else should have at least one
inbound link. Report orphan slugs + suggest where they should be linked from
(usually `index.md` or the concept page closest to their topic).

### Missing cross-references
If page A mentions entity E (by name) but doesn't link `[[entities/<e-slug>]]`,
flag it. Heuristic: for each entity page, grep wiki for its title (and common
aliases listed in frontmatter); any hit without a `[[...]]` link is a missing
cross-ref.

### Missing entity / concept pages
Scan source-summary pages for capitalized named entities and key terms listed
in their `Key terms` section. For each, check if an entity page exists. If
not, flag `missing entity page: <name>` and suggest the slug.

### Data gaps (thinly covered topics)
Count how many sources each entity / concept page cites. Flag any
entity/concept page with fewer than 2 citing sources as a potential data
gap — the user may want to find more reading on it. Report the slug and the
current citation count.

### Suggested follow-up questions
End the report with 2-5 questions the user could ask next, generated from
the wiki's current shape. Good questions:
  - Point at thinly-covered topics: "What does the literature say about X?"
  - Point at unresolved contradictions: "Which view of Y seems better
    supported — the one in [[entities/a]] or [[entities/b]]?"
  - Point at synthesis gaps: "How do [[concepts/p]] and [[concepts/q]]
    relate, given the sources cover them separately?"
Bad questions: vague prompts, anything generic that ignores the wiki's
content.

4. Output a grouped report like:

```
Wiki health report — N pages scanned

== Contradictions (unresolved) ==
1. [[entities/transformer]] ⚠ conflicts with [[entities/rnn]] on vanishing
   gradients (line 42 + line 37). Consider: add a short comparison section
   to [[concepts/sequence-modelling]] and note the trade-off.

== Orphan pages ==
2. [[entities/gpt-2]] — no inbound links. Suggested: add to index.md under
   "Entities > Models" and reference from [[concepts/pretraining]].

== Missing cross-references ==
3. [[sources/attention-is-all-you-need]] mentions "Transformer" without a
   link to [[entities/transformer]] (line 18).

== Missing entity pages ==
4. "Adam optimizer" appears in 3 source summaries with no entity page.
   Suggested slug: entities/adam-optimizer.

== Data gaps ==
5. [[entities/layer-normalization]] cites only 1 source. Consider reading
   more on this.

== Follow-up questions you might ask ==
- How does [[entities/adam-optimizer]] compare to SGD across the sources
  that cover both?
- Why does [[concepts/attention-mechanisms]] cite 8 sources but
  [[concepts/positional-encoding]] only 2 — is that a real gap in the
  literature or a gap in your reading?
```

5. **Append a log entry** to `research/wiki/log.md`:
   ```
   ## [YYYY-MM-DD] lint | pass <n>
   - Contradictions: <count>
   - Orphans: <count>
   - Missing xrefs: <count>
   - Missing pages: <count>
   - Data gaps: <count>
   - Questions suggested: <count>
   ```

## What NOT to do
- Do NOT auto-fix. Offer; the user decides.
- Do NOT run web searches — you have no web tool. Suggest where one could
  help; the user can do it manually.
- Do NOT write to `research/raw/**` or `data/**`.
- Do NOT mark EVERY claim `⚠ possibly stale` — only those you're confident
  a newer source contradicts. False positives train the user to ignore you.
