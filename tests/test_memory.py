"""Memory module: SqliteSaver / SqliteStore context managers.

These tests hit real sqlite (file DBs) because the whole point of the module
is round-tripping through disk. They do not call any LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent.config import Paths
from thesis_agent.memory import make_checkpointer, make_store, memory_context


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path.resolve())


# ---------------------------------------------------------------------------
# make_checkpointer
# ---------------------------------------------------------------------------

def test_checkpointer_yields_usable_saver(paths: Paths):
    with make_checkpointer(paths) as saver:
        assert saver is not None
        # LangGraph's SqliteSaver exposes .put / .get_tuple / .list
        assert hasattr(saver, "put") or hasattr(saver, "aput")


def test_checkpointer_creates_db_file(paths: Paths):
    assert not paths.checkpoints_db.exists()
    with make_checkpointer(paths):
        assert paths.checkpoints_db.exists()


def test_checkpointer_persists_across_invocations(paths: Paths):
    # Two sequential "with" blocks must share the same file.
    with make_checkpointer(paths) as s1:
        db_path_1 = paths.checkpoints_db
        assert db_path_1.exists()
        size_1 = db_path_1.stat().st_size
        assert size_1 > 0
        _ = s1  # keep reference live

    with make_checkpointer(paths):
        # File persists, not truncated
        assert paths.checkpoints_db.exists()
        assert paths.checkpoints_db.stat().st_size >= size_1


def test_checkpointer_creates_parent_directory(paths: Paths):
    assert not paths.data_dir.exists()
    with make_checkpointer(paths):
        assert paths.data_dir.is_dir()


# ---------------------------------------------------------------------------
# make_store
# ---------------------------------------------------------------------------

def test_store_yields_something(paths: Paths):
    with make_store(paths) as store:
        assert store is not None
        # BaseStore API: .get / .put / .search
        assert hasattr(store, "get") or hasattr(store, "aget")


def test_store_uses_sqlite_when_available_else_inmemory(paths: Paths):
    """Whatever backend is chosen, the context manager must not raise."""
    with make_store(paths) as store:
        typename = type(store).__name__
        assert typename in {"SqliteStore", "InMemoryStore"}


# ---------------------------------------------------------------------------
# memory_context (combined)
# ---------------------------------------------------------------------------

def test_memory_context_yields_pair(paths: Paths):
    with memory_context(paths) as (cp, st):
        assert cp is not None
        assert st is not None


def test_memory_context_closes_both_on_exit(paths: Paths):
    """Contract: no dangling file handles after exit. On Windows, a still-open
    sqlite connection would prevent deletion — use that as the probe."""
    with memory_context(paths):
        pass
    # Both DB files should exist and be deletable (no locks held)
    if paths.checkpoints_db.exists():
        paths.checkpoints_db.unlink()
    if paths.store_db.exists():
        paths.store_db.unlink()
    # No assertion needed — if a lock were held, unlink() would have raised.


def test_memory_context_isolates_per_paths(tmp_path: Path):
    """Two independent workspaces must not share DB files."""
    a = Paths((tmp_path / "a").resolve())
    b = Paths((tmp_path / "b").resolve())
    with memory_context(a):
        pass
    with memory_context(b):
        pass
    assert a.checkpoints_db.exists()
    assert b.checkpoints_db.exists()
    assert a.checkpoints_db != b.checkpoints_db


# ---------------------------------------------------------------------------
# Idempotency: setup() called twice does not corrupt
# ---------------------------------------------------------------------------

def test_checkpointer_setup_twice_does_not_crash(paths: Paths):
    with make_checkpointer(paths):
        pass
    with make_checkpointer(paths):
        pass  # would raise if setup() weren't idempotent
