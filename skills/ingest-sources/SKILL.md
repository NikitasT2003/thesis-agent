---
name: ingest-sources
description: Use this skill when the user asks to ingest, add, index, or import new source material (PDFs, DOCX, EPUB, Markdown, URLs) into the thesis research library, or after they have dropped new files into `research/raw/`. Explains how to run the deterministic ingest CLI and follow up by triggering curation. Triggers include phrases like "ingest", "add source", "index these", "import sources", "update knowledge base", "I just dropped files in raw".
---

# ingest-sources

## When to use
Triggered when the user has added material under `research/raw/` or asks to bring new sources into the library. The wiki will be stale until both ingest AND curate run.

## Do NOT run the ingest yourself
Source extraction is deterministic Python — it is NOT an agent task. Do not try to read binary PDFs with `read_file` or invent a URL fetcher. Instead, tell the user to run the CLI:

```
uv run thesis ingest
```

This runs `thesis_agent.ingest.run_ingest`, which:
- Extracts text from every PDF / DOCX / EPUB / MD / TXT in `research/raw/` and every URL listed in `research/raw/urls.txt`.
- Writes normalised markdown alongside each original, named `<orig_filename>.md`.
- Updates `research/raw/_index.json` with sha256, word count, and `status: pending`.
- Is idempotent — unchanged files are skipped.

## After ingest
Once the user confirms ingest finished, offer to run the `wiki-curator` subagent on any entries with `status: pending`. The handoff prompt is:

> "Curate all pending sources per AGENTS.md. For each entry in `research/raw/_index.json` where `status == 'pending'`: delegate to the wiki-curator subagent, then flip status to `curated` when it confirms completion."

## Failure handling
If the user says ingest failed:
- Ask them to paste the error.
- Common causes: missing optional dependency (e.g. `ebooklib`), encrypted PDF, broken URL. Advise they install optional deps with `uv sync` or skip the offending file.
