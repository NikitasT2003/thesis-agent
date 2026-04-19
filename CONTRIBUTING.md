# Contributing

## Dev setup

```bash
git clone https://github.com/your-org/thesis-agent.git
cd thesis-agent
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
```

## Project layout

```
src/thesis_agent/
  cli.py          Typer CLI (thesis setup, init, ingest, ...)
  agent.py        build_agent(): wires deepagents with our config
  subagents.py    researcher / wiki-curator / drafter definitions
  memory.py       SqliteSaver + SqliteStore context managers
  sandbox.py      path-scope enforcement for agent writes
  config.py       workspace paths + env + model defaults
  ingest/         deterministic source extraction (no LLM)
skills/           5 SKILL.md files (YAML frontmatter + markdown)
AGENTS.md         operating schema loaded into every agent run
examples/         sample workspace committed for first-run demo
tests/            ingest + sandbox + CLI smoke tests
```

## Adding a skill

1. `mkdir skills/your-skill`
2. Create `skills/your-skill/SKILL.md`:

```markdown
---
name: your-skill
description: >
  When to use this skill. Put ALL trigger conditions here — the body is
  only loaded after the skill has been triggered. Be explicit about the
  phrases that should activate it.
---

# your-skill

Step-by-step guidance here. What to read, what to write, what to avoid.
```

3. The skill is picked up automatically on the next agent run.

## Swapping the model

Set env vars in `.env`:

```
THESIS_MODEL_DRAFTER=anthropic:claude-sonnet-4-6
THESIS_MODEL_CURATOR=anthropic:claude-sonnet-4-6
THESIS_MODEL_RESEARCHER=anthropic:claude-haiku-4-5-20251001
```

## Adjusting the sandbox

`src/thesis_agent/sandbox.py` defines per-scope allow/deny globs. Tests in
`tests/test_sandbox.py` exercise the policy — run them if you change anything
there.

Two hard invariants that should not be relaxed:

1. `tools=[]` in `build_agent(...)` — no shell, no network, no code exec.
2. `research/raw/**` and `data/**` are always on the global deny list.

If you need the agent to do something it's currently blocked from, consider
whether a deterministic Python helper (like `ingest/`) would be safer than
giving the agent a new tool.

## Tests

- `tests/test_ingest.py` — extractor + manifest idempotency.
- `tests/test_sandbox.py` — path traversal, per-scope writes.
- `tests/test_cli_smoke.py` — `thesis --help`, `thesis init`, `thesis status`.

Add tests for any new code path before sending a PR. LLM-calling tests
should be avoided in CI (no Anthropic key available); exercise those
locally.

## Filing issues

- Include the full command you ran and the error.
- Include your Python and `uv` versions (`uv run python --version`, `uv --version`).
- Do **not** paste your API key or source material — reproduce with the
  committed examples where possible.
