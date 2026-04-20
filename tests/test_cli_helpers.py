"""Unit tests for CLI helper functions (not the full wizard flow)."""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent import cli
from thesis_agent.config import paths

# ---------------------------------------------------------------------------
# _humanise_error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,hint",
    [
        ("401 Unauthorized: invalid api key", "rejected"),
        ("Authentication failed", "rejected"),
        ("insufficient credit — add a payment method", "credits"),
        ("429 Too Many Requests", "rate-limited"),
        ("402 payment required", "credits"),
        ("Connection timed out", "internet"),
        ("model 'nope' not found", "not found"),
    ],
)
def test_humanise_error_translates_common_errors(raw: str, hint: str):
    msg = cli._humanise_error(raw)
    assert hint in msg.lower()


def test_humanise_error_truncates_unknown():
    long_err = "X" * 500
    out = cli._humanise_error(long_err)
    assert len(out) <= 200


# ---------------------------------------------------------------------------
# _read_env_var / _write_env
# ---------------------------------------------------------------------------

class TestEnvIO:
    def test_read_env_var_missing_file_returns_none(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert cli._read_env_var("ANYTHING") is None

    def test_read_env_var_with_quotes_and_spaces(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            'ANTHROPIC_API_KEY="sk-ant-xxx"\nOTHER=  value  \n',
            encoding="utf-8",
        )
        assert cli._read_env_var("ANTHROPIC_API_KEY") == "sk-ant-xxx"

    def test_write_env_adds_new_keys(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli._write_env({"THESIS_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k1"})
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "THESIS_PROVIDER=anthropic" in env
        assert "ANTHROPIC_API_KEY=k1" in env

    def test_write_env_replaces_existing_keys(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "ANTHROPIC_API_KEY=old\nKEEP_ME=yes\n", encoding="utf-8"
        )
        cli._write_env({"ANTHROPIC_API_KEY": "new"})
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY=new" in env
        assert "old" not in env
        assert "KEEP_ME=yes" in env  # unrelated lines preserved

    def test_write_env_empty_values_skipped(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli._write_env({"A": "hello", "B": "", "C": "world"})
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "A=hello" in env
        assert "C=world" in env
        assert "B=" not in env


# ---------------------------------------------------------------------------
# _copy_examples
# ---------------------------------------------------------------------------

class TestCopyExamples:
    def test_copy_examples_does_not_overwrite(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = paths()
        p.raw.mkdir(parents=True)
        # Pre-existing file — must not be overwritten
        pre = p.raw / "example-source.md"
        pre.write_text("MINE", encoding="utf-8")
        cli._copy_examples()
        assert pre.read_text(encoding="utf-8") == "MINE"

    def test_copy_examples_returns_count(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = paths()
        for d in (p.raw, p.style_samples, p.thesis_dir):
            d.mkdir(parents=True, exist_ok=True)
        n = cli._copy_examples()
        assert n >= 1  # at least the example source


# ---------------------------------------------------------------------------
# _ensure_workspace
# ---------------------------------------------------------------------------

class TestEnsureWorkspace:
    def test_creates_all_required_dirs(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli._ensure_workspace()
        assert (tmp_path / "research" / "raw").is_dir()
        assert (tmp_path / "research" / "wiki").is_dir()
        assert (tmp_path / "style" / "samples").is_dir()
        assert (tmp_path / "thesis" / "chapters").is_dir()
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "research" / "raw" / "urls.txt").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert (tmp_path / "thesis" / "outline.md").exists()

    def test_does_not_overwrite_agents_md_by_default(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("MINE", encoding="utf-8")
        cli._ensure_workspace(force=False)
        assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "MINE"

    def test_force_overwrites_agents_md(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "AGENTS.md").write_text("MINE", encoding="utf-8")
        cli._ensure_workspace(force=True)
        content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        assert content != "MINE"

    def test_idempotent_second_call_no_crash(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli._ensure_workspace()
        cli._ensure_workspace()
        # No assertion needed — second call must not raise.


# ---------------------------------------------------------------------------
# `thesis ingest` command (pure Python, no LLM)
# ---------------------------------------------------------------------------

from typer.testing import CliRunner  # noqa: E402

runner = CliRunner()


class TestIngestCommand:
    def test_ingest_on_missing_dir_exits_nonzero(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli.app, ["ingest", str(tmp_path / "nope")])
        assert result.exit_code != 0
        assert "no such directory" in result.stdout.lower()

    def test_ingest_on_empty_raw_exits_zero(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        result = runner.invoke(cli.app, ["ingest"])
        assert result.exit_code == 0
        assert "added 0" in result.stdout.lower() or "no sources" in result.stdout.lower()

    def test_ingest_happy_path_on_md_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        (tmp_path / "research" / "raw" / "note.md").write_text(
            "# Title\n\nbody\n", encoding="utf-8"
        )
        result = runner.invoke(cli.app, ["ingest"])
        assert result.exit_code == 0
        assert (tmp_path / "research" / "raw" / "note.md.md").exists()
        assert (tmp_path / "research" / "raw" / "_index.json").exists()
