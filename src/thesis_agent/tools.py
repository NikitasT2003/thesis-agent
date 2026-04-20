"""External tool loading: MCP servers.

Filesystem + shell tools are provided by deepagents' `LocalShellBackend`
out of the box (see `agent.py`). The only thing this module adds is a
loader for MCP servers declared in `.thesis/mcp.json` (or via the
`$THESIS_MCP_CONFIG` env var), using `langchain-mcp-adapters`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from thesis_agent.config import paths

_MCP_CONFIG_ENV = "THESIS_MCP_CONFIG"


def _mcp_config_path() -> Path:
    """Where to look for the MCP server config.

    1. `$THESIS_MCP_CONFIG` (absolute or relative to workspace)
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
    """Connect to every server in the MCP config and return their tools.

    Safe to call with no config (returns []). Uses
    `langchain_mcp_adapters.MultiServerMCPClient` which handles stdio /
    SSE / streamable_http uniformly. Individual server failures are
    logged and skipped.
    """
    cfg = _load_mcp_config()
    if not cfg or cfg.get("_error"):
        if cfg.get("_error"):
            import sys
            print(f"thesis-agent: {cfg['_error']}", file=sys.stderr)
        return []

    # Accept either flat form `{server_name: {...}}` or nested
    # `{servers: {server_name: {...}}}`.
    servers = cfg.get("servers") or cfg
    servers = {
        k: v for k, v in servers.items()
        if isinstance(v, dict) and not k.startswith("_")
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
        # Already in an event loop — rare in our sync CLI path.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_collect())
        finally:
            loop.close()
