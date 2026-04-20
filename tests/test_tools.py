"""External tool loading: MCP config discovery + tool construction.

Filesystem + shell tools are not tested here — they come from
deepagents' `LocalShellBackend` and are covered by end-to-end agent
tests in `test_agent_e2e.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesis_agent import tools


@pytest.fixture
def ws(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("THESIS_MCP_CONFIG", raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# MCP config discovery
# ---------------------------------------------------------------------------

class TestMCPConfigPath:
    def test_default_is_dot_thesis_mcp_json(self, ws: Path):
        """With no file and no env var, we return the canonical default path
        (non-existent) so the caller can decide whether to create it."""
        p = tools._mcp_config_path()
        assert p.name == "mcp.json"
        assert not p.exists()

    def test_env_override_absolute(self, ws: Path, monkeypatch):
        (ws / "custom.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("THESIS_MCP_CONFIG", str(ws / "custom.json"))
        assert tools._mcp_config_path().name == "custom.json"

    def test_env_override_relative_to_workspace(self, ws: Path, monkeypatch):
        (ws / "x.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("THESIS_MCP_CONFIG", "x.json")
        assert tools._mcp_config_path().name == "x.json"

    def test_dot_thesis_preferred_over_flat(self, ws: Path):
        (ws / ".thesis").mkdir()
        (ws / ".thesis" / "mcp.json").write_text("{}", encoding="utf-8")
        (ws / "mcp.json").write_text("{}", encoding="utf-8")
        assert tools._mcp_config_path() == (ws / ".thesis" / "mcp.json")

    def test_flat_fallback(self, ws: Path):
        (ws / "mcp.json").write_text("{}", encoding="utf-8")
        assert tools._mcp_config_path() == (ws / "mcp.json")


# ---------------------------------------------------------------------------
# _load_mcp_config parsing
# ---------------------------------------------------------------------------

class TestLoadMCPConfig:
    def test_missing_returns_empty(self, ws: Path):
        assert tools._load_mcp_config() == {}

    def test_invalid_json_reports_error(self, ws: Path):
        (ws / "mcp.json").write_text("{ not valid", encoding="utf-8")
        cfg = tools._load_mcp_config()
        assert "_error" in cfg

    def test_non_dict_toplevel_treated_as_empty(self, ws: Path):
        (ws / "mcp.json").write_text("[1,2,3]", encoding="utf-8")
        assert tools._load_mcp_config() == {}

    def test_parses_valid(self, ws: Path):
        (ws / "mcp.json").write_text(
            json.dumps({"servers": {"a": {"command": "x"}}}),
            encoding="utf-8",
        )
        cfg = tools._load_mcp_config()
        assert cfg == {"servers": {"a": {"command": "x"}}}


# ---------------------------------------------------------------------------
# load_mcp_tools_sync composition
# ---------------------------------------------------------------------------

class TestLoadMCPTools:
    def test_no_config_returns_empty(self, ws: Path):
        assert tools.load_mcp_tools_sync() == []

    def test_flat_config_reaches_client(self, ws: Path, monkeypatch):
        """Flat `{server: {...}}` form is accepted alongside the nested
        `{servers: {...}}` form."""
        (ws / "mcp.json").write_text(
            json.dumps({"alpha": {"command": "echo", "transport": "stdio"}}),
            encoding="utf-8",
        )
        recorded: dict = {}

        class _FakeClient:
            def __init__(self, servers):
                recorded["servers"] = servers

            async def get_tools(self):
                return ["t1", "t2"]

        import sys
        import types
        fake = types.ModuleType("langchain_mcp_adapters.client")
        fake.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake)

        assert tools.load_mcp_tools_sync() == ["t1", "t2"]
        assert "alpha" in recorded["servers"]

    def test_nested_servers_key_form(self, ws: Path, monkeypatch):
        (ws / "mcp.json").write_text(
            json.dumps({"servers": {"svc": {"url": "http://x"}}}),
            encoding="utf-8",
        )

        class _FakeClient:
            def __init__(self, servers):
                self.servers = servers

            async def get_tools(self):
                return [f"from-{name}" for name in self.servers]

        import sys
        import types
        fake = types.ModuleType("langchain_mcp_adapters.client")
        fake.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake)

        assert tools.load_mcp_tools_sync() == ["from-svc"]

    def test_server_failure_returns_empty_and_does_not_raise(self, ws: Path, monkeypatch):
        (ws / "mcp.json").write_text(
            json.dumps({"bad": {"command": "x"}}),
            encoding="utf-8",
        )

        class _FakeClient:
            def __init__(self, servers):
                pass

            async def get_tools(self):
                raise RuntimeError("cannot connect")

        import sys
        import types
        fake = types.ModuleType("langchain_mcp_adapters.client")
        fake.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake)

        # Must not raise — we log + return [] so the rest of the agent boots.
        assert tools.load_mcp_tools_sync() == []

    def test_bad_json_returns_empty(self, ws: Path):
        (ws / "mcp.json").write_text("{ not valid", encoding="utf-8")
        assert tools.load_mcp_tools_sync() == []


# ---------------------------------------------------------------------------
# LocalShellBackend gives us execute (sanity check — wiring)
# ---------------------------------------------------------------------------

class TestLocalShellBackendWiring:
    def test_execute_is_available_on_backend(self):
        """Regression: deepagents' `LocalShellBackend` provides the
        `execute` tool out of the box. If this import or attribute goes
        away in a deepagents upgrade, the agent loses its shell."""
        from deepagents.backends import LocalShellBackend

        assert hasattr(LocalShellBackend, "execute"), (
            "LocalShellBackend.execute is missing — upgrade likely broke "
            "the shell tool wiring"
        )
