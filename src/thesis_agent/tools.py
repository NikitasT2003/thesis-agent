"""Tools the agent gets at runtime.

Two sources of tools:

1. **Bash** — a shell-in-the-workspace tool, built as a LangChain `@tool`.
   Runs in the workspace root, captures stdout/stderr, caps runtime.
   Disabled globally with `THESIS_NO_SHELL=1`. Without this the agent
   cannot run any shell command — the deepagents filesystem tools
   still work for reads/writes.

2. **MCP servers** — any MCP-compliant server listed in `.thesis/mcp.json`
   (or `$THESIS_MCP_CONFIG`) is connected at agent build time via
   `langchain-mcp-adapters`. Supports stdio, SSE, and streamable HTTP
   transports. Tools from every server are flattened into one list and
   passed to `create_deep_agent(tools=...)`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from thesis_agent.config import paths

SHELL_ENABLED_DEFAULT = True
_SHELL_DISABLE_ENV = "THESIS_NO_SHELL"
_SHELL_TIMEOUT_ENV = "THESIS_SHELL_TIMEOUT_SEC"
_SHELL_DEFAULT_TIMEOUT = 60
_SHELL_MAX_OUTPUT_BYTES = 64_000


def shell_enabled() -> bool:
    """Single source of truth for whether we expose the bash tool."""
    flag = (os.environ.get(_SHELL_DISABLE_ENV) or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return False
    return SHELL_ENABLED_DEFAULT


def _shell_timeout() -> int:
    raw = os.environ.get(_SHELL_TIMEOUT_ENV)
    if raw and raw.strip().isdigit():
        return max(5, int(raw))
    return _SHELL_DEFAULT_TIMEOUT


@tool("bash")
def bash_tool(command: str) -> str:
    """Run a shell command in the workspace root and return its combined
    stdout+stderr output. Use for: git operations, running `thesis ingest`,
    invoking `pandoc`, compiling LaTeX, running tests, or any other
    deterministic deterministic script. The workspace root is the CWD.

    The command runs with a timeout (default 60s, override via
    `THESIS_SHELL_TIMEOUT_SEC`). Output is truncated at 64 KB to keep
    the conversation window healthy. Destructive operations still
    require your confirmation via the CLI — the agent can execute
    whatever you'd execute at a shell prompt yourself.

    Do not use the shell to read or write files that the filesystem
    tools (`read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`)
    can handle — those are sandboxed and safer.
    """
    ws = paths().root
    try:
        completed = subprocess.run(  # noqa: S602  — explicit shell=True, see note above
            command,
            shell=True,
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=_shell_timeout(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            f"<bash timed out after {_shell_timeout()}s>\n"
            f"command: {command}"
        )
    except Exception as e:
        return f"<bash failed to start: {e}>\ncommand: {command}"

    out = (completed.stdout or "") + (
        f"\n[stderr]\n{completed.stderr}" if completed.stderr else ""
    )
    if len(out.encode("utf-8")) > _SHELL_MAX_OUTPUT_BYTES:
        out = out.encode("utf-8")[:_SHELL_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        out += f"\n\n<truncated at {_SHELL_MAX_OUTPUT_BYTES} bytes>"
    return (
        f"exit={completed.returncode}\n"
        f"{out.strip() or '<no output>'}"
    )


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

_MCP_CONFIG_ENV = "THESIS_MCP_CONFIG"


def _mcp_config_path() -> Path:
    """Where to look for the MCP server config. Order:
    1. $THESIS_MCP_CONFIG (absolute or relative)
    2. `.thesis/mcp.json` under the workspace
    3. `mcp.json` at the workspace root
    """
    override = os.environ.get(_MCP_CONFIG_ENV)
    if override:
        candidate = Path(override)
        if not candidate.is_absolute():
            candidate = paths().root / candidate
        return candidate
    root = paths().root
    for rel in (".thesis/mcp.json", "mcp.json"):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return root / ".thesis" / "mcp.json"  # non-existent default


def _load_mcp_config() -> dict[str, Any]:
    """Return the parsed config dict, or {} if no config file is present."""
    path = _mcp_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"_error": f"invalid JSON in {path}: {e}"}
    return data if isinstance(data, dict) else {}


def load_mcp_tools_sync() -> list:
    """Connect to every server in the MCP config and return their tools
    flattened into one list. Safe to call with no config (returns []).

    Uses `langchain-mcp-adapters.MultiServerMCPClient` which handles
    stdio / SSE / streamable_http transports uniformly. Any server that
    fails to connect is logged and skipped (others still work).

    Runs the async connection in a throwaway event loop so our sync
    `build_agent()` flow doesn't need to know about asyncio.
    """
    cfg = _load_mcp_config()
    if not cfg or cfg.get("_error"):
        if cfg.get("_error"):
            import sys
            print(f"thesis-agent: {cfg['_error']}", file=sys.stderr)
        return []

    # The config format mirrors langchain-mcp-adapters': a dict of
    # server_name → {command / url / transport / args / env / ...}.
    servers = cfg.get("servers") or cfg  # accept either {servers: {...}} or flat
    # Strip our own keys out of the flat form, if any slipped in.
    servers = {
        k: v for k, v in servers.items() if isinstance(v, dict) and not k.startswith("_")
    }
    if not servers:
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except Exception as e:
        import sys
        print(
            f"thesis-agent: MCP config found but `langchain-mcp-adapters` "
            f"is not installed ({e}). Run: uv add langchain-mcp-adapters",
            file=sys.stderr,
        )
        return []

    import asyncio

    async def _collect() -> list:
        client = MultiServerMCPClient(servers)
        tools: list = []
        try:
            tools = await client.get_tools()
        except Exception as e:
            import sys
            print(f"thesis-agent: MCP tool load failed: {e}", file=sys.stderr)
        return tools

    try:
        return asyncio.run(_collect())
    except RuntimeError:
        # Already in an event loop (unusual for our sync CLI, but be safe)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_collect())
        finally:
            loop.close()


def build_runtime_tools() -> list:
    """Compose the full tool list handed to `create_deep_agent(tools=...)`.

    The deepagents filesystem tools (`read_file`, `write_file`, `edit_file`,
    `ls`, `glob`, `grep`) come for free from the FilesystemBackend and do
    not need to be returned here. This function returns only the *extra*
    tools: bash (unless disabled) + MCP tools (if configured).
    """
    out: list = []
    if shell_enabled():
        out.append(bash_tool)
    out.extend(load_mcp_tools_sync())
    return out
