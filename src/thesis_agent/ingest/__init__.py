"""Deterministic source ingestion: PDF/DOCX/EPUB/MD/URL -> normalized markdown."""

from thesis_agent.ingest.extract import extract_to_markdown
from thesis_agent.ingest.manifest import Manifest, ManifestEntry, run_ingest

__all__ = ["extract_to_markdown", "Manifest", "ManifestEntry", "run_ingest"]
