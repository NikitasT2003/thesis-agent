"""`python -m thesis_agent.ingest <dir>` — standalone entrypoint for ingest."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from thesis_agent.config import paths
from thesis_agent.ingest.manifest import run_ingest

console = Console()


def main() -> int:
    args = sys.argv[1:]
    p = paths()
    raw_dir = Path(args[0]).resolve() if args else p.raw
    result = run_ingest(raw_dir, p)
    console.print(
        f"[green]done[/] — added {result['added']}, updated {result['updated']}, "
        f"skipped {result['skipped']}, failed {len(result['failed'])}"
    )
    for ref, err in result["failed"]:
        console.print(f"  [red]\u2717[/] {ref}: {err}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
