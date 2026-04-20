"""CLI surface tests — help, init, status. No LLM calls."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from thesis_agent.cli import app

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("setup", "init", "status", "ingest", "chat"):
        assert cmd in result.stdout


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "thesis-agent" in result.stdout


def test_init_creates_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "research" / "raw").is_dir()
    assert (tmp_path / "research" / "wiki").is_dir()
    assert (tmp_path / "style" / "samples").is_dir()
    assert (tmp_path / "thesis" / "chapters").is_dir()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "research" / "raw" / "urls.txt").exists()
    assert (tmp_path / "thesis" / "outline.md").exists()


def test_status_after_init(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "workspace" in result.stdout.lower()
