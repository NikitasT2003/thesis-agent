# thesis-agent

A local, sandboxed thesis-writing agent. Built on [`deepagents`][deepagents]
(LangChain/LangGraph) and Andrej Karpathy's [LLM Wiki pattern][wiki-pattern].

- **Indexes your sources.** Drop PDFs, DOCX, EPUB, Markdown, or URLs into
  `research/raw/`; one command normalises them.
- **Compiles a wiki, not a vector database.** One wiki page per source,
  cross-linked, grown over time. The wiki is the retrieval layer — no
  embeddings, no RAG, no services.
- **Writes in your voice.** Point it at a few of your prior essays and it
  compiles a prescriptive style guide the drafter follows verbatim.
- **Strictly grounded.** Every factual claim in your thesis cites an
  indexed source. If nothing supports the claim, the agent refuses.
- **Sandboxed.** The agent has no shell, no network, no code-exec tool.
  Filesystem access is scoped to your workspace, with per-subagent write
  allowlists.
- **Two-tier memory, both on SQLite.** Thread-scoped checkpoints +
  cross-thread store, all as plain files under `data/`. Clone the repo,
  take your memory with you.

## Quickstart for non-technical users

You need two things: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Install uv (one time)
#    macOS / Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
#    Windows:       winget install astral-sh.uv   (or see uv docs)

# 2. Clone and install
git clone https://github.com/your-org/thesis-agent.git
cd thesis-agent
uv sync

# 3. Run the interactive setup wizard
uv run thesis setup
#  - Pick a provider: Anthropic (direct) or OpenRouter (hundreds of models).
#  - Paste the API key when prompted. It is stored locally in `.env`.
#    Anthropic: https://console.anthropic.com/   (keys start sk-ant-)
#    OpenRouter: https://openrouter.ai/keys     (keys start sk-or-)
#  - Say yes to copying example files.

# 4. Drop your own sources and writing samples, then go
uv run thesis ingest      # normalise sources
uv run thesis style       # learn your writing voice
uv run thesis curate      # build the wiki
uv run thesis chat        # interactive drafting
```

That's it. Non-technical users can stop reading here.

## Commands

| Command | What it does |
|---|---|
| `thesis setup` | Interactive first-run wizard (API key, workspace, examples). |
| `thesis init` | Non-interactive workspace scaffold. |
| `thesis status` | What's in the workspace (counts, DB sizes, thread id). |
| `thesis ingest [DIR]` | Normalise PDFs/DOCX/EPUB/MD/URLs → markdown. No LLM. |
| `thesis style` | Compile `style/STYLE.md` from `style/samples/`. |
| `thesis curate` | Build wiki pages from `pending` sources. |
| `thesis write SECTION` | Draft one thesis section. |
| `thesis lint [FILE]` | Citation + grounding linter over chapters. |
| `thesis chat [--new]` | Interactive REPL. `/new`, `/quit` control the session. |

Global flags: `--thread <id>`, `--version`.

## How it works

```
         You drop files                   You read chapters
               │                                  ▲
               ▼                                  │
   research/raw/  ──┐                       thesis/chapters/
      (immutable)  │                              ▲
                   │                              │
                   │   wiki-curator               │   drafter
                   ▼   subagent                   │   subagent
               research/wiki/  ──────────────────┘
               (one page per source, cross-linked)
                        │
                        │  read by thesis-writer skill
                        ▼
              (grounded prose, [src:...] citations)
```

- **`research/raw/`** — normalised markdown, one per source. Never edited by
  the agent.
- **`research/wiki/`** — LLM-compiled markdown, one page per source, plus
  `index.md` grouping by topic. This is the retrieval layer.
- **`style/STYLE.md`** — prescriptive style guide the drafter follows.
- **`thesis/`** — your outline + chapters, written by the drafter.
- **`data/`** — SQLite memory. Gitignored. Never touched by the agent.

Schema lives in [`AGENTS.md`](AGENTS.md); read it to understand (and
customise) the agent's operating rules.

## Architecture (technical)

- Agent harness: `deepagents` (planning, subagents, filesystem, skills
  middleware, memory middleware).
- Subagents: `wiki-curator` (Sonnet), `drafter` (Sonnet), `researcher`
  (Haiku, read-only).
- Skills: `ingest-sources`, `wiki-curator`, `thesis-writer`, `style-learner`,
  `citation-linter` — each a `SKILL.md` with YAML frontmatter loaded on
  demand by deepagents.
- Memory: `SqliteSaver` for short-term (thread) + `SqliteStore` for
  long-term (cross-thread), both on local SQLite.
- Sandbox: `tools=[]` (no shell/network/exec), `FilesystemBackend` scoped to
  workspace, per-subagent write allowlists in `src/thesis_agent/sandbox.py`.
- Ingest: pure-Python `pypdf` / `python-docx` / `ebooklib` / `trafilatura`.
  No LLM involvement, deterministic, idempotent via sha256.

## Extending

- **Add a skill**: drop a new `skills/<name>/SKILL.md` with `name` and
  `description` frontmatter. The `description` must contain the trigger
  phrases — it's the only part loaded before activation.
- **Change models**: edit `.env` — `THESIS_MODEL_DRAFTER`,
  `THESIS_MODEL_CURATOR`, `THESIS_MODEL_RESEARCHER`. Format depends on
  provider:
  - Anthropic → `anthropic:claude-sonnet-4-6`
  - OpenRouter → `z-ai/glm-5.1`, `google/gemma-4-31b-it`,
    `openai/gpt-4o`, `meta-llama/llama-3.3-70b-instruct`, etc.
    (browse at [openrouter.ai/models](https://openrouter.ai/models))
  - OpenRouter defaults: drafter + curator use **GLM 5.1**
    (`z-ai/glm-5.1`, ~$1/M input, 200K context), researcher uses
    **Gemma 4 31B-IT** (`google/gemma-4-31b-it`, ~$0.13/M input,
    256K context). Roughly a 3–4× cost drop vs Claude Sonnet while
    keeping quality-critical roles on a capable frontier model.
- **Model fallback** (OpenRouter only): `THESIS_OPENROUTER_FALLBACK`
  is a comma-separated list passed to OpenRouter's `models` routing
  parameter. Requests automatically fall through the chain on
  outage, rate limit, or content filter. Default:
  `google/gemma-4-31b-it`. Set to empty string to disable.
- **Switch providers**: edit `.env` — set `THESIS_PROVIDER=anthropic` or
  `openrouter` and make sure the matching key is present.
- **Change the schema**: edit `AGENTS.md`. The whole agent is wired to
  follow it.

See [CONTRIBUTING.md](CONTRIBUTING.md) for more.

## License

MIT. See [LICENSE](LICENSE).

[deepagents]: https://github.com/langchain-ai/deepagents
[wiki-pattern]: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
