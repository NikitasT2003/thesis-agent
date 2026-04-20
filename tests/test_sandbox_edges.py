"""Sandbox edge cases: globs, literal-allow overrides, case normalisation, symlinks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from thesis_agent.sandbox import (
    DRAFTER,
    GLOBAL_DENY,
    MAIN,
    RESEARCHER,
    SCOPES,
    WIKI_CURATOR,
    SandboxViolation,
    Scope,
    check_write,
    resolve_inside_root,
)

# ---------------------------------------------------------------------------
# resolve_inside_root
# ---------------------------------------------------------------------------

class TestResolveInsideRoot:
    def test_resolves_relative_to_root(self, tmp_path: Path):
        out = resolve_inside_root("sub/file.md", tmp_path)
        assert out == (tmp_path / "sub" / "file.md").resolve()

    def test_accepts_absolute_inside(self, tmp_path: Path):
        abs_path = tmp_path / "a.md"
        out = resolve_inside_root(str(abs_path), tmp_path)
        assert out == abs_path.resolve()

    def test_rejects_absolute_outside(self, tmp_path: Path):
        with pytest.raises(SandboxViolation):
            resolve_inside_root("/tmp/evil.txt", tmp_path)

    def test_rejects_parent_traversal(self, tmp_path: Path):
        with pytest.raises(SandboxViolation):
            resolve_inside_root("../../etc/passwd", tmp_path)

    def test_rejects_mixed_separators(self, tmp_path: Path):
        # Windows-style path attempting to escape
        with pytest.raises(SandboxViolation):
            resolve_inside_root("..\\..\\etc\\passwd", tmp_path)

    def test_path_object_input(self, tmp_path: Path):
        out = resolve_inside_root(Path("sub/x.md"), tmp_path)
        assert out == (tmp_path / "sub" / "x.md").resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink rights required on Windows")
class TestSymlinkEscape:
    def test_symlink_out_of_root_is_rejected(self, tmp_path: Path):
        outside = tmp_path.parent / "outside_ws"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("shhh", encoding="utf-8")

        root = tmp_path / "ws"
        root.mkdir()
        link = root / "leak"
        os.symlink(outside, link)

        with pytest.raises(SandboxViolation):
            resolve_inside_root("leak/secret.txt", root)


# ---------------------------------------------------------------------------
# Scope.permits — glob + literal semantics
# ---------------------------------------------------------------------------

class TestScopePermits:
    def test_literal_allow_overrides_wildcard_deny(self, tmp_path: Path):
        # This is the exact case we hit for wiki-curator writing _index.json
        (tmp_path / "research" / "raw").mkdir(parents=True)
        assert WIKI_CURATOR.permits(
            (tmp_path / "research" / "raw" / "_index.json").resolve(),
            tmp_path,
        )
        # But NOT other files under research/raw
        assert not WIKI_CURATOR.permits(
            (tmp_path / "research" / "raw" / "new.md").resolve(),
            tmp_path,
        )

    def test_path_outside_root_never_permitted(self, tmp_path: Path):
        outside = tmp_path.parent / "outside.txt"
        assert not MAIN.permits(outside, tmp_path)

    def test_nested_directory_under_allow_glob(self, tmp_path: Path):
        # research/wiki/** should match deeply nested paths
        (tmp_path / "research" / "wiki" / "a" / "b").mkdir(parents=True)
        assert WIKI_CURATOR.permits(
            (tmp_path / "research" / "wiki" / "a" / "b" / "page.md").resolve(),
            tmp_path,
        )

    def test_env_file_is_on_global_deny(self, tmp_path: Path):
        assert not MAIN.permits((tmp_path / ".env").resolve(), tmp_path)

    def test_custom_scope_can_be_instantiated(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        s = Scope(name="docs", allow_globs=("docs/**", "docs/*"))
        assert s.permits((tmp_path / "docs" / "a.md").resolve(), tmp_path)
        assert not s.permits((tmp_path / "other.md").resolve(), tmp_path)


# ---------------------------------------------------------------------------
# check_write integration
# ---------------------------------------------------------------------------

class TestCheckWrite:
    def test_returns_absolute_resolved_path(self, tmp_path: Path):
        (tmp_path / "thesis").mkdir()
        out = check_write("drafter", "thesis/01.md", tmp_path)
        assert out.is_absolute()
        assert out == (tmp_path / "thesis" / "01.md").resolve()

    def test_unknown_scope_raises(self, tmp_path: Path):
        with pytest.raises(SandboxViolation, match="unknown scope"):
            check_write("ghost", "x", tmp_path)

    def test_researcher_all_writes_rejected(self, tmp_path: Path):
        (tmp_path / "research" / "wiki").mkdir(parents=True)
        (tmp_path / "thesis").mkdir()
        for target in ("research/wiki/a.md", "thesis/01.md", "style/STYLE.md"):
            with pytest.raises(SandboxViolation):
                check_write("researcher", target, tmp_path)

    def test_drafter_cannot_touch_wiki(self, tmp_path: Path):
        (tmp_path / "research" / "wiki").mkdir(parents=True)
        with pytest.raises(SandboxViolation):
            check_write("drafter", "research/wiki/x.md", tmp_path)

    def test_main_can_write_style_guide(self, tmp_path: Path):
        (tmp_path / "style").mkdir()
        check_write("main", "style/STYLE.md", tmp_path)

    def test_main_cannot_overwrite_style_samples(self, tmp_path: Path):
        # style/samples is not in main's allowlist
        (tmp_path / "style" / "samples").mkdir(parents=True)
        # style/** is NOT granted to main; only style/STYLE.md is allowed.
        with pytest.raises(SandboxViolation):
            check_write("main", "style/samples/essay.md", tmp_path)


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

class TestScopeRegistry:
    def test_all_named_scopes_in_SCOPES(self):
        assert set(SCOPES.keys()) == {"main", "wiki-curator", "drafter", "researcher"}

    def test_global_deny_contains_data_and_raw(self):
        assert any("data/" in g for g in GLOBAL_DENY)
        assert any("research/raw" in g for g in GLOBAL_DENY)

    def test_drafter_scope_is_only_thesis(self):
        assert all("thesis" in g for g in DRAFTER.allow_globs)

    def test_researcher_has_no_allow_globs(self):
        assert RESEARCHER.allow_globs == ()
