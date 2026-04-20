"""Ingest edge cases: _clean, url slugs, _iter filters, DOCX/EPUB/PDF via fake modules.

These tests cover branches the happy-path suite doesn't reach — invalid input,
mixed file populations, unicode in paths, and extractors whose real libraries
we patch out to keep the tests fast + offline.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from thesis_agent.config import Paths
from thesis_agent.ingest import extract
from thesis_agent.ingest.extract import (
    SUPPORTED_EXTS,
    _clean,
    extract_to_markdown,
    url_to_slug,
)
from thesis_agent.ingest.manifest import (
    Manifest,
    ManifestEntry,
    _iter_raw_sources,
    run_ingest,
)

# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------

class TestClean:
    def test_collapses_more_than_two_blank_lines(self):
        out = _clean("a\n\n\n\n\nb")
        assert out.count("\n\n") <= 2
        assert "a" in out and "b" in out

    def test_strips_trailing_whitespace_per_line(self):
        out = _clean("foo   \nbar\t\n")
        assert "foo   " not in out
        assert "foo\nbar" in out

    def test_ends_with_single_newline(self):
        out = _clean("hello")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")

    def test_empty_input_still_ends_with_newline(self):
        out = _clean("")
        assert out == "\n"


# ---------------------------------------------------------------------------
# url_to_slug
# ---------------------------------------------------------------------------

class TestUrlSlug:
    def test_trims_protocol(self):
        assert url_to_slug("https://example.com/").startswith("example-com")

    def test_handles_query_and_fragment(self):
        a = url_to_slug("https://example.com/a?x=1&y=2#frag")
        assert "?" not in a and "#" not in a and "&" not in a
        assert a.endswith(".md")

    def test_lowercases(self):
        assert url_to_slug("https://Example.COM/Path") == url_to_slug("https://example.com/path")

    def test_stable_output(self):
        u = "https://arxiv.org/abs/1706.03762"
        assert url_to_slug(u) == url_to_slug(u)

    def test_truncated_to_80_chars_plus_ext(self):
        long_url = "https://example.com/" + ("x" * 500)
        s = url_to_slug(long_url)
        # slug body capped at 80, then ".md"
        assert len(s) <= 80 + 3

    def test_empty_path_falls_back_to_url(self):
        # Just a scheme+host with no path => non-empty slug
        s = url_to_slug("https://")
        assert s.endswith(".md")


# ---------------------------------------------------------------------------
# SUPPORTED_EXTS + dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_supported_exts_all_lowercase(self):
        for ext in SUPPORTED_EXTS:
            assert ext == ext.lower()
            assert ext.startswith(".")

    def test_unsupported_ext_raises(self, tmp_path: Path):
        p = tmp_path / "weird.xyz"
        p.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported"):
            extract_to_markdown(p)

    def test_uppercase_ext_is_accepted(self, tmp_path: Path):
        p = tmp_path / "note.TXT"
        p.write_text("hello\n", encoding="utf-8")
        # Dispatch uses .suffix.lower()
        out = extract_to_markdown(p)
        assert "hello" in out


# ---------------------------------------------------------------------------
# _iter_raw_sources filters
# ---------------------------------------------------------------------------

class TestIterRawSources:
    def test_skips_underscore_prefixed(self, tmp_path: Path):
        (tmp_path / "_index.json").write_text("{}", encoding="utf-8")
        (tmp_path / "real.md").write_text("x", encoding="utf-8")
        files = [orig for _, _, orig in _iter_raw_sources(tmp_path)]
        assert "real.md" in files
        assert "_index.json" not in files

    def test_skips_dotfiles(self, tmp_path: Path):
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        files = [orig for _, _, orig in _iter_raw_sources(tmp_path)]
        assert ".gitkeep" not in files

    def test_skips_urls_txt(self, tmp_path: Path):
        (tmp_path / "urls.txt").write_text("# nothing here\n", encoding="utf-8")
        # Should not be yielded as a source file
        files = [orig for path, is_url, orig in _iter_raw_sources(tmp_path) if not is_url]
        assert "urls.txt" not in files

    def test_skips_normalized_output_file(self, tmp_path: Path):
        # foo.pdf.md is the output of prior ingest; should not re-ingest
        (tmp_path / "foo.pdf.md").write_text("normalized", encoding="utf-8")
        (tmp_path / "bar.md").write_text("real", encoding="utf-8")
        files = [orig for _, _, orig in _iter_raw_sources(tmp_path)]
        assert "foo.pdf.md" not in files
        assert "bar.md" in files

    def test_skips_subdirectories(self, tmp_path: Path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "deep.md").write_text("x", encoding="utf-8")
        (tmp_path / "top.md").write_text("y", encoding="utf-8")
        files = [orig for _, _, orig in _iter_raw_sources(tmp_path)]
        assert "top.md" in files
        assert "deep.md" not in files  # subdirs are not recursed

    def test_yields_urls_from_urls_txt(self, tmp_path: Path):
        (tmp_path / "urls.txt").write_text(
            "# comment\n\nhttps://example.com/a\nhttps://example.com/b\n",
            encoding="utf-8",
        )
        urls = [orig for _, is_url, orig in _iter_raw_sources(tmp_path) if is_url]
        assert urls == ["https://example.com/a", "https://example.com/b"]


# ---------------------------------------------------------------------------
# DOCX via fake python-docx module
# ---------------------------------------------------------------------------

def _install_fake_docx(monkeypatch, paragraphs: list[tuple[str, str]]):
    """Fake `docx.Document` that returns pre-scripted paragraphs."""
    fake_mod = types.ModuleType("docx")

    class FakeStyle:
        def __init__(self, name: str):
            self.name = name

    class FakePara:
        def __init__(self, text: str, style_name: str):
            self.text = text
            self.style = FakeStyle(style_name)

    class FakeDoc:
        def __init__(self, path):
            self.paragraphs = [FakePara(t, s) for (t, s) in paragraphs]

    fake_mod.Document = FakeDoc
    monkeypatch.setitem(sys.modules, "docx", fake_mod)


class TestDocx:
    def test_maps_heading_levels(self, tmp_path: Path, monkeypatch):
        _install_fake_docx(monkeypatch, [
            ("Top", "Heading 1"),
            ("Sub", "Heading 2"),
            ("SubSub", "Heading 3"),
            ("Body text.", "Normal"),
            ("", "Normal"),
        ])
        p = tmp_path / "x.docx"
        p.write_bytes(b"not used")
        out = extract.extract_docx(p)
        assert "# Top" in out
        assert "## Sub" in out
        assert "### SubSub" in out
        assert "Body text." in out

    def test_empty_doc_produces_trailing_newline(self, tmp_path: Path, monkeypatch):
        _install_fake_docx(monkeypatch, [])
        p = tmp_path / "empty.docx"
        p.write_bytes(b"")
        out = extract.extract_docx(p)
        assert out == "\n"


# ---------------------------------------------------------------------------
# EPUB via fake ebooklib + bs4
# ---------------------------------------------------------------------------

def _install_fake_epub(monkeypatch, items_html: list[str]):
    import ebooklib
    from ebooklib import epub  # noqa: F401  (needed so attribute lookup works)

    class FakeItem:
        def __init__(self, html: str, is_doc: bool = True):
            self._html = html
            self._is_doc = is_doc

        def get_type(self):
            return ebooklib.ITEM_DOCUMENT if self._is_doc else 0

        def get_content(self):
            return self._html.encode("utf-8")

    class FakeBook:
        def __init__(self, items):
            self._items = items

        def get_items(self):
            return list(self._items)

    def fake_read_epub(path):
        return FakeBook([FakeItem(h) for h in items_html])

    monkeypatch.setattr("ebooklib.epub.read_epub", fake_read_epub)


class TestEpub:
    def test_extracts_text_strips_script_and_style(self, tmp_path: Path, monkeypatch):
        _install_fake_epub(monkeypatch, [
            "<html><body><h1>Title</h1><script>x=1</script><p>Para.</p></body></html>",
            "<html><body><style>.a{}</style><p>Two.</p></body></html>",
        ])
        p = tmp_path / "book.epub"
        p.write_bytes(b"")
        out = extract.extract_epub(p)
        assert "Title" in out
        assert "Para." in out
        assert "Two." in out
        assert "x=1" not in out  # script content removed
        assert ".a{}" not in out


# ---------------------------------------------------------------------------
# run_ingest wiring
# ---------------------------------------------------------------------------

class TestRunIngest:
    def test_empty_dir_produces_empty_manifest(self, tmp_path: Path):
        p = Paths(tmp_path.resolve())
        p.raw.mkdir(parents=True)
        result = run_ingest(p.raw, p)
        assert result == {"added": 0, "updated": 0, "skipped": 0, "failed": []}
        # _index.json should be touched (empty manifest written)
        assert p.index_json.exists()
        m = Manifest.load(p.index_json)
        assert m.entries == {}

    def test_content_change_updates_manifest_and_reverts_status(self, tmp_path: Path):
        p = Paths(tmp_path.resolve())
        p.raw.mkdir(parents=True)
        src = p.raw / "doc.txt"
        src.write_text("v1\n", encoding="utf-8")
        run_ingest(p.raw, p)
        # Simulate curator marking curated
        m = Manifest.load(p.index_json)
        entry = m.entries["doc.txt.md"]
        entry.status = "curated"
        entry.curated_pages = ["doc.txt.md"]
        m.save(p.index_json)

        # Modify the source — re-ingest must reset to pending
        src.write_text("v2 changed\n", encoding="utf-8")
        result = run_ingest(p.raw, p)
        assert result["updated"] == 1
        m2 = Manifest.load(p.index_json)
        e2 = m2.entries["doc.txt.md"]
        assert e2.status == "pending"
        assert e2.curated_pages == []

    def test_failure_on_one_source_doesnt_stop_others(self, tmp_path: Path, monkeypatch):
        p = Paths(tmp_path.resolve())
        p.raw.mkdir(parents=True)
        (p.raw / "good.md").write_text("ok\n", encoding="utf-8")
        (p.raw / "bad.md").write_text("bad\n", encoding="utf-8")

        real = extract.extract_to_markdown

        def flaky(path):
            if path.name == "bad.md":
                raise RuntimeError("boom")
            return real(path)

        monkeypatch.setattr(
            "thesis_agent.ingest.manifest.extract_to_markdown", flaky
        )
        result = run_ingest(p.raw, p)
        assert result["added"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0][0] == "bad.md"

    def test_manifest_corrupt_json_starts_fresh(self, tmp_path: Path):
        p = Paths(tmp_path.resolve())
        p.raw.mkdir(parents=True)
        p.index_json.write_text("{ not valid json", encoding="utf-8")
        (p.raw / "note.md").write_text("x", encoding="utf-8")
        result = run_ingest(p.raw, p)
        assert result["added"] == 1


class TestManifestEntry:
    def test_default_status_pending(self):
        e = ManifestEntry(
            filename="x.md", orig="x.md", orig_ext=".md",
            sha256="abc", bytes=1, words=1,
        )
        assert e.status == "pending"
        assert e.curated_pages == []

    def test_round_trip_via_manifest_asdict(self, tmp_path: Path):
        m = Manifest()
        m.entries["y.md"] = ManifestEntry(
            filename="y.md", orig="y.md", orig_ext=".md",
            sha256="def", bytes=2, words=2,
            status="curated", curated_pages=["y.md"],
        )
        m.save(tmp_path / "_index.json")
        loaded = Manifest.load(tmp_path / "_index.json")
        e = loaded.entries["y.md"]
        assert e.status == "curated"
        assert e.curated_pages == ["y.md"]
