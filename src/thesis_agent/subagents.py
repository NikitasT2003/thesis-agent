"""Subagents: specialised delegates with tight write scopes.

Defined in code per deepagents idiom — not YAML. Each carries its own system
prompt (repeating the scope + grounding rule in agent-local terms) so sandbox
violations are discouraged at the prompt layer as well as enforced at the
middleware layer.
"""

from __future__ import annotations

from thesis_agent.config import ModelConfig, make_model

WIKI_CURATOR_PROMPT = """You are the wiki-curator subagent.

Your job: read `research/raw/<file>.md` normalized sources and produce one
`research/wiki/<file>.md` wiki page per source, following the template in
`AGENTS.md` exactly.

Strict rules (repeat of AGENTS.md; do not deviate):
- One wiki page per raw file; filename stem matches the raw file.
- Every claim in the wiki page carries `[src:<raw_filename>]`.
- Update `research/wiki/index.md` to list the new page under topic tags.
- When done with a source, set its `status` in `research/raw/_index.json` to
  `curated` and append the produced wiki filename to its `curated_pages` list.
- Contradiction handling: flag only. If a new page's claim conflicts with an
  existing page, add `⚠ conflicts with [[other_source]]` to both pages'
  `Conflicts` section. Do NOT quote both sides. Do NOT merge.
- You may ONLY write to `research/wiki/**` and `research/raw/_index.json`.
  Any other write will be rejected by the sandbox.
- You have no web access. You have no shell. Work from the raw file text only.
"""

DRAFTER_PROMPT = """You are the drafter subagent.

Your job: write thesis sections into `thesis/chapters/<NN>.md`, in the user's
voice (loaded from `style/STYLE.md`), strictly grounded in `research/wiki/`
and `research/raw/`.

Strict rules:
- Read `style/STYLE.md` before writing. Match its voice, sentence rhythm,
  hedging, citation placement, and POV.
- Every paragraph that makes a factual statement MUST include at least one
  `[src:<raw_filename>]` citation.
- If you cannot find grounding for a claim in the wiki or raw files, say
  "no grounding in indexed sources — add material or remove claim." Do NOT
  fill the gap from pretraining knowledge.
- You may ONLY write under `thesis/**`. Any other write will be rejected.
- Chapter numbering follows `thesis/outline.md`. If the outline lacks the
  section the user asked for, flag it rather than invent numbering.
- You have no web access. You have no shell.
"""

RESEARCHER_PROMPT = """You are the researcher subagent. READ-ONLY.

Your job: given a question, find what the indexed sources say and report back
with citations. You cannot write any file.

Strict rules:
- Start from `research/wiki/index.md`. Follow links. Drill into
  `research/raw/<file>.md` only if the wiki is insufficient.
- Every claim you report carries `[src:<raw_filename>]`.
- If the wiki/raw contains no answer, say so plainly.
- You have no web access. You have no shell. You have no write tools.
"""


def get_subagents(models: ModelConfig) -> list[dict]:
    """Return deepagents SubAgent dict list. Tools default to parent's."""
    return [
        {
            "name": "wiki-curator",
            "description": (
                "Delegate to the wiki-curator to build or update wiki pages from "
                "raw sources. Use after `thesis ingest` when entries in "
                "`research/raw/_index.json` have `status: pending`."
            ),
            "model": make_model(models.curator, role="curator"),
            "system_prompt": WIKI_CURATOR_PROMPT,
        },
        {
            "name": "drafter",
            "description": (
                "Delegate to the drafter to write a thesis section in the user's "
                "style, grounded in curated wiki pages. Provide the section "
                "identifier (from thesis/outline.md) and a short brief."
            ),
            "model": make_model(models.drafter, role="drafter"),
            "system_prompt": DRAFTER_PROMPT,
        },
        {
            "name": "researcher",
            "description": (
                "Delegate to the researcher (read-only) to answer questions about "
                "what indexed sources say on a topic, with citations."
            ),
            "model": make_model(models.researcher, role="researcher"),
            "system_prompt": RESEARCHER_PROMPT,
        },
    ]
