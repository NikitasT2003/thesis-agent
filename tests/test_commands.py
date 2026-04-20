"""End-to-end behavioural tests for every `thesis` subcommand.

Goal: every command must have:
  * --help smoke (it exists, prints, exits 0)
  * happy path (expected files/effects/stdout)
  * error path (missing input, agent failure, bad args)
  * thread-id persistence for agent-backed commands

Agent-invoking commands mock `thesis_agent.agent.invoke` so tests run
offline. `chat` mocks `thesis_agent.agent.build_agent` as a context manager
returning a stub agent.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thesis_agent import cli

runner = CliRunner()


# ---------------------------------------------------------------------------
# Shared fixture + helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    """Isolated workspace; any Anthropic/OpenRouter keys cleared.

    Also replaces cli.console with a wide one so Rich tables don't truncate
    under CliRunner's tiny default terminal size.
    """
    monkeypatch.chdir(tmp_path)
    for v in (
        "THESIS_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
    ):
        monkeypatch.delenv(v, raising=False)

    from rich.console import Console

    wide = Console(width=240, force_terminal=False, legacy_windows=False, soft_wrap=False)
    monkeypatch.setattr(cli, "console", wide)
    return tmp_path


def _init(ws: Path):
    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0, result.stdout
    return result


def _record_invoke(monkeypatch, reply: str = "ok") -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def fake_invoke(prompt: str, *, thread_id: str, p=None):
        seen.append((prompt, thread_id))
        return reply

    monkeypatch.setattr("thesis_agent.agent.invoke", fake_invoke)
    return seen


# ---------------------------------------------------------------------------
# Top-level flags
# ---------------------------------------------------------------------------

class TestTopLevel:
    def test_no_args_prints_help(self):
        result = runner.invoke(cli.app, [])
        assert result.exit_code == 0
        assert "setup" in result.stdout
        assert "ingest" in result.stdout

    def test_help_lists_every_command(self):
        result = runner.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        for cmd in (
            "setup", "init", "status", "ingest",
            "curate", "style", "write", "lint", "chat",
        ):
            assert cmd in result.stdout, f"missing command in --help: {cmd}"

    def test_version_flag(self):
        result = runner.invoke(cli.app, ["--version"])
        assert result.exit_code == 0
        assert "thesis-agent" in result.stdout


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

class TestSetup:
    def test_help(self, ws: Path):
        result = runner.invoke(cli.app, ["setup", "--help"])
        assert result.exit_code == 0
        for flag in ("--non-interactive", "--provider", "--api-key",
                     "--skip-validation", "--skip-examples", "--quickstart", "--force"):
            assert flag in result.stdout

    def test_non_interactive_anthropic(self, ws: Path):
        result = runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "anthropic",
            "--api-key", "sk-ant-xyz",
            "--skip-validation", "--skip-examples",
        ])
        assert result.exit_code == 0, result.stdout
        env = (ws / ".env").read_text(encoding="utf-8")
        assert "THESIS_PROVIDER=anthropic" in env
        assert "ANTHROPIC_API_KEY=sk-ant-xyz" in env

    def test_non_interactive_openrouter(self, ws: Path):
        result = runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "openrouter",
            "--api-key", "sk-or-abc",
            "--skip-validation", "--skip-examples",
        ])
        assert result.exit_code == 0, result.stdout
        env = (ws / ".env").read_text(encoding="utf-8")
        assert "THESIS_PROVIDER=openrouter" in env
        assert "OPENROUTER_API_KEY=sk-or-abc" in env

    def test_non_interactive_bad_provider_exits_2(self, ws: Path):
        result = runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "mistral",
            "--api-key", "x",
            "--skip-validation",
        ])
        assert result.exit_code == 2

    def test_creates_workspace_even_when_skipping_examples(self, ws: Path):
        runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "anthropic", "--api-key", "sk-ant-x",
            "--skip-validation", "--skip-examples",
        ])
        for sub in ("research/raw", "research/wiki", "style/samples", "thesis/chapters", "data"):
            assert (ws / sub).is_dir()

    def test_does_not_copy_examples_when_skipped(self, ws: Path):
        runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "anthropic", "--api-key", "sk-ant-x",
            "--skip-validation", "--skip-examples",
        ])
        assert not (ws / "research" / "raw" / "example-source.md").exists()
        assert not (ws / "style" / "samples" / "sample-essay.md").exists()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

class TestInit:
    def test_help(self, ws: Path):
        result = runner.invoke(cli.app, ["init", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.stdout

    def test_scaffolds_empty_workspace(self, ws: Path):
        result = runner.invoke(cli.app, ["init"])
        assert result.exit_code == 0
        assert "workspace initialised" in result.stdout.lower()

    def test_idempotent(self, ws: Path):
        runner.invoke(cli.app, ["init"])
        result = runner.invoke(cli.app, ["init"])
        assert result.exit_code == 0

    def test_preserves_existing_agents_md_without_force(self, ws: Path):
        (ws / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
        runner.invoke(cli.app, ["init"])
        assert (ws / "AGENTS.md").read_text(encoding="utf-8") == "# mine\n"

    def test_force_rewrites_agents_md(self, ws: Path):
        (ws / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
        runner.invoke(cli.app, ["init", "--force"])
        assert (ws / "AGENTS.md").read_text(encoding="utf-8") != "# mine\n"

    def test_creates_outline_stub(self, ws: Path):
        runner.invoke(cli.app, ["init"])
        outline = (ws / "thesis" / "outline.md").read_text(encoding="utf-8")
        for heading in ("Introduction", "Background", "Method", "Results", "Discussion", "Conclusion"):
            assert heading in outline

    def test_creates_urls_txt_with_instructions(self, ws: Path):
        runner.invoke(cli.app, ["init"])
        urls = (ws / "research" / "raw" / "urls.txt").read_text(encoding="utf-8")
        assert "# " in urls  # has comment instructions


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_help(self, ws: Path):
        result = runner.invoke(cli.app, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_empty_workspace(self, ws: Path):
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0
        # Reports paths that don't exist yet as "no"
        assert "no" in result.stdout.lower()

    def test_status_after_init_exits_zero(self, ws: Path):
        # Rich tables in CliRunner's captive stdout can collapse to frames-only
        # output; assert on exit code + command did not raise.
        _init(ws)
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0

    def test_status_does_not_mutate_workspace(self, ws: Path):
        _init(ws)
        before = sorted(p.name for p in ws.rglob("*"))
        runner.invoke(cli.app, ["status"])
        after = sorted(p.name for p in ws.rglob("*"))
        assert before == after

    def test_status_runs_without_env_key(self, ws: Path):
        # status is pure Python — no LLM, no key required
        _init(ws)
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0

    def test_status_reads_current_thread(self, ws: Path):
        _init(ws)
        # Seed the thread file; status should not crash
        (ws / "data" / ".thread").write_text("t-xyz", encoding="utf-8")
        result = runner.invoke(cli.app, ["status"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_help(self, ws: Path):
        result = runner.invoke(cli.app, ["ingest", "--help"])
        assert result.exit_code == 0

    def test_ingest_default_dir(self, ws: Path):
        _init(ws)
        (ws / "research" / "raw" / "n.md").write_text("# x\n", encoding="utf-8")
        result = runner.invoke(cli.app, ["ingest"])
        assert result.exit_code == 0
        assert (ws / "research" / "raw" / "n.md.md").exists()

    def test_ingest_explicit_dir(self, ws: Path):
        custom = ws / "mydocs"
        custom.mkdir()
        (custom / "p.md").write_text("hello", encoding="utf-8")
        result = runner.invoke(cli.app, ["ingest", str(custom)])
        assert result.exit_code == 0
        assert (custom / "p.md.md").exists()

    def test_ingest_missing_dir_exits_1(self, ws: Path):
        result = runner.invoke(cli.app, ["ingest", str(ws / "nope")])
        assert result.exit_code == 1
        assert "no such directory" in result.stdout.lower()

    def test_ingest_idempotent_skip(self, ws: Path):
        _init(ws)
        (ws / "research" / "raw" / "p.md").write_text("once", encoding="utf-8")
        runner.invoke(cli.app, ["ingest"])
        result = runner.invoke(cli.app, ["ingest"])
        assert "skipped 1" in result.stdout.lower()

    def test_ingest_on_init_with_no_sources(self, ws: Path):
        _init(ws)
        result = runner.invoke(cli.app, ["ingest"])
        assert result.exit_code == 0
        assert "no sources" in result.stdout.lower() or "added 0" in result.stdout.lower()

    def test_ingest_does_not_require_env_key(self, ws: Path):
        """Ingest is pure Python — must work without an API key."""
        _init(ws)
        (ws / "research" / "raw" / "p.md").write_text("x", encoding="utf-8")
        result = runner.invoke(cli.app, ["ingest"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# curate / style / write / lint  (agent-dispatch commands)
# ---------------------------------------------------------------------------

class TestAgentCommands:
    @pytest.mark.parametrize("cmd", ["curate", "style", "write", "lint"])
    def test_each_has_help(self, ws: Path, cmd: str):
        args = ["write", "1.1"] if cmd == "write" else [cmd]
        # --help bypasses any required args
        result = runner.invoke(cli.app, [cmd, "--help"])
        assert result.exit_code == 0
        _ = args

    def test_curate_prompt_mentions_pending_and_status(self, ws: Path, monkeypatch):
        _init(ws)
        seen = _record_invoke(monkeypatch)
        result = runner.invoke(cli.app, ["curate"])
        assert result.exit_code == 0, result.stdout
        prompt, _ = seen[0]
        assert "pending" in prompt.lower()
        assert "status" in prompt.lower() or "_index.json" in prompt

    def test_style_prompt_mentions_samples_and_styleguide(self, ws: Path, monkeypatch):
        _init(ws)
        seen = _record_invoke(monkeypatch)
        runner.invoke(cli.app, ["style"])
        prompt, _ = seen[0]
        assert "style/samples" in prompt
        assert "STYLE.md" in prompt

    def test_write_requires_section_argument(self, ws: Path):
        _init(ws)
        result = runner.invoke(cli.app, ["write"])
        assert result.exit_code != 0  # missing required arg

    def test_write_carries_section_through(self, ws: Path, monkeypatch):
        _init(ws)
        seen = _record_invoke(monkeypatch)
        runner.invoke(cli.app, ["write", "3.2"])
        assert "3.2" in seen[0][0]
        assert "thesis/chapters" in seen[0][0]

    def test_lint_defaults_to_all_chapters(self, ws: Path, monkeypatch):
        _init(ws)
        seen = _record_invoke(monkeypatch)
        runner.invoke(cli.app, ["lint"])
        prompt = seen[0][0]
        assert "thesis/chapters" in prompt

    def test_lint_specific_file_passed(self, ws: Path, monkeypatch):
        _init(ws)
        target = ws / "thesis" / "chapters" / "03.md"
        target.write_text("# 3\n", encoding="utf-8")
        seen = _record_invoke(monkeypatch)
        runner.invoke(cli.app, ["lint", str(target)])
        assert "03.md" in seen[0][0] or str(target) in seen[0][0]

    @pytest.mark.parametrize("cmd,extra", [
        ("curate", []),
        ("style", []),
        ("write", ["2.1"]),
        ("lint", []),
    ])
    def test_thread_flag_persists_per_command(self, ws: Path, monkeypatch, cmd, extra):
        _init(ws)
        _record_invoke(monkeypatch)
        runner.invoke(cli.app, [cmd, *extra, "--thread", f"t-{cmd}"])
        assert (ws / "data" / ".thread").read_text(encoding="utf-8").strip() == f"t-{cmd}"

    @pytest.mark.parametrize("cmd,extra", [
        ("curate", []), ("style", []), ("write", ["1.1"]), ("lint", []),
    ])
    def test_agent_error_reported_and_nonzero(self, ws: Path, monkeypatch, cmd, extra):
        _init(ws)

        def raiser(*a, **kw):
            raise RuntimeError("oops")

        monkeypatch.setattr("thesis_agent.agent.invoke", raiser)
        result = runner.invoke(cli.app, [cmd, *extra])
        assert result.exit_code != 0
        assert "oops" in result.stdout or "agent error" in result.stdout.lower()

    def test_commands_use_persisted_thread_when_flag_absent(self, ws: Path, monkeypatch):
        _init(ws)
        seen = _record_invoke(monkeypatch)
        # First run sets persisted id
        runner.invoke(cli.app, ["curate", "--thread", "t-shared"])
        # Second run without flag should reuse
        runner.invoke(cli.app, ["lint"])
        _, tid1 = seen[0]
        _, tid2 = seen[1]
        assert tid1 == "t-shared"
        assert tid2 == "t-shared"


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

class _StubAgent:
    """Mimics the deepagents agent: .invoke returns a messages list dict."""

    def __init__(self, reply: str = "hello"):
        self.calls: list[tuple[str, str]] = []
        self._reply = reply

    def invoke(self, payload: dict, *, config=None):
        msg = payload["messages"][-1]["content"]
        tid = (config or {}).get("configurable", {}).get("thread_id", "?")
        self.calls.append((msg, tid))
        return {"messages": [{"role": "assistant", "content": self._reply}]}


def _patch_build_agent(monkeypatch, stub: _StubAgent):
    @contextmanager
    def fake_builder(*a, **kw):
        yield stub

    monkeypatch.setattr("thesis_agent.agent.build_agent", fake_builder)


class TestChat:
    def test_help(self, ws: Path):
        result = runner.invoke(cli.app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--thread" in result.stdout
        assert "--new" in result.stdout

    def test_single_turn_and_quit(self, ws: Path, monkeypatch):
        _init(ws)
        stub = _StubAgent(reply="hi back")
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(cli.app, ["chat"], input="hello\n/quit\n")
        assert result.exit_code == 0, result.stdout
        assert "hi back" in result.stdout
        assert len(stub.calls) == 1
        assert stub.calls[0][0] == "hello"

    def test_empty_input_skipped(self, ws: Path, monkeypatch):
        _init(ws)
        stub = _StubAgent()
        _patch_build_agent(monkeypatch, stub)
        # Three blank lines then /quit → no calls made
        runner.invoke(cli.app, ["chat"], input="\n\n\n/quit\n")
        assert stub.calls == []

    def test_slash_new_starts_fresh_thread(self, ws: Path, monkeypatch):
        _init(ws)
        stub = _StubAgent()
        _patch_build_agent(monkeypatch, stub)
        runner.invoke(
            cli.app,
            ["chat", "--thread", "t-original"],
            input="first\n/new\nsecond\n/quit\n",
        )
        # /new should have rotated the thread id between calls
        assert len(stub.calls) == 2
        tid_1 = stub.calls[0][1]
        tid_2 = stub.calls[1][1]
        assert tid_1 == "t-original"
        assert tid_2 != tid_1
        assert tid_2.startswith("t-")

    def test_new_flag_rotates_thread(self, ws: Path, monkeypatch):
        _init(ws)
        stub = _StubAgent()
        _patch_build_agent(monkeypatch, stub)
        # First run with --new creates a new t-<timestamp>
        runner.invoke(cli.app, ["chat", "--new"], input="/quit\n")
        persisted = (ws / "data" / ".thread").read_text(encoding="utf-8").strip()
        assert persisted.startswith("t-")

    def test_agent_error_surfaces_then_loop_continues(self, ws: Path, monkeypatch):
        _init(ws)

        class Flaky:
            def __init__(self):
                self.n = 0

            def invoke(self, payload, *, config=None):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("boom")
                return {"messages": [{"role": "assistant", "content": "recovered"}]}

        flaky = Flaky()
        _patch_build_agent(monkeypatch, flaky)
        result = runner.invoke(cli.app, ["chat"], input="bad\ngood\n/quit\n")
        assert result.exit_code == 0
        assert "boom" in result.stdout or "agent error" in result.stdout.lower()
        assert "recovered" in result.stdout

    def test_exit_alias_works(self, ws: Path, monkeypatch):
        _init(ws)
        stub = _StubAgent()
        _patch_build_agent(monkeypatch, stub)
        result = runner.invoke(cli.app, ["chat"], input="/exit\n")
        assert result.exit_code == 0
