"""Coverage fill-ins: PDF extractor via fake pypdf, ingest __main__, agent-dispatch CLI."""

from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thesis_agent import cli
from thesis_agent.ingest import extract

runner = CliRunner()


# ---------------------------------------------------------------------------
# PDF extractor (fake pypdf)
# ---------------------------------------------------------------------------

def _install_fake_pypdf(monkeypatch, pages_text: list[str]):
    fake_mod = types.ModuleType("pypdf")

    class FakePage:
        def __init__(self, t):
            self._t = t

        def extract_text(self):
            return self._t

    class FakeReader:
        def __init__(self, path):
            self.pages = [FakePage(t) for t in pages_text]

    fake_mod.PdfReader = FakeReader
    monkeypatch.setitem(sys.modules, "pypdf", fake_mod)


class TestPdfExtractor:
    def test_extract_pdf_joins_pages_with_headings(self, tmp_path: Path, monkeypatch):
        _install_fake_pypdf(monkeypatch, ["Page one text.", "Page two text."])
        p = tmp_path / "paper.pdf"
        p.write_bytes(b"")
        out = extract.extract_pdf(p)
        assert "## Page 1" in out
        assert "Page one text." in out
        assert "## Page 2" in out
        assert "Page two text." in out

    def test_extract_pdf_skips_blank_pages(self, tmp_path: Path, monkeypatch):
        _install_fake_pypdf(monkeypatch, ["Real content.", "", "   "])
        p = tmp_path / "x.pdf"
        p.write_bytes(b"")
        out = extract.extract_pdf(p)
        assert "## Page 1" in out
        # Pages 2 and 3 are blank — no heading for them
        assert "## Page 2" not in out
        assert "## Page 3" not in out

    def test_extract_pdf_tolerates_page_extraction_error(self, tmp_path: Path, monkeypatch):
        fake_mod = types.ModuleType("pypdf")

        class BadPage:
            def extract_text(self):
                raise RuntimeError("bad page")

        class OkPage:
            def extract_text(self):
                return "ok"

        class FakeReader:
            def __init__(self, path):
                self.pages = [BadPage(), OkPage()]

        fake_mod.PdfReader = FakeReader
        monkeypatch.setitem(sys.modules, "pypdf", fake_mod)
        p = tmp_path / "x.pdf"
        p.write_bytes(b"")
        # Should not raise; bad page is silently skipped.
        out = extract.extract_pdf(p)
        assert "ok" in out


# ---------------------------------------------------------------------------
# URL extractor via fake trafilatura
# ---------------------------------------------------------------------------

def _install_fake_trafilatura(monkeypatch, html: str | None, markdown: str | None):
    fake_mod = types.ModuleType("trafilatura")
    fake_mod.fetch_url = lambda url: html
    fake_mod.extract = lambda _downloaded, **kw: markdown
    monkeypatch.setitem(sys.modules, "trafilatura", fake_mod)


class TestUrlExtractor:
    def test_extract_url_happy_path(self, monkeypatch):
        _install_fake_trafilatura(monkeypatch, "<html>x</html>", "# Hello\n\nBody.")
        out = extract.extract_url("https://example.com/a")
        assert "Hello" in out and "Body." in out

    def test_extract_url_fetch_failure_raises(self, monkeypatch):
        _install_fake_trafilatura(monkeypatch, None, None)
        with pytest.raises(RuntimeError, match="failed to fetch"):
            extract.extract_url("https://example.com/fail")

    def test_extract_url_empty_content_raises(self, monkeypatch):
        _install_fake_trafilatura(monkeypatch, "<html></html>", None)
        with pytest.raises(RuntimeError, match="no extractable content"):
            extract.extract_url("https://example.com/empty")


# ---------------------------------------------------------------------------
# `python -m thesis_agent.ingest` entrypoint
# ---------------------------------------------------------------------------

class TestIngestMainModule:
    def test_main_defaults_to_research_raw(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "research" / "raw").mkdir(parents=True)
        (tmp_path / "research" / "raw" / "note.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["thesis_agent.ingest"])
        # Use runpy to execute the module as __main__
        try:
            runpy.run_module("thesis_agent.ingest", run_name="__main__")
        except SystemExit as e:
            assert e.code == 0
        assert (tmp_path / "research" / "raw" / "note.md.md").exists()

    def test_main_with_explicit_dir_arg(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        custom = tmp_path / "custom"
        custom.mkdir()
        (custom / "a.md").write_text("hi", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["thesis_agent.ingest", str(custom)])
        try:
            runpy.run_module("thesis_agent.ingest", run_name="__main__")
        except SystemExit as e:
            assert e.code == 0
        assert (custom / "a.md.md").exists()


# ---------------------------------------------------------------------------
# Agent-dispatch CLI commands (curate/style/write/lint) with mocked agent
# ---------------------------------------------------------------------------

class TestAgentCommands:
    def _patch_invoke(self, monkeypatch, reply: str = "ok") -> list[tuple[str, str]]:
        seen: list[tuple[str, str]] = []

        def fake_invoke(prompt: str, *, thread_id: str, p=None):
            seen.append((prompt, thread_id))
            return reply

        monkeypatch.setattr("thesis_agent.agent.invoke", fake_invoke)
        return seen

    def test_curate_dispatches_pending_sources_prompt(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        seen = self._patch_invoke(monkeypatch)
        result = runner.invoke(cli.app, ["curate"])
        assert result.exit_code == 0, result.stdout
        assert len(seen) == 1
        prompt, _ = seen[0]
        assert "pending" in prompt.lower()
        assert "wiki-curator" in prompt.lower() or "curate" in prompt.lower()

    def test_style_dispatches_samples_prompt(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        seen = self._patch_invoke(monkeypatch)
        result = runner.invoke(cli.app, ["style"])
        assert result.exit_code == 0, result.stdout
        assert "style/samples" in seen[0][0]
        assert "STYLE.md" in seen[0][0]

    def test_write_carries_section_identifier(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        seen = self._patch_invoke(monkeypatch)
        result = runner.invoke(cli.app, ["write", "2.1"])
        assert result.exit_code == 0
        assert "2.1" in seen[0][0]

    def test_lint_specific_file_passed_through(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        target = tmp_path / "thesis" / "chapters" / "02.md"
        target.write_text("# 02\n", encoding="utf-8")
        seen = self._patch_invoke(monkeypatch)
        result = runner.invoke(cli.app, ["lint", str(target)])
        assert result.exit_code == 0
        assert str(target) in seen[0][0] or "02.md" in seen[0][0]

    def test_thread_flag_persists_to_file(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])
        self._patch_invoke(monkeypatch)
        runner.invoke(cli.app, ["curate", "--thread", "t-777"])
        assert (tmp_path / "data" / ".thread").read_text(encoding="utf-8").strip() == "t-777"

    def test_agent_error_exits_nonzero(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(cli.app, ["init"])

        def raiser(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr("thesis_agent.agent.invoke", raiser)
        result = runner.invoke(cli.app, ["curate"])
        assert result.exit_code != 0
        assert "agent error" in result.stdout.lower()
