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

MAIN_SYSTEM_PROMPT = """You are thesis-agent, a terminal-native assistant for
writing a thesis from indexed source material.

The user drives. They'll ask for things like "ingest my new papers",
"curate the pending sources", "draft section 2.1", "lint the wiki", or
open-ended questions. Figure out what to do. The skills in `skills/`
describe conventions for each kind of task; read a skill's body only
when you need it (descriptions load by default). `AGENTS.md` in this
message is the schema — the wiki structure, citation format, and hard
rules — follow it exactly.

What you have:

  * **Filesystem tools** (read_file, write_file, edit_file, ls, glob,
    grep) scoped to the workspace. Virtual paths like
    `/research/wiki/index.md` map onto disk under the workspace root.
  * **Bash tool** — runs shell commands in the workspace. Use for
    `thesis ingest`, git, pandoc, pytest, anything you'd run at a
    prompt. The CLI already has a timeout; don't worry about hangs.
    May be disabled via `THESIS_NO_SHELL=1` — if it is, tell the user.
  * **Any MCP tools** the user attached via `.thesis/mcp.json`
    (web search, Obsidian, GitHub, etc.). Check your tool list at the
    start of a non-trivial task so you know what's available.
  * **Persistent memory** via the deepagents /memories/ path — writes
    there survive across chat sessions. Use it for user preferences,
    long-running goals, and durable context.
  * **Subagents** (task tool): `wiki-curator` for ingesting sources,
    `drafter` for writing thesis chapters, `researcher` for read-only
    research with citations.

Hard rules (from AGENTS.md):

  * Every factual claim in `research/wiki/**` and `thesis/**` carries
    `[src:<raw_filename>]`. No pretraining facts.
  * Never write to `research/raw/` — sources are immutable. Never write
    to `data/` — that's the agent's own memory.
  * `write_file` refuses to overwrite; use `edit_file` for in-place
    updates. Never retry a refused write — switch strategies.
  * When nothing in the wiki/raw grounds a claim, say so and stop.

Efficiency:

  * Plan briefly, then act. One `ls` or one `glob` is usually enough
    to orient yourself.
  * Read each file at most once per task. AGENTS.md is already here
    — never `read_file("AGENTS.md")`.
  * Prefer one decisive tool call over three speculative ones.
  * Stop as soon as the user's request is satisfied. No unprompted
    polish, no re-verification loops.
"""

# LangGraph safety ceiling — stops runaway loops before they bill a fortune.
# Overridable via THESIS_RECURSION_LIMIT for power users (e.g. large theses
# with many sources where the default per-pass budget isn't enough).
#
# 60 is a pragmatic default: a full curate pass on one source touches
# ~10-15 pages (source summary + entities + concepts + index + log +
# manifest), each of which is at least one tool call. Two sources fit.
# Chat and small linting runs fit easily. Raise via env var for very
# large batches.
import os as _os  # noqa: E402

_DEFAULT_RECURSION_LIMIT = 60


def _recursion_limit() -> int:
    raw = _os.environ.get("THESIS_RECURSION_LIMIT")
    if raw and raw.strip().isdigit():
        return max(5, int(raw))
    return _DEFAULT_RECURSION_LIMIT


# Client-side loop detector. Complements recursion_limit by catching the
# more common failure mode: the agent making THE SAME tool call over and
# over (e.g. retrying a write that `write_file` refused to overwrite
# instead of switching to `edit_file`). Weak or rate-limited models fall
# into this trap easily; recursion_limit alone wouldn't catch it until
# step N, wasting every step before then.
class ToolCallLoopError(RuntimeError):
    """Raised when the agent repeats the same (tool_name, args) N times."""


def _tool_call_signature(tool_call: dict) -> str:
    """Stable signature for dedup. Stringifies args with sorted keys so
    equivalent calls hash the same, independent of dict key order."""
    import json

    name = tool_call.get("name", "?")
    args = tool_call.get("args") or {}
    try:
        serialised = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        serialised = str(args)
    return f"{name}::{serialised}"


def _scan_for_loop(signatures: list[str], *, window: int = 10, threshold: int = 3) -> str | None:
    """Return the offending signature if any has repeated `threshold` times
    within the most recent `window` tool calls, else None."""
    from collections import Counter

    recent = signatures[-window:]
    counts = Counter(recent)
    for sig, n in counts.items():
        if n >= threshold:
            return sig
    return None


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

    from thesis_agent.tools import build_runtime_tools

    with ExitStack() as stack:
        checkpointer, store = stack.enter_context(memory_context(p))

        kwargs: dict[str, Any] = {
            # Main orchestrator runs on the drafter model (most capable)
            # but with the curator's tighter output cap — the orchestrator
            # mostly plans and delegates; it rarely needs a long reply.
            "model": make_model(mconf.drafter, role="curator"),
            # Runtime tools: bash (unless `THESIS_NO_SHELL=1`) + any MCP
            # tools the user attached via `.thesis/mcp.json`. Filesystem
            # tools come from the FilesystemBackend separately.
            "tools": build_runtime_tools(),
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
                # `virtual_mode=True` makes the agent see a clean virtual
                # filesystem rooted at `/` that maps onto `root_dir` on disk.
                # Pinned explicitly because deepagents will change the default
                # in 0.5.0 (per its DeprecationWarning).
                kwargs["backend"] = FilesystemBackend(
                    root_dir=str(p.root),
                    virtual_mode=True,
                )
            except Exception:
                pass  # library will use its default

        agent = create_deep_agent(**kwargs)
        yield agent


def invoke(prompt: str, *, thread_id: str, p: Paths | None = None) -> str:
    """One-shot agent invocation. Returns the assistant's final message.

    Uses `stream_mode="values"` so we can inspect each new AIMessage as it
    arrives and abort if the agent starts looping on the same tool call.
    This catches a failure mode recursion_limit alone wouldn't: the model
    retries the same (name, args) call repeatedly (e.g. a weak model that
    doesn't switch from `write_file` to `edit_file` after an overwrite
    refusal), burning every step up to the limit before failing.
    """
    from langchain_core.messages import AIMessage

    with build_agent(p=p) as agent:
        cfg = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _recursion_limit(),
        }
        signatures: list[str] = []
        seen_msg_count = 0
        last_state: dict = {}
        for state in agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            config=cfg,
            stream_mode="values",
        ):
            last_state = state
            msgs = state.get("messages", []) or []
            for m in msgs[seen_msg_count:]:
                if isinstance(m, AIMessage):
                    for tc in (m.tool_calls or []):
                        signatures.append(_tool_call_signature(tc))
                        offender = _scan_for_loop(signatures)
                        if offender is not None:
                            raise ToolCallLoopError(
                                f"agent repeated the same tool call 3+ times "
                                f"in the last 10 steps: {offender}. Aborting "
                                f"turn to prevent runaway spend. This usually "
                                f"means the model is weak for this task or "
                                f"hit a refusal it can't recover from (e.g. "
                                f"write_file on an existing path — should use "
                                f"edit_file instead)."
                            )
            seen_msg_count = len(msgs)

    msgs = last_state.get("messages", [])
    if not msgs:
        return ""
    last = msgs[-1]
    return getattr(last, "content", None) or last.get("content", "")
