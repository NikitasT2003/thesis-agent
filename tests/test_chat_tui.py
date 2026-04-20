"""Claude-Code-style TUI tests for `thesis chat`.

Covers the additions beyond the minimal REPL:
  * /help, /status, /model, /clear, /thread, /history slash commands
  * Multi-line input via trailing `\\` and fenced ``` blocks
  * Tool calls rendered inline during streaming
  * Markdown-rendered assistant replies
  * --quiet flag suppresses tool-call traces
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thesis_agent import cli

runner = CliRunner()


# ---------------------------------------------------------------------------
# Stub agent that supports both invoke() and stream()
# ---------------------------------------------------------------------------

class _StreamStub:
    """Stream-aware stub. Each user turn yields: human → optional tool calls
    + tool results → final AIMessage."""

    def __init__(self, reply: str = "ok", tool_calls: list[dict] | None = None):
        self.calls: list[tuple[str, str]] = []
        self._reply = reply
        self._tool_calls = tool_calls or []

    def invoke(self, payload, *, config=None):
        msg = payload["messages"][-1]["content"]
        tid = (config or {}).get("configurable", {}).get("thread_id", "?")
        self.calls.append((msg, tid))
        from langchain_core.messages import AIMessage, HumanMessage
        human = HumanMessage(content=msg)
        return {"messages": [human, AIMessage(content=self._reply)]}

    def stream(self, payload, *, config=None, stream_mode=None):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        msg = payload["messages"][-1]["content"]
        tid = (config or {}).get("configurable", {}).get("thread_id", "?")
        self.calls.append((msg, tid))
        human = HumanMessage(content=msg)
        state = [human]
        yield {"messages": list(state)}
        for tc in self._tool_calls:
            # `_result` is test-fixture metadata; don't send it to LangChain.
            result_text = tc.get("_result", "ok")
            tool_call_payload = {
                k: v for k, v in tc.items() if k != "_result"
            }
            tool_call_payload.setdefault("type", "tool_call")
            state.append(AIMessage(content="", tool_calls=[tool_call_payload]))
            yield {"messages": list(state)}
            state.append(ToolMessage(
                content=result_text,
                tool_call_id=tool_call_payload.get("id", "x"),
            ))
            yield {"messages": list(state)}
        state.append(AIMessage(content=self._reply))
        yield {"messages": list(state)}


def _patch_build_agent(monkeypatch, stub):
    @contextmanager
    def fake_builder(*a, **kw):
        yield stub

    monkeypatch.setattr("thesis_agent.agent.build_agent", fake_builder)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for v in ("THESIS_PROVIDER", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    # Wide console so Rich panels don't truncate under CliRunner
    from rich.console import Console
    monkeypatch.setattr(cli, "console", Console(
        width=240, force_terminal=False, legacy_windows=False, soft_wrap=False,
    ))
    runner.invoke(cli.app, ["init"])
    return tmp_path


# ---------------------------------------------------------------------------
# Banner + /help
# ---------------------------------------------------------------------------

class TestBannerAndHelp:
    def test_banner_shows_on_entry(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(cli.app, ["chat"], input="/quit\n")
        assert result.exit_code == 0
        assert "thesis-agent chat" in result.stdout
        assert "/help" in result.stdout  # banner lists slash cmds

    def test_slash_help_reprints_banner(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(cli.app, ["chat"], input="/help\n/quit\n")
        assert result.exit_code == 0
        # Banner appears at least twice: initial + /help
        assert result.stdout.count("thesis-agent chat") >= 2


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

class TestSlashCommands:
    def test_status_reports_counts(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        # Seed some content
        (ws / "research" / "raw" / "a.md").write_text("x", encoding="utf-8")
        (ws / "research" / "wiki" / "sources" / "b.md").write_text("y", encoding="utf-8")
        result = runner.invoke(cli.app, ["chat"], input="/status\n/quit\n")
        assert result.exit_code == 0
        out = result.stdout
        assert "thread:" in out
        assert "raw:" in out
        assert "wiki:" in out

    def test_model_shows_three_roles(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(cli.app, ["chat"], input="/model\n/quit\n")
        assert result.exit_code == 0
        out = result.stdout
        assert "drafter" in out
        assert "curator" in out
        assert "researcher" in out

    def test_thread_without_arg_prints_current(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(
            cli.app, ["chat", "--thread", "t-xyz"], input="/thread\n/quit\n"
        )
        assert result.exit_code == 0
        assert "t-xyz" in result.stdout

    def test_thread_with_arg_switches(self, ws: Path, monkeypatch):
        stub = _StreamStub()
        _patch_build_agent(monkeypatch, stub)
        runner.invoke(
            cli.app, ["chat", "--thread", "t-a"],
            input="first\n/thread t-b\nsecond\n/quit\n",
        )
        assert len(stub.calls) == 2
        assert stub.calls[0][1] == "t-a"
        assert stub.calls[1][1] == "t-b"
        # Persisted
        assert (ws / "data" / ".thread").read_text(encoding="utf-8").strip() == "t-b"

    def test_clear_does_not_exit(self, ws: Path, monkeypatch):
        stub = _StreamStub(reply="after clear")
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(
            cli.app, ["chat"], input="/clear\nhello\n/quit\n"
        )
        assert result.exit_code == 0
        # Turn after /clear still went through
        assert len(stub.calls) == 1
        assert stub.calls[0][0] == "hello"

    def test_unknown_slash_reported(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(
            cli.app, ["chat"], input="/bogus\n/quit\n"
        )
        assert result.exit_code == 0
        assert "unknown command" in result.stdout.lower()

    def test_history_acknowledged(self, ws: Path, monkeypatch):
        _patch_build_agent(monkeypatch, _StreamStub())
        result = runner.invoke(
            cli.app, ["chat"], input="/history 5\n/quit\n"
        )
        assert result.exit_code == 0
        assert "thread" in result.stdout.lower()
        assert "checkpoint" in result.stdout.lower() or "history" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Multi-line input
# ---------------------------------------------------------------------------

class TestMultiLineInput:
    def test_backslash_continuation(self, ws: Path, monkeypatch):
        stub = _StreamStub()
        _patch_build_agent(monkeypatch, stub)
        # "first line \\" + "second line" → one message
        runner.invoke(
            cli.app, ["chat"],
            input="first line \\\nsecond line\n/quit\n",
        )
        assert len(stub.calls) == 1
        combined = stub.calls[0][0]
        assert "first line" in combined
        assert "second line" in combined
        # joined on newline (not trailing backslash)
        assert "\\" not in combined

    def test_fenced_block(self, ws: Path, monkeypatch):
        stub = _StreamStub()
        _patch_build_agent(monkeypatch, stub)
        runner.invoke(
            cli.app, ["chat"],
            input="```\nline one\nline two\nline three\n```\n/quit\n",
        )
        assert len(stub.calls) == 1
        msg = stub.calls[0][0]
        assert "line one" in msg
        assert "line two" in msg
        assert "line three" in msg


# ---------------------------------------------------------------------------
# Streaming + tool-call rendering
# ---------------------------------------------------------------------------

class TestStreamingRender:
    def test_tool_call_name_visible_inline(self, ws: Path, monkeypatch):
        stub = _StreamStub(
            reply="done",
            tool_calls=[{
                "name": "read_file",
                "args": {"file_path": "/research/wiki/index.md"},
                "id": "c1",
                "_result": "# Wiki Index\n…",
            }],
        )
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(cli.app, ["chat"], input="go\n/quit\n")
        assert result.exit_code == 0
        out = result.stdout
        # Tool name + key args shown
        assert "read_file" in out
        assert "/research/wiki/index.md" in out
        # Tool result preview shown (↳ marker)
        assert "Wiki Index" in out
        # Final assistant reply rendered
        assert "done" in out

    def test_final_reply_rendered(self, ws: Path, monkeypatch):
        stub = _StreamStub(reply="## Heading\n\n**bold**")
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(cli.app, ["chat"], input="go\n/quit\n")
        assert result.exit_code == 0
        # Markdown's rendered output keeps the literal text readable
        # (bold turns into terminal codes but the word stays).
        assert "Heading" in result.stdout
        assert "bold" in result.stdout

    def test_quiet_flag_hides_tool_calls(self, ws: Path, monkeypatch):
        stub = _StreamStub(
            reply="done",
            tool_calls=[{
                "name": "read_file",
                "args": {"file_path": "/secret"},
                "id": "c1",
                "_result": "sensitive",
            }],
        )
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(cli.app, ["chat", "--quiet"], input="go\n/quit\n")
        assert result.exit_code == 0
        out = result.stdout
        # Tool call + result hidden in quiet mode
        assert "read_file" not in out
        assert "sensitive" not in out
        # Final reply still shown
        assert "done" in out


# ---------------------------------------------------------------------------
# Helper-level tests (unit, no CliRunner)
# ---------------------------------------------------------------------------

class TestPreviewHelpers:
    def test_preview_tool_args_prefers_file_path(self):
        out = cli._preview_tool_args("read_file", {"file_path": "/a/b.md", "offset": 0})
        assert "file_path" in out
        assert "/a/b.md" in out

    def test_preview_tool_args_truncates_long_values(self):
        out = cli._preview_tool_args("edit_file", {"file_path": "x" * 200})
        assert len(out) <= 120

    def test_preview_tool_result_collapses_newlines(self):
        out = cli._preview_tool_result("line1\nline2\nline3")
        assert "\n" not in out
        assert "line1" in out and "line3" in out

    def test_preview_tool_result_truncates(self):
        long = "x" * 500
        out = cli._preview_tool_result(long)
        assert len(out) <= 120
        assert out.endswith("…") or out.endswith("...")
