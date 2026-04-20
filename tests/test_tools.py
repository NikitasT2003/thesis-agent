"""Runtime tools: bash + MCP loader.

User asked for a Claude-Code-style agent in terminal with shell + MCP +
memory + skills. These tests lock in:
  * bash runs in the workspace root, captures output, respects
    timeout + size caps, and is togglable with `THESIS_NO_SHELL=1`
  * MCP config loader picks up `.thesis/mcp.json` or `$THESIS_MCP_CONFIG`
    and skips cleanly when absent
  * `build_runtime_tools()` composes bash + MCP tools into the list
    that `build_agent` hands to `create_deep_agent(tools=...)`
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesis_agent import tools


@pytest.fixture
def ws(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for v in (
        "THESIS_NO_SHELL", "THESIS_SHELL_TIMEOUT_SEC",
        "THESIS_MCP_CONFIG",
    ):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# shell_enabled toggle
# ---------------------------------------------------------------------------

class TestShellToggle:
    def test_enabled_by_default(self, ws: Path):
        assert tools.shell_enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_disable_via_env(self, ws: Path, monkeypatch, val):
        monkeypatch.setenv("THESIS_NO_SHELL", val)
        assert tools.shell_enabled() is False

    @pytest.mark.parametrize("val", ["0", "", "false", "no", "off"])
    def test_falsy_env_keeps_shell_enabled(self, ws: Path, monkeypatch, val):
        monkeypatch.setenv("THESIS_NO_SHELL", val)
        assert tools.shell_enabled() is True


# ---------------------------------------------------------------------------
# bash tool
# ---------------------------------------------------------------------------

class TestBashTool:
    def test_runs_command_in_workspace_cwd(self, ws: Path):
        # Use a command that works on both POSIX and Windows.
        result = tools.bash_tool.invoke({"command": "echo hello-bash"})
        assert "exit=0" in result
        assert "hello-bash" in result

    def test_captures_nonzero_exit(self, ws: Path):
        # `exit 7` works in both bash and cmd
        import sys
        cmd = "exit 7" if sys.platform == "win32" else "exit 7"
        result = tools.bash_tool.invoke({"command": cmd})
        assert "exit=7" in result

    def test_output_size_capped(self, ws: Path, monkeypatch):
        # Generate ~100KB of output — must be truncated
        import sys
        if sys.platform == "win32":
            # PowerShell one-liner would be huge to type; Python is portable.
            py = sys.executable
            cmd = f'"{py}" -c "print(\'x\' * 100000)"'
        else:
            cmd = "python -c 'print(\"x\" * 100000)'"
        monkeypatch.setenv("THESIS_SHELL_TIMEOUT_SEC", "30")
        result = tools.bash_tool.invoke({"command": cmd})
        # Output is capped at 64KB per the config constant
        assert "truncated" in result.lower() or len(result) < 70_000

    def test_timeout_respected(self, ws: Path, monkeypatch):
        monkeypatch.setenv("THESIS_SHELL_TIMEOUT_SEC", "5")  # floor
        assert tools._shell_timeout() == 5

    def test_timeout_has_floor(self, ws: Path, monkeypatch):
        monkeypatch.setenv("THESIS_SHELL_TIMEOUT_SEC", "1")
        # Clamped to >= 5 so we don't ship a useless 1s timeout.
        assert tools._shell_timeout() >= 5

    def test_bogus_timeout_env_falls_back(self, ws: Path, monkeypatch):
        monkeypatch.setenv("THESIS_SHELL_TIMEOUT_SEC", "forever")
        assert tools._shell_timeout() == tools._SHELL_DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# MCP config resolution
# ---------------------------------------------------------------------------

class TestMCPConfig:
    def test_path_default_when_none_present(self, ws: Path):
        path = tools._mcp_config_path()
        assert path.name == "mcp.json"
        assert not path.exists()

    def test_env_override_absolute(self, ws: Path, monkeypatch):
        (ws / "custom.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("THESIS_MCP_CONFIG", str(ws / "custom.json"))
        assert tools._mcp_config_path() == (ws / "custom.json").resolve() or \
               tools._mcp_config_path() == (ws / "custom.json")

    def test_env_override_relative(self, ws: Path, monkeypatch):
        (ws / "x.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("THESIS_MCP_CONFIG", "x.json")
        p = tools._mcp_config_path()
        assert p.name == "x.json"

    def test_prefers_dot_thesis(self, ws: Path):
        (ws / ".thesis").mkdir()
        (ws / ".thesis" / "mcp.json").write_text("{}", encoding="utf-8")
        (ws / "mcp.json").write_text("{}", encoding="utf-8")
        assert tools._mcp_config_path() == (ws / ".thesis" / "mcp.json")

    def test_load_mcp_config_missing_returns_empty(self, ws: Path):
        assert tools._load_mcp_config() == {}

    def test_load_mcp_config_invalid_json_reports_error(self, ws: Path):
        (ws / "mcp.json").write_text("{ not valid", encoding="utf-8")
        cfg = tools._load_mcp_config()
        assert "_error" in cfg


# ---------------------------------------------------------------------------
# load_mcp_tools_sync behaviour
# ---------------------------------------------------------------------------

class TestLoadMCPTools:
    def test_returns_empty_when_no_config(self, ws: Path):
        assert tools.load_mcp_tools_sync() == []

    def test_handles_flat_config(self, ws: Path, monkeypatch):
        """Config in the flat `{server: {...}}` form (no `servers` key).
        Patch MultiServerMCPClient so we don't need a real server."""
        (ws / "mcp.json").write_text(
            json.dumps({
                "fake-server": {"command": "echo", "transport": "stdio"},
            }),
            encoding="utf-8",
        )

        recorded = {}

        class _FakeClient:
            def __init__(self, servers):
                recorded["servers"] = servers

            async def get_tools(self):
                return ["t1", "t2"]

        import sys
        fake_mod = __import__("types").ModuleType("langchain_mcp_adapters.client")
        fake_mod.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_mod)

        result = tools.load_mcp_tools_sync()
        assert result == ["t1", "t2"]
        assert "fake-server" in recorded["servers"]

    def test_handles_nested_servers_key(self, ws: Path, monkeypatch):
        """Config in the `{servers: {srv: {...}}}` form."""
        (ws / "mcp.json").write_text(
            json.dumps({
                "servers": {"svc": {"url": "http://x", "transport": "sse"}},
            }),
            encoding="utf-8",
        )

        class _FakeClient:
            def __init__(self, servers):
                self.servers = servers

            async def get_tools(self):
                return [f"from-{name}" for name in self.servers]

        import sys
        fake_mod = __import__("types").ModuleType("langchain_mcp_adapters.client")
        fake_mod.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_mod)

        assert tools.load_mcp_tools_sync() == ["from-svc"]

    def test_failed_server_connection_returns_empty(self, ws: Path, monkeypatch):
        (ws / "mcp.json").write_text(
            json.dumps({"bad": {"command": "echo", "transport": "stdio"}}),
            encoding="utf-8",
        )

        class _FakeClient:
            def __init__(self, servers):
                pass

            async def get_tools(self):
                raise RuntimeError("boom")

        import sys
        fake_mod = __import__("types").ModuleType("langchain_mcp_adapters.client")
        fake_mod.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_mod)

        # Must not raise — we warn and return empty.
        assert tools.load_mcp_tools_sync() == []


# ---------------------------------------------------------------------------
# build_runtime_tools composition
# ---------------------------------------------------------------------------

class TestBuildRuntimeTools:
    def test_includes_bash_by_default(self, ws: Path):
        out = tools.build_runtime_tools()
        names = [getattr(t, "name", None) for t in out]
        assert "bash" in names

    def test_excludes_bash_when_disabled(self, ws: Path, monkeypatch):
        monkeypatch.setenv("THESIS_NO_SHELL", "1")
        out = tools.build_runtime_tools()
        names = [getattr(t, "name", None) for t in out]
        assert "bash" not in names

    def test_composes_bash_plus_mcp(self, ws: Path, monkeypatch):
        (ws / "mcp.json").write_text(
            json.dumps({"s": {"command": "x", "transport": "stdio"}}),
            encoding="utf-8",
        )

        class _FakeClient:
            def __init__(self, servers):
                pass

            async def get_tools(self):
                return ["mcp-tool-a", "mcp-tool-b"]

        import sys
        fake_mod = __import__("types").ModuleType("langchain_mcp_adapters.client")
        fake_mod.MultiServerMCPClient = _FakeClient
        monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", fake_mod)

        out = tools.build_runtime_tools()
        # bash plus the two mcp strings
        assert "mcp-tool-a" in out
        assert "mcp-tool-b" in out
        assert any(getattr(t, "name", None) == "bash" for t in out)
