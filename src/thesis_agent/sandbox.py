"""Sandbox: path-scoped filesystem guard for agent writes.

The agent has no shell, no network, and no code-exec tools by design (see
`agent.py` where `tools=[]`). This module layers one more defense: every
write the agent emits is resolved to an absolute path, then checked against
allowlists and denylists before it touches disk.

Scope rules:
  * Everything resolves inside the workspace root.
  * `data/` and `research/raw/` are deny-list for all agents.
  * `wiki-curator` may only write under `research/wiki/**` + update `_index.json`.
  * `drafter` may only write under `thesis/**`.
  * `researcher` may not write anywhere.
  * Main agent may write to `research/wiki/**`, `style/STYLE.md`, `thesis/**`,
    and `research/raw/_index.json`.

The `WriteGuard` is designed to plug into deepagents' filesystem middleware;
the `resolve_inside_root` helper is also used directly by any non-LLM code
that accepts agent-supplied paths (currently none — kept as a safety net).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class SandboxViolation(RuntimeError):
    """Raised when the agent attempts a write that violates policy."""


def resolve_inside_root(path: str | Path, root: Path) -> Path:
    """Resolve *path* and require it to be inside *root*.

    Handles relative paths (resolved against root), absolute paths (must be
    under root after resolution), symlink traversal, and Windows/POSIX mixing.
    """
    root = root.resolve()
    p = Path(path)
    abs_p = (p if p.is_absolute() else (root / p)).resolve()
    try:
        abs_p.relative_to(root)
    except ValueError as e:
        raise SandboxViolation(
            f"path escapes workspace: {path!r} -> {abs_p} (root: {root})"
        ) from e
    return abs_p


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class Scope:
    """Per-agent write scope. Empty allow = no writes (read-only)."""

    name: str
    allow_globs: tuple[str, ...]
    deny_globs: tuple[str, ...] = ()

    def permits(self, path: Path, root: Path) -> bool:
        abs_p = path.resolve()
        if not _under(abs_p, root):
            return False
        rel = PurePosixPath(abs_p.relative_to(root.resolve()).as_posix())
        rel_str = str(rel)

        def _match(pattern: str) -> bool:
            if rel.match(pattern):
                return True
            prefix = pattern.rstrip("/*")
            return bool(prefix) and (rel_str == prefix or rel_str.startswith(prefix + "/"))

        # Exact literal allow (no wildcards) wins over deny — lets scopes whitelist
        # specific files like `research/raw/_index.json` even though the dir is denied.
        for g in self.allow_globs:
            if "*" not in g and rel_str == g:
                return True
        for g in self.deny_globs:
            if _match(g):
                return False
        for g in self.allow_globs:
            if _match(g):
                return True
        return False


# Global deny list: these paths are off-limits to every agent, full stop.
GLOBAL_DENY: tuple[str, ...] = (
    "data/**",
    "data/*",
    ".env",
    ".env.*",
    "research/raw/**",  # raw sources are immutable
    # allow _index.json via explicit allow in wiki-curator and main
)


MAIN: Scope = Scope(
    name="main",
    allow_globs=(
        "research/wiki/**",
        "research/wiki/*",
        "research/raw/_index.json",
        "style/STYLE.md",
        "thesis/**",
        "thesis/*",
    ),
    deny_globs=GLOBAL_DENY,
)

WIKI_CURATOR: Scope = Scope(
    name="wiki-curator",
    allow_globs=(
        "research/wiki/**",
        "research/wiki/*",
        "research/raw/_index.json",
    ),
    deny_globs=GLOBAL_DENY,
)

DRAFTER: Scope = Scope(
    name="drafter",
    allow_globs=("thesis/**", "thesis/*"),
    deny_globs=GLOBAL_DENY,
)

RESEARCHER: Scope = Scope(
    name="researcher",
    allow_globs=(),  # read-only
    deny_globs=GLOBAL_DENY,
)

SCOPES: dict[str, Scope] = {
    s.name: s for s in (MAIN, WIKI_CURATOR, DRAFTER, RESEARCHER)
}


def check_write(scope_name: str, path: str | Path, root: Path) -> Path:
    """Resolve + authorise a write. Returns the resolved absolute path.

    Raises SandboxViolation if the write is outside workspace, on the global
    deny list, or outside the scope's allow list.
    """
    scope = SCOPES.get(scope_name)
    if scope is None:
        raise SandboxViolation(f"unknown scope: {scope_name!r}")
    abs_p = resolve_inside_root(path, root)
    if not scope.permits(abs_p, root):
        raise SandboxViolation(
            f"scope {scope.name!r} may not write to {path!r} "
            f"(allowed: {scope.allow_globs})"
        )
    return abs_p
