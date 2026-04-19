"""Sandbox policy tests — path traversal + scope enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent.sandbox import (
    SandboxViolation,
    check_write,
    resolve_inside_root,
)


def test_resolve_rejects_dotdot_traversal(tmp_path: Path):
    with pytest.raises(SandboxViolation):
        resolve_inside_root("../outside.txt", tmp_path)


def test_resolve_rejects_absolute_outside(tmp_path: Path):
    with pytest.raises(SandboxViolation):
        resolve_inside_root("/etc/passwd", tmp_path)


def test_resolve_accepts_relative_inside(tmp_path: Path):
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    out = resolve_inside_root("research/wiki/x.md", tmp_path)
    assert out.is_absolute()
    assert str(out).startswith(str(tmp_path.resolve()))


def test_main_can_write_wiki(tmp_path: Path):
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    out = check_write("main", "research/wiki/a.md", tmp_path)
    assert out.name == "a.md"


def test_main_cannot_write_data(tmp_path: Path):
    (tmp_path / "data").mkdir()
    with pytest.raises(SandboxViolation):
        check_write("main", "data/checkpoints.db", tmp_path)


def test_main_cannot_write_raw(tmp_path: Path):
    (tmp_path / "research" / "raw").mkdir(parents=True)
    with pytest.raises(SandboxViolation):
        check_write("main", "research/raw/evil.md", tmp_path)


def test_researcher_is_read_only(tmp_path: Path):
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    with pytest.raises(SandboxViolation):
        check_write("researcher", "research/wiki/a.md", tmp_path)


def test_drafter_only_under_thesis(tmp_path: Path):
    (tmp_path / "thesis" / "chapters").mkdir(parents=True)
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    assert check_write("drafter", "thesis/chapters/01.md", tmp_path).name == "01.md"
    with pytest.raises(SandboxViolation):
        check_write("drafter", "research/wiki/01.md", tmp_path)


def test_wiki_curator_only_under_wiki_plus_manifest(tmp_path: Path):
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    (tmp_path / "research" / "raw").mkdir(parents=True)
    (tmp_path / "thesis").mkdir(parents=True)
    assert check_write("wiki-curator", "research/wiki/a.md", tmp_path)
    assert check_write("wiki-curator", "research/raw/_index.json", tmp_path)
    with pytest.raises(SandboxViolation):
        check_write("wiki-curator", "thesis/chapters/01.md", tmp_path)


def test_unknown_scope_rejected(tmp_path: Path):
    with pytest.raises(SandboxViolation):
        check_write("hacker", "research/wiki/x.md", tmp_path)
