"""Agent factory. Canonical deepagents pattern — no custom glue.

  create_deep_agent(
      model=...,
      memory=["AGENTS.md"],              # middleware: loaded into system prompt
      skills=["./skills/"],              # middleware: loaded on demand
      subagents=load_subagents(...),     # YAML → SubAgent dicts
      tools=[*mcp_tools],                # extras (filesystem + shell + task
                                         # are added automatically by the backend)
      backend=CompositeBackend(
          default=LocalShellBackend(...),     # fs + execute (shell)
          routes={"/memories/": StoreBackend()},  # persistent cross-thread
      ),
      checkpointer=SqliteSaver(...),     # short-term, thread-scoped
      store=SqliteStore(...),            # long-term, cross-thread
  )

Nothing above is custom to this project — it's all straight out of the
deepagents `content-builder-agent` example. The project-specific things
live in files the user can edit without touching Python:
`AGENTS.md`, `skills/<name>/SKILL.md`, `subagents.yaml`, `mcp.json`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from thesis_agent.config import Paths, load_env, make_model, models, paths
from thesis_agent.memory import memory_context
from thesis_agent.subagents import load_subagents
from thesis_agent.tools import load_mcp_tools_sync

# Keep the system prompt tiny: AGENTS.md (loaded via `memory=[...]`) is
# the real operating manual. This prompt just orients the model.
MAIN_SYSTEM_PROMPT = """You are thesis-agent, a terminal-native assistant for
writing a thesis from indexed source material.

`AGENTS.md` is in your system prompt — it is the schema (wiki layout,
citation rules, hard rules). Follow it. The user's ask drives what you
do; pick the right skill from `skills/` on your own.

Tools available to you: filesystem (read_file, write_file, edit_file,
ls, glob, grep), shell (execute), task-tracking (write_todos / read_todos),
and subagent delegation (task). MCP servers listed in `.thesis/mcp.json`
are also wired in if configured.
"""


# Recursion limit: LangGraph safety ceiling. Large enough for a real
# multi-page ingest; overridable via THESIS_RECURSION_LIMIT.
_DEFAULT_RECURSION_LIMIT = 60


def _recursion_limit() -> int:
    raw = os.environ.get("THESIS_RECURSION_LIMIT")
    if raw and raw.strip().isdigit():
        return max(5, int(raw))
    return _DEFAULT_RECURSION_LIMIT


# Client-side loop detector — catches the weak-model failure mode where
# the same (tool_name, args) is called repeatedly. recursion_limit only
# catches "too many steps"; this catches "same step N times".
class ToolCallLoopError(RuntimeError):
    """Raised when the agent repeats the same (tool_name, args) N times."""


def _tool_call_signature(tool_call: dict) -> str:
    import json

    name = tool_call.get("name", "?")
    args = tool_call.get("args") or {}
    try:
        serialised = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        serialised = str(args)
    return f"{name}::{serialised}"


def _scan_for_loop(
    signatures: list[str], *, window: int = 10, threshold: int = 3
) -> str | None:
    from collections import Counter

    recent = signatures[-window:]
    for sig, n in Counter(recent).items():
        if n >= threshold:
            return sig
    return None


def _find_skills_dir() -> Path:
    """Workspace `skills/` wins; falls back to the repo-bundled one."""
    ws = paths().root / "skills"
    if ws.exists():
        return ws
    return Path(__file__).resolve().parent.parent.parent / "skills"


def _find_subagents_yaml() -> Path | None:
    """Workspace `subagents.yaml` wins; falls back to the repo-bundled one."""
    ws = paths().root / "subagents.yaml"
    if ws.exists():
        return ws
    bundled = Path(__file__).resolve().parent.parent.parent / "subagents.yaml"
    return bundled if bundled.exists() else None


def _make_backend(workspace_root: str, store_instance: Any):
    """Composite backend: shell-capable filesystem + persistent-memory routing.

    `LocalShellBackend` gives the agent `execute` (shell) alongside the
    usual filesystem tools. `StoreBackend` routes `/memories/` paths
    through the cross-thread store, so writes there survive new chat
    threads. Both are deepagents built-ins — no custom middleware.
    """
    from deepagents.backends import (
        CompositeBackend,
        LocalShellBackend,
        StoreBackend,
    )

    default = LocalShellBackend(
        root_dir=workspace_root,
        virtual_mode=True,  # scopes paths to root_dir, rejects `..` / absolute
        timeout=int(os.environ.get("THESIS_SHELL_TIMEOUT_SEC", "60")),
        max_output_bytes=100_000,
    )
    routes = {"/memories/": StoreBackend(store=store_instance)}
    return CompositeBackend(default=default, routes=routes)


@contextmanager
def build_agent(
    *,
    system_prompt: str = MAIN_SYSTEM_PROMPT,
    p: Paths | None = None,
) -> Iterator[Any]:
    """Yield a configured deepagents agent. Memory connections stay open
    for the duration of the `with` block."""
    load_env(required_api_key=True)
    p = p or paths()
    mconf = models()

    from deepagents import create_deep_agent

    with ExitStack() as stack:
        checkpointer, store = stack.enter_context(memory_context(p))

        kwargs: dict[str, Any] = {
            "model": make_model(mconf.drafter, role="curator"),
            "system_prompt": system_prompt,
            "tools": load_mcp_tools_sync(),  # bash/execute comes from backend
            "subagents": (
                load_subagents(sub_path, mconf)
                if (sub_path := _find_subagents_yaml()) else []
            ),
            "backend": _make_backend(str(p.root), store),
            "checkpointer": checkpointer,
            "store": store,
        }

        if p.agents_md.exists():
            kwargs["memory"] = [str(p.agents_md)]

        skills_dir = _find_skills_dir()
        if skills_dir.exists():
            kwargs["skills"] = [str(skills_dir)]

        yield create_deep_agent(**kwargs)


def invoke(prompt: str, *, thread_id: str, p: Paths | None = None) -> str:
    """One-shot agent invocation with loop detection."""
    from langchain_core.messages import AIMessage

    with build_agent(p=p) as agent:
        cfg = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _recursion_limit(),
        }
        signatures: list[str] = []
        seen = 0
        last_state: dict = {}
        for state in agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            config=cfg,
            stream_mode="values",
        ):
            last_state = state
            msgs = state.get("messages", []) or []
            for m in msgs[seen:]:
                if isinstance(m, AIMessage):
                    for tc in (m.tool_calls or []):
                        signatures.append(_tool_call_signature(tc))
                        offender = _scan_for_loop(signatures)
                        if offender is not None:
                            raise ToolCallLoopError(
                                f"agent repeated the same tool call 3+ times "
                                f"in the last 10 steps: {offender}. This "
                                f"usually means the model is weak for the "
                                f"task or hit a refusal it can't recover from "
                                f"(e.g. write_file on an existing path — "
                                f"should use edit_file instead)."
                            )
            seen = len(msgs)

    msgs = last_state.get("messages", [])
    if not msgs:
        return ""
    last = msgs[-1]
    return getattr(last, "content", None) or last.get("content", "")
