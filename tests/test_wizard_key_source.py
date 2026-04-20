"""Wizard must be honest about where an existing key came from.

Context: a user reported the wizard finding an OpenRouter key they were sure
they hadn't set. Investigation showed their shell had `OPENROUTER_API_KEY`
exported from a parent process. The wizard was correct to detect it, but its
output did not distinguish shell env from `.env`, making the key look like a
phantom. These tests lock in the fix: the wizard names the source and shows
a masked preview.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from thesis_agent import cli

runner = CliRunner()


class _Prompt:
    def __init__(self, answers: list[Any]):
        self._answers = answers

    def ask(self):
        if not self._answers:
            raise AssertionError("script exhausted")
        a = self._answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a


class _FakeChoice:
    def __init__(self, label: str, value: Any = None):
        self.title = label
        self.value = value if value is not None else label

    def __eq__(self, other):
        return isinstance(other, _FakeChoice) and self.value == other.value

    def __hash__(self):
        return hash(self.value)


class _FakeQuestionary:
    Choice = _FakeChoice

    def __init__(self, script: list[Any]):
        self._script = script

    def _n(self):
        return _Prompt([self._script.pop(0)])

    def select(self, *a, **k):
        return self._n()

    def confirm(self, *a, **k):
        return self._n()

    def password(self, *a, **k):
        return self._n()

    def text(self, *a, **k):
        return self._n()


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for v in (
        "THESIS_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_SITE_NAME",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(cli, "_validate_key", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(cli, "_copy_examples", lambda **kw: {
        "copied": 0, "overwritten": 0, "already_present": 0, "source_missing": 0,
    })
    # Rich collapses output inside CliRunner's tiny default terminal. Force
    # a wide console so assertions can see the whole transcript.
    from rich.console import Console
    monkeypatch.setattr(cli, "console", Console(
        width=240, force_terminal=False, legacy_windows=False, soft_wrap=False,
    ))
    return tmp_path


def _install_fake_q(monkeypatch, script: list[Any]):
    monkeypatch.setitem(sys.modules, "questionary", _FakeQuestionary(script))


# ---------------------------------------------------------------------------
# _mask_key
# ---------------------------------------------------------------------------

class TestMaskKey:
    def test_openrouter_key_preserves_prefix_and_last_four(self):
        out = cli._mask_key("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")
        assert out.startswith("sk-or-")
        assert out.endswith("c264")
        assert "…" in out
        # Middle must be masked — the long hex body should not appear
        assert "71b768574b63558d" not in out

    def test_anthropic_key_preserves_prefix(self):
        out = cli._mask_key("sk-ant-abcdefghijklmnop")
        assert out.startswith("sk-ant-")
        assert out.endswith("mnop")
        assert "abcdefghij" not in out

    def test_very_short_key_only_reports_length(self):
        out = cli._mask_key("xyz")
        assert "xyz" not in out
        assert "chars" in out

    def test_empty_key(self):
        assert cli._mask_key("") == "<empty>"


# ---------------------------------------------------------------------------
# Source attribution: shell env vs .env
# ---------------------------------------------------------------------------

class TestKeySourceAttribution:
    def test_key_from_shell_env_is_labelled(self, ws: Path, monkeypatch):
        """When shell env has the key, wizard must say 'shell environment'
        so the user knows where the phantom key came from."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-from-shell-xxxx9999")
        _install_fake_q(monkeypatch, [
            "openrouter",   # provider
            True,           # use existing? → yes
            False,          # add attribution headers? → no (bool confirm)
            True,           # create workspace?
            False,          # copy examples?
        ])
        result = runner.invoke(cli.app, ["setup"])
        assert result.exit_code == 0, result.stdout
        assert "shell environment" in result.stdout
        # Masked preview must show — last 4 chars visible, middle hidden
        assert "9999" in result.stdout
        assert "v1-from-shell" not in result.stdout  # body masked

    def test_key_from_env_file_is_labelled(self, ws: Path, monkeypatch):
        """When only .env has the key (no shell env), wizard must say '.env'."""
        (ws / ".env").write_text(
            "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-v1-in-dotenv-1234\n",
            encoding="utf-8",
        )
        _install_fake_q(monkeypatch, [
            "openrouter",
            True,    # use existing
            False,   # attribution headers
            True,    # create ws
            False,   # examples
        ])
        result = runner.invoke(cli.app, ["setup"])
        assert result.exit_code == 0, result.stdout
        assert ".env" in result.stdout
        assert "shell environment" not in result.stdout
        assert "1234" in result.stdout
        assert "in-dotenv" not in result.stdout

    def test_warns_when_shell_and_dotenv_differ(self, ws: Path, monkeypatch):
        """Both sources have (different) values. Wizard must flag the
        mismatch in its initial 'found existing key' line — .env wins
        at runtime, shell export is ignored."""
        (ws / ".env").write_text(
            "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-v1-in-env-aaaa\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-stale-shell-bbbb")
        _install_fake_q(monkeypatch, [
            "openrouter",
            True,    # reuse (the .env one)
            False,   # attribution headers
            True, False,
        ])
        result = runner.invoke(cli.app, ["setup"])
        assert result.exit_code == 0, result.stdout
        out = result.stdout.lower()
        # The mismatch must be flagged and the outcome named.
        assert "shell" in out
        assert "different value" in out
        assert "wins" in out or "ignored" in out

    def test_no_key_anywhere_shows_no_source(self, ws: Path, monkeypatch):
        _install_fake_q(monkeypatch, [
            "anthropic",
            "sk-ant-fresh",
            True, False,
        ])
        result = runner.invoke(cli.app, ["setup"])
        assert result.exit_code == 0, result.stdout
        assert "shell environment" not in result.stdout
        assert "found ANTHROPIC_API_KEY" not in result.stdout

    def test_dotenv_takes_precedence_over_shell_env(self, ws: Path, monkeypatch):
        """When both are present, .env wins — this matches the runtime
        override in `load_env` so the wizard shows the key that will
        actually be used. Previously the wizard said 'shell environment'
        but the agent still failed at runtime because .env was stale."""
        (ws / ".env").write_text(
            "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-v1-in-env-aaaa\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-shell-zzzz1111")
        _install_fake_q(monkeypatch, [
            "openrouter",
            True, False,
            True, False,
        ])
        result = runner.invoke(cli.app, ["setup"])
        assert result.exit_code == 0, result.stdout
        # Source must be .env, not shell.
        assert ".env" in result.stdout
        assert "aaaa" in result.stdout  # .env preview shown
        # Plus a hint that the shell value is different and being ignored.
        assert "different value" in result.stdout.lower() or "ignored" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Non-interactive mode still reuses silently but names the source
# ---------------------------------------------------------------------------

class TestNonInteractiveReuse:
    def test_reuse_message_names_shell_env(self, ws: Path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-ci-env-yyyy9999")
        result = runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "openrouter",
            "--skip-validation", "--skip-examples",
        ])
        assert result.exit_code == 0, result.stdout
        assert "shell environment" in result.stdout
        assert "9999" in result.stdout  # masked preview

    def test_reuse_message_names_env_file(self, ws: Path, monkeypatch):
        (ws / ".env").write_text(
            "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-v1-persisted-wwww0000\n",
            encoding="utf-8",
        )
        result = runner.invoke(cli.app, [
            "setup", "--non-interactive",
            "--provider", "openrouter",
            "--skip-validation", "--skip-examples",
        ])
        assert result.exit_code == 0, result.stdout
        assert ".env file" in result.stdout or "env file" in result.stdout.lower()
        assert "0000" in result.stdout
