"""Ingest pipeline tests — extractors + manifest idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent.config import Paths
from thesis_agent.ingest.extract import extract_to_markdown, url_to_slug
from thesis_agent.ingest.manifest import Manifest, run_ingest


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Paths:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "research" / "raw").mkdir(parents=True)
    return Paths(tmp_path.resolve())


def test_manifest_round_trip(tmp_path: Path):
    m = Manifest()
    from thesis_agent.ingest.manifest import ManifestEntry

    m.entries["foo.md"] = ManifestEntry(
        filename="foo.md",
        orig="foo.txt",
        orig_ext=".txt",
        sha256="abc",
        bytes=5,
        words=1,
        status="pending",
    )
    p = tmp_path / "_index.json"
    m.save(p)
    loaded = Manifest.load(p)
    assert loaded.entries["foo.md"].sha256 == "abc"
    assert loaded.entries["foo.md"].status == "pending"


def test_ingest_txt_is_idempotent(workspace: Paths):
    src = workspace.raw / "note.txt"
    src.write_text("hello world\n\n\n\nmore\n", encoding="utf-8")

    r1 = run_ingest(workspace.raw, workspace)
    assert r1["added"] == 1
    assert (workspace.raw / "note.txt.md").exists()
    m = Manifest.load(workspace.index_json)
    assert m.entries["note.txt.md"].status == "pending"
    assert m.entries["note.txt.md"].words >= 2

    # Re-run with no changes → skipped
    r2 = run_ingest(workspace.raw, workspace)
    assert r2["added"] == 0
    assert r2["skipped"] == 1


def test_ingest_md_passthrough(workspace: Paths):
    src = workspace.raw / "paper.md"
    src.write_text("# Title\n\nBody.\n", encoding="utf-8")
    r = run_ingest(workspace.raw, workspace)
    assert r["added"] == 1
    out = workspace.raw / "paper.md.md"
    assert out.exists()
    assert "Title" in out.read_text(encoding="utf-8")


def test_unsupported_ext_raises_via_extractor(tmp_path: Path):
    p = tmp_path / "weird.xyz"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_to_markdown(p)


def test_url_slug_is_stable_and_safe():
    s1 = url_to_slug("https://example.com/page/a?b=1")
    s2 = url_to_slug("https://example.com/page/a?b=1")
    assert s1 == s2
    assert s1.endswith(".md")
    assert "/" not in s1
    assert "?" not in s1


def test_urls_txt_comments_ignored(workspace: Paths):
    urls = workspace.raw / "urls.txt"
    urls.write_text("# comment\n\n# another\n", encoding="utf-8")
    r = run_ingest(workspace.raw, workspace)
    assert r["added"] == 0
