"""Copy-examples honesty.

User reported running `thesis setup` → Step 5 → answered "Yes" → wizard
replied "copied 0 example file(s)". The call was correct (targets already
existed) but the report was misleading. These tests lock in the fix:
report copied / overwritten / already-present separately, and expose
`--overwrite-examples` for when users actually want to replace them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from thesis_agent import cli
from thesis_agent.config import paths

runner = CliRunner()


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for v in (
        "THESIS_PROVIDER", "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL",
    ):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# _copy_examples helper direct tests
# ---------------------------------------------------------------------------

class TestCopyExamplesHelper:
    def test_fresh_workspace_copies_files(self, ws: Path):
        p = paths()
        for d in (p.raw, p.style_samples, p.thesis_dir):
            d.mkdir(parents=True, exist_ok=True)
        res = cli._copy_examples()
        assert res["copied"] >= 1
        assert res["already_present"] == 0
        assert res["overwritten"] == 0
        assert res["source_missing"] == 0

    def test_second_call_reports_already_present(self, ws: Path):
        p = paths()
        for d in (p.raw, p.style_samples, p.thesis_dir):
            d.mkdir(parents=True, exist_ok=True)
        first = cli._copy_examples()
        second = cli._copy_examples()
        assert second["copied"] == 0
        assert second["already_present"] == first["copied"]

    def test_overwrite_flag_rewrites_files(self, ws: Path):
        p = paths()
        for d in (p.raw, p.style_samples, p.thesis_dir):
            d.mkdir(parents=True, exist_ok=True)
        cli._copy_examples()
        # User edits an example
        edited = p.raw / "example-source.md"
        edited.write_text("MY EDITS", encoding="utf-8")

        # Without --overwrite: left alone
        res_no = cli._copy_examples()
        assert edited.read_text(encoding="utf-8") == "MY EDITS"
        assert res_no["overwritten"] == 0
        assert res_no["already_present"] >= 1

        # With overwrite=True: replaced
        res_yes = cli._copy_examples(overwrite=True)
        assert edited.read_text(encoding="utf-8") != "MY EDITS"
        assert res_yes["overwritten"] >= 1
        assert res_yes["copied"] == 0


# ---------------------------------------------------------------------------
# Wizard output: honest report when Yes but nothing to do
# ---------------------------------------------------------------------------

class TestWizardExampleReport:
    def _run_setup(self, args_extra: list[str] | None = None):
        args = [
            "setup", "--non-interactive",
            "--provider", "anthropic", "--api-key", "sk-ant-x",
            "--skip-validation",
        ] + (args_extra or [])
        return runner.invoke(cli.app, args)

    def test_first_run_says_copied_N(self, ws: Path):
        result = self._run_setup()
        assert result.exit_code == 0, result.stdout
        assert "copied" in result.stdout
        # Should name at least one new file
        assert "new" in result.stdout

    def test_second_run_says_already_present(self, ws: Path):
        self._run_setup()
        result = self._run_setup()
        assert result.exit_code == 0
        # Must NOT mislead with "copied 0"
        assert "copied 0" not in result.stdout
        # Must explain the real state
        assert "already in your workspace" in result.stdout
        # Must point to the escape hatch
        assert "--overwrite-examples" in result.stdout

    def test_overwrite_flag_replaces_and_reports(self, ws: Path):
        self._run_setup()
        # Mutate one example
        p = paths()
        (p.raw / "example-source.md").write_text("MINE\n", encoding="utf-8")
        result = self._run_setup(["--overwrite-examples"])
        assert result.exit_code == 0, result.stdout
        assert "overwrote" in result.stdout
        # And the content was actually replaced
        content = (p.raw / "example-source.md").read_text(encoding="utf-8")
        assert content != "MINE\n"

    def test_skip_examples_still_works(self, ws: Path):
        result = self._run_setup(["--skip-examples"])
        assert result.exit_code == 0
        assert "skipped examples" in result.stdout.lower()
        # Did not copy
        assert not (ws / "research" / "raw" / "example-source.md").exists()

    def test_setup_help_documents_overwrite_flag(self, ws: Path):
        result = runner.invoke(cli.app, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--overwrite-examples" in result.stdout


# ---------------------------------------------------------------------------
# Regression: wizard must never claim "copied 0" when Yes was answered
# ---------------------------------------------------------------------------

def test_yes_with_existing_examples_never_says_copied_zero(ws: Path):
    # First run populates the examples
    runner.invoke(cli.app, [
        "setup", "--non-interactive",
        "--provider", "anthropic", "--api-key", "sk-ant-x",
        "--skip-validation",
    ])
    # Second run: user answers "Yes" to copy (via non-interactive default)
    result = runner.invoke(cli.app, [
        "setup", "--non-interactive",
        "--provider", "anthropic", "--api-key", "sk-ant-x",
        "--skip-validation",
    ])
    assert result.exit_code == 0
    assert "copied 0 example" not in result.stdout  # the bug that triggered this fix
