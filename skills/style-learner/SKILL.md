---
name: style-learner
description: >
  Use this skill when the user asks you to learn their writing style,
  build/update the style guide, or when they have added new samples to
  `style/samples/`. Reads every file in `style/samples/`, extracts voice and
  mechanical patterns (sentence length, hedging, jargon density, POV, citation
  placement), and writes a prescriptive `style/STYLE.md` that the drafter will
  follow. Triggers "learn my style", "update style guide", "analyse my writing",
  "I added samples", "compile style".
---

# style-learner

## Goal
Produce a prescriptive style guide the drafter can follow verbatim. Descriptive observations ("the writer sometimes uses long sentences") are useless; prescriptive rules ("target 22–28 word average; allow 40+ in conclusions; cap short sentences under 10 words to transitions") are what makes the drafter sound like the user.

## Procedure

1. List `style/samples/` (accept `.md` and `.txt`). If empty, tell the user to drop 3–5 prior writing samples there first.
2. Read every sample.
3. Produce `style/STYLE.md` with these sections:

```markdown
# Writing Style Guide
_Derived from N samples totalling ~M words._

## Voice
- First-person / third-person / none-preferred: ...
- Hedging level (low/medium/high): ...
- Formal vs conversational: ...
- Any distinctive tics (e.g. rhetorical questions, em-dashes, parentheticals): ...

## Sentence rhythm
- Average sentence length: N words. Variation range: A–B words.
- Short-sentence policy: "allow under X words only for transitions / conclusions / not at all".
- Paragraph length: N–M sentences typical.

## Lexicon
- Jargon density: low / medium / high (per paragraph).
- Favoured transitions: [list].
- Hedging vocabulary used: [list].
- Banned or avoided words in samples: [list].

## POV and tense
- Tense: present / past / mixed.
- POV: ...

## Citation placement habits
- Where citations tend to sit (mid-sentence vs end-of-sentence vs end-of-paragraph): ...

## Structural patterns
- How sections typically open: ...
- How sections typically close: ...
- Use of lists, block quotes, equations: ...

## Do / Don't checklist (for the drafter)
- DO: ...
- DON'T: ...
```

4. Be specific. Use numbers wherever possible. The drafter will follow this like code.

## What NOT to do
- Do not include sample text itself in `STYLE.md` (it's a guide, not a corpus).
- Do not describe the user — describe the writing.
- Do not write to `style/samples/` (read-only to you).
