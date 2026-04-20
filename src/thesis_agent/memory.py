"""Two-tier memory: SQLite checkpointer (short-term) + SQLite store (long-term).

Both live as plain files under `data/` so the workspace is fully portable
(clone the repo, no services). The checkpointer is thread-scoped — one thread
per chat session. The store is cross-thread — user preferences, style rules,
outline state.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from thesis_agent.config import Paths


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def make_checkpointer(paths: Paths) -> Iterator[Any]:
    """Yield a LangGraph SqliteSaver bound to `data/checkpoints.db`."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    _ensure_parent(paths.checkpoints_db)
    conn = sqlite3.connect(str(paths.checkpoints_db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        try:
            saver.setup()
        except Exception:
            pass
        yield saver
    finally:
        conn.close()


def _try_import_sqlite_store():
    """Return SqliteStore class if the installed langgraph ships one, else None.

    Isolated from the context manager so any import/attribute failure can't
    get mixed up with exceptions thrown into the generator at yield time —
    that mix produces 'generator didn't stop after throw()'.
    """
    try:
        from langgraph.store.sqlite import SqliteStore  # type: ignore
        return SqliteStore
    except Exception:
        return None


@contextmanager
def make_store(paths: Paths) -> Iterator[Any]:
    """Yield a LangGraph Store for long-term cross-thread memory.

    Prefer SqliteStore when the installed langgraph ships it; fall back to
    InMemoryStore so the agent still works on older installs (long-term
    memory just won't persist between processes until the user upgrades).
    """
    SqliteStoreCls = _try_import_sqlite_store()

    if SqliteStoreCls is None:
        from langgraph.store.memory import InMemoryStore

        yield InMemoryStore()
        return

    _ensure_parent(paths.store_db)
    conn = sqlite3.connect(str(paths.store_db), check_same_thread=False)
    try:
        store = SqliteStoreCls(conn)
        try:
            store.setup()
        except Exception:
            pass
        yield store
    finally:
        conn.close()


@contextmanager
def memory_context(paths: Paths) -> Iterator[tuple[Any, Any]]:
    """One-shot context yielding (checkpointer, store)."""
    with ExitStack() as stack:
        cp = stack.enter_context(make_checkpointer(paths))
        st = stack.enter_context(make_store(paths))
        yield cp, st
