"""`_index.json` manifest: hash-based idempotent tracking of normalized sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from thesis_agent.config import Paths
from thesis_agent.ingest.extract import (
    SUPPORTED_EXTS,
    extract_to_markdown,
    extract_url,
    url_to_slug,
)

console = Console()


@dataclass
class ManifestEntry:
    filename: str  # normalized markdown filename (e.g. "paper.pdf.md")
    orig: str  # original filename OR URL
    orig_ext: str  # ".pdf", ".docx", "url", ...
    sha256: str
    bytes: int
    words: int
    status: str = "pending"  # "pending" | "curated"
    ingested_at: str = ""
    curated_pages: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    version: int = 1
    entries: dict[str, ManifestEntry] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> Manifest:
        m = cls(version=int(data.get("version", 1)))
        for k, v in (data.get("entries") or {}).items():
            m.entries[k] = ManifestEntry(**v)
        return m

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            console.print(f"[yellow]warning:[/] corrupt {path.name}, starting fresh")
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _iter_raw_sources(raw_dir: Path):
    """Yield (path_or_url, is_url, original_ref) tuples for files + urls.txt lines."""
    for p in sorted(raw_dir.iterdir()):
        if p.is_dir():
            continue
        if p.name.startswith("_") or p.name.startswith("."):
            continue  # _index.json, .gitkeep, etc
        if p.name == "urls.txt":
            continue  # handled separately
        if p.name.endswith(".md") and p.stem.endswith(
            tuple(e[1:] for e in SUPPORTED_EXTS if e != ".md")
        ):
            continue  # normalized output (e.g. foo.pdf.md), not a source
        if p.suffix.lower() in SUPPORTED_EXTS:
            yield p, False, p.name

    urls = raw_dir / "urls.txt"
    if urls.exists():
        for line in urls.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            yield line, True, line


def _normalized_name_for(orig: str, is_url: bool) -> str:
    if is_url:
        return url_to_slug(orig)
    return f"{orig}.md"  # attach .md after original ext -> "paper.pdf.md"


def run_ingest(raw_dir: Path, paths: Paths) -> dict:
    """Ingest everything under raw_dir. Returns a summary dict.

    Idempotent: if the extracted markdown's sha256 matches the manifest entry,
    skip. Otherwise re-extract and mark `status=pending`.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest.load(paths.index_json)

    added = 0
    updated = 0
    skipped = 0
    failed: list[tuple[str, str]] = []

    sources = list(_iter_raw_sources(raw_dir))
    if not sources:
        console.print("[yellow]no sources found[/] in " + str(raw_dir))
        manifest.save(paths.index_json)
        return {"added": 0, "updated": 0, "skipped": 0, "failed": []}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=False,
    ) as progress:
        task = progress.add_task("Extracting...", total=len(sources))
        for src, is_url, orig_ref in sources:
            progress.update(task, description=f"Extracting [cyan]{orig_ref}[/]")
            try:
                if is_url:
                    md_text = extract_url(src)
                    orig_ext = "url"
                else:
                    md_text = extract_to_markdown(src)
                    orig_ext = src.suffix.lower()
                norm_name = _normalized_name_for(orig_ref, is_url)
                norm_path = raw_dir / norm_name
                sha = _sha256_bytes(md_text.encode("utf-8"))

                existing = manifest.entries.get(norm_name)
                if existing and existing.sha256 == sha and norm_path.exists():
                    skipped += 1
                else:
                    norm_path.write_text(md_text, encoding="utf-8")
                    entry = ManifestEntry(
                        filename=norm_name,
                        orig=orig_ref,
                        orig_ext=orig_ext,
                        sha256=sha,
                        bytes=len(md_text.encode("utf-8")),
                        words=len(md_text.split()),
                        status="pending",
                        ingested_at=datetime.now(UTC).isoformat(timespec="seconds"),
                        curated_pages=[],
                    )
                    if existing:
                        updated += 1
                    else:
                        added += 1
                    manifest.entries[norm_name] = entry
            except Exception as e:  # keep going on individual failures
                failed.append((orig_ref, str(e)))
            finally:
                progress.advance(task)

    manifest.save(paths.index_json)
    return {"added": added, "updated": updated, "skipped": skipped, "failed": failed}
