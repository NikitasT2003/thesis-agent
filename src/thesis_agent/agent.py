"""Agent factory: wire deepagents with our skills, subagents, sandbox, and memory.

Call sites use the `run_agent(...)` helper so the memory context is opened
and closed cleanly around a single agent call (chat loop opens it once and
reuses).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from thesis_agent.config import Paths, load_env, make_model, models, paths
from thesis_agent.memory import memory_context
from thesis_agent.subagents import get_subagents

MAIN_SYSTEM_PROMPT = """You are the thesis-agent main orchestrator.

The schema in AGENTS.md is your operating manual; follow it exactly. Key
reminders:
  * No facts from pretraining. Every factual claim must carry `[src:<file>]`
    and trace to `research/raw/` + `research/wiki/`.
  * The wiki is the index. Navigate it with read_file/glob/grep. There is
    no vector search. There is no web. There is no shell.
  * Delegate to subagents: wiki-curator for building wiki pages, drafter for
    writing thesis chapters, researcher for read-only questions.
  * Write scopes are enforced. Do not try to write outside them.
  * When asked for something you cannot ground in the indexed sources, say so.

COST + EFFICIENCY RULES (non-negotiable):
  * Plan briefly, then act. Do NOT enumerate every possible path before
    reading a file. One `ls` or one `glob` is usually enough.
  * Read each file AT MOST ONCE per task. AGENTS.md is already in your
    system prompt — never `read_file("AGENTS.md")`.
  * Do not re-read files you already read this turn.
  * Prefer one decisive tool call over three speculative ones.
  * When delegating to a subagent, give it ALL the context it needs in the
    initial prompt — don't fan out into multiple task() calls for one job.
  * If a tool returns an error, read the error and adjust; do not blindly
    retry the same call.
  * Stop as soon as the user's request is satisfied. Do not polish,
    re-verify, or summarise unprompted.
"""

# LangGraph safety ceiling — stops runaway loops before they bill a fortune.
# Overridable via THESIS_RECURSION_LIMIT for power users (e.g. large theses
# with many sources where 25 steps per curate pass isn't enough).
import os as _os  # noqa: E402

_DEFAULT_RECURSION_LIMIT = 25


def _recursion_limit() -> int:
    raw = _os.environ.get("THESIS_RECURSION_LIMIT")
    if raw and raw.strip().isdigit():
        return max(5, int(raw))
    return _DEFAULT_RECURSION_LIMIT


def _find_skills_dir() -> Path:
    """Bundled skills live next to the package; user may override with
    `./skills/` in the workspace."""
    ws = paths().root / "skills"
    if ws.exists():
        return ws
    # installed package case: skills shipped alongside
    here = Path(__file__).resolve().parent.parent.parent / "skills"
    return here


@contextmanager
def build_agent(
    *,
    system_prompt: str = MAIN_SYSTEM_PROMPT,
    p: Paths | None = None,
) -> Iterator[Any]:
    """Construct a deepagents agent wired with our config.

    Yields the agent object. Caller invokes via `.invoke(...)` or `.stream(...)`.
    Memory connections stay open for the duration of the `with` block.
    """
    load_env(required_api_key=True)
    p = p or paths()
    mconf = models()

    from deepagents import create_deep_agent

    # Import the filesystem backend defensively — deepagents 0.x has shuffled
    # these around between releases. Fall back to library default if absent.
    FilesystemBackend = None
    try:
        from deepagents.backends import FilesystemBackend  # type: ignore
    except Exception:
        try:
            from deepagents import FilesystemBackend  # type: ignore
        except Exception:
            FilesystemBackend = None

    with ExitStack() as stack:
        checkpointer, store = stack.enter_context(memory_context(p))

        kwargs: dict[str, Any] = {
            # Main orchestrator runs on the drafter model (most capable)
            # but with the curator's tighter output cap — the orchestrator
            # mostly plans and delegates; it rarely needs a long reply.
            "model": make_model(mconf.drafter, role="curator"),
            "tools": [],  # sandbox: no shell, no network, no code exec
            "system_prompt": system_prompt,
            "subagents": get_subagents(mconf),
            "checkpointer": checkpointer,
            "store": store,
        }

        # AGENTS.md schema gets loaded into the system prompt by deepagents.
        if p.agents_md.exists():
            kwargs["memory"] = [str(p.agents_md)]

        skills_dir = _find_skills_dir()
        if skills_dir.exists():
            kwargs["skills"] = [str(skills_dir)]

        if FilesystemBackend is not None:
            try:
                kwargs["backend"] = FilesystemBackend(root_dir=str(p.root))
            except Exception:
                pass  # library will use its default

        agent = create_deep_agent(**kwargs)
        yield agent


def invoke(prompt: str, *, thread_id: str, p: Paths | None = None) -> str:
    """One-shot agent invocation. Returns the assistant's final message."""
    with build_agent(p=p) as agent:
        cfg = {
            "configurable": {"thread_id": thread_id},
            # Hard ceiling on agent loop iterations — stops runaway spend
            # before it starts. ~25 steps is enough for curating one source
            # or drafting one section. Override with THESIS_RECURSION_LIMIT.
            "recursion_limit": _recursion_limit(),
        }
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config=cfg,
        )
    msgs = result.get("messages", [])
    if not msgs:
        return ""
    last = msgs[-1]
    # LangChain message objects or plain dicts
    return getattr(last, "content", None) or last.get("content", "")
