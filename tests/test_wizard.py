"""Wizard path tests — mock questionary so we can verify every branch without a TTY.

Covers the behaviours the user's brother / OSS audience are most likely to hit:
  - Providing a key via --api-key flag
  - Re-using an existing .env key (answer Yes)
  - Refusing an existing .env key then entering a new one (answer No)
  - Empty-enter then "skip for now"
  - Three empty entries auto-skip
  - Bad-prefix key then "use anyway"
  - Bad-prefix key then "skip"
  - --non-interactive with missing key exits cleanly
  - Ctrl-C at any prompt raises _Cancelled and writes nothing
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from thesis_agent import cli

runner = CliRunner()


class _Prompt:
    """Stand-in for a questionary prompt: .ask() returns a queued answer."""

    def __init__(self, answers: list[Any]):
        self._answers = answers

    def ask(self):
        if not self._answers:
            raise AssertionError("ran out of scripted answers")
        nxt = self._answers.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


class _FakeChoice:
    """Duck-type replacement for questionary.Choice."""

    def __init__(self, label: str, value: Any = None):
        self.title = label
        self.value = value if value is not None else label

    def __eq__(self, other):
        return isinstance(other, _FakeChoice) and self.value == other.value

    def __hash__(self):
        return hash(self.value)


class FakeQuestionary:
    """Scripts every questionary call in order. Any unexpected call fails loudly."""

    Choice = _FakeChoice

    def __init__(self, script: list[Any]):
        self._script = script

    def _next(self) -> Any:
        return _Prompt([self._script.pop(0)])

    # Called with (message, choices=..., default=...) -> Prompt
    def select(self, *args, **kwargs):  # noqa: D401
        return self._next()

    def confirm(self, *args, **kwargs):
        return self._next()

    def password(self, *args, **kwargs):
        return self._next()

    def text(self, *args, **kwargs):
        return self._next()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Ensure a clean shell env.
    for var in (
        "THESIS_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_SITE_NAME",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _patch_questionary(monkeypatch, script: list[Any]) -> FakeQuestionary:
    fake = FakeQuestionary(script)
    # Insert the fake module globally (wizard does `import questionary` lazily).
    import sys

    monkeypatch.setitem(sys.modules, "questionary", fake)
    return fake


def _no_real_calls(monkeypatch):
    """Neutralise validation + example copying so tests run offline and fast."""
    monkeypatch.setattr(cli, "_validate_key", lambda *a, **kw: (True, "ok"))
    monkeypatch.setattr(cli, "_copy_examples", lambda: 0)


# ---------------------------------------------------------------------------
# Non-interactive paths
# ---------------------------------------------------------------------------

def test_non_interactive_with_flags_writes_env(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    result = runner.invoke(
        cli.app,
        [
            "setup",
            "--non-interactive",
            "--provider", "openrouter",
            "--api-key", "sk-or-aaa",
            "--skip-validation",
            "--skip-examples",
        ],
    )
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "THESIS_PROVIDER=openrouter" in env
    assert "OPENROUTER_API_KEY=sk-or-aaa" in env


def test_non_interactive_missing_key_exits(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    result = runner.invoke(
        cli.app,
        ["setup", "--non-interactive", "--provider", "anthropic"],
    )
    assert result.exit_code != 0
    assert "required for --non-interactive" in result.stdout.lower() or \
           "no anthropic_api_key" in result.stdout.lower()


def test_non_interactive_bad_provider_exits(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    result = runner.invoke(
        cli.app,
        ["setup", "--non-interactive", "--provider", "bogus", "--api-key", "x"],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Reuse-existing paths
# ---------------------------------------------------------------------------

def test_reuse_existing_key_yes(workspace: Path, monkeypatch):
    """Existing .env has a key; user answers Yes to reuse."""
    _no_real_calls(monkeypatch)
    (workspace / ".env").write_text(
        "THESIS_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-ant-existing\n",
        encoding="utf-8",
    )
    _patch_questionary(monkeypatch, [
        "anthropic",  # provider select
        True,                                          # "use existing?"  → yes
        True,                                          # "create workspace?" → yes
        False,                                         # "copy examples?" → no
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-existing" in env


def test_reuse_existing_key_no_then_enter_new(workspace: Path, monkeypatch):
    """User answers No to reuse, then enters a fresh key. Regression: the
    `No` path used to feel broken because no transition was shown."""
    _no_real_calls(monkeypatch)
    (workspace / ".env").write_text(
        "THESIS_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-ant-old\n",
        encoding="utf-8",
    )
    _patch_questionary(monkeypatch, [
        "anthropic",   # provider
        False,                                         # use existing? → no
        "sk-ant-new",                                  # password prompt
        True,                                          # create workspace?
        False,                                         # copy examples?
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-new" in env
    assert "sk-ant-old" not in env


# ---------------------------------------------------------------------------
# Retry loop paths
# ---------------------------------------------------------------------------

def test_empty_then_skip(workspace: Path, monkeypatch):
    """User enters blank, then selects 'skip for now'."""
    _no_real_calls(monkeypatch)
    _patch_questionary(monkeypatch, [
        "anthropic",   # provider
        "",                                            # empty password
        "skip",                                        # what now? → skip
        True,                                          # create workspace?
        False,                                         # copy examples?
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "THESIS_PROVIDER=anthropic" in env
    assert "ANTHROPIC_API_KEY" not in env  # skipped
    assert "No API key saved yet" in result.stdout


def test_three_empty_attempts_auto_skip(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    _patch_questionary(monkeypatch, [
        "anthropic",
        "", "retry",
        "", "retry",
        "",                 # third empty → auto-skip, no menu
        True, False,
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    assert "skipping key entry" in result.stdout.lower()


def test_bad_prefix_then_use_anyway(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    _patch_questionary(monkeypatch, [
        "anthropic",
        "some-custom-key",   # wrong prefix
        True,                # "use anyway?" → yes
        True, False,
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=some-custom-key" in env


def test_bad_prefix_then_skip(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    _patch_questionary(monkeypatch, [
        "anthropic",
        "wrong-key",
        False,               # "use anyway?" → no
        "skip",              # what now? → skip
        True, False,
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def test_ctrl_c_writes_nothing(workspace: Path, monkeypatch):
    _no_real_calls(monkeypatch)
    _patch_questionary(monkeypatch, [
        "anthropic",
        None,  # questionary returns None on Ctrl-C → _Cancelled
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 130
    assert not (workspace / ".env").exists()
    assert "cancelled" in result.stdout.lower()


def test_validation_failure_then_save_anyway(workspace: Path, monkeypatch):
    """Validation fails — user picks 'save anyway'."""
    monkeypatch.setattr(cli, "_validate_key", lambda *a, **kw: (False, "401 invalid key"))
    monkeypatch.setattr(cli, "_copy_examples", lambda: 0)
    _patch_questionary(monkeypatch, [
        "anthropic",
        "sk-ant-bad",     # key
        "save",           # validation-fail menu → save anyway
        True, False,
    ])
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.stdout
    env = (workspace / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-bad" in env
    assert "401" in result.stdout or "rejected" in result.stdout.lower()
