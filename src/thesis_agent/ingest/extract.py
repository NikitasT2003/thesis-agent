"""Extractors: one function per source kind, all returning plain UTF-8 markdown."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

SUPPORTED_EXTS: set[str] = {".pdf", ".docx", ".epub", ".md", ".markdown", ".txt"}


def _clean(text: str) -> str:
    """Collapse >2 blank lines, strip trailing whitespace on lines."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 2:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out).strip() + "\n"


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            parts.append(f"## Page {i}\n\n{txt.strip()}")
    return _clean("\n\n".join(parts))


def extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    for para in doc.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        text = para.text.strip()
        if not text:
            parts.append("")
            continue
        if "heading 1" in style:
            parts.append(f"# {text}")
        elif "heading 2" in style:
            parts.append(f"## {text}")
        elif "heading" in style:
            parts.append(f"### {text}")
        else:
            parts.append(text)
    return _clean("\n\n".join(parts))


def extract_epub(path: Path) -> str:
    from bs4 import BeautifulSoup
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items():
        if item.get_type() != ITEM_DOCUMENT:
            continue
        html = item.get_content().decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        if text.strip():
            parts.append(text.strip())
    return _clean("\n\n".join(parts))


def extract_text(path: Path) -> str:
    return _clean(path.read_text(encoding="utf-8", errors="ignore"))


def extract_url(url: str) -> str:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise RuntimeError(f"failed to fetch {url}")
    text = trafilatura.extract(
        downloaded, include_comments=False, include_tables=True, output_format="markdown"
    )
    if not text:
        raise RuntimeError(f"no extractable content at {url}")
    return _clean(text)


EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".epub": extract_epub,
    ".md": extract_text,
    ".markdown": extract_text,
    ".txt": extract_text,
}


def extract_to_markdown(path: Path) -> str:
    """Dispatch by extension. Caller handles URLs separately via extract_url()."""
    ext = path.suffix.lower()
    if ext not in EXTRACTORS:
        raise ValueError(f"unsupported extension: {ext} (file: {path.name})")
    return EXTRACTORS[ext](path)


_SLUG_RX = re.compile(r"[^a-z0-9]+")


def url_to_slug(url: str) -> str:
    """Stable, filesystem-safe slug for a URL."""
    base = re.sub(r"^https?://", "", url).strip("/").lower()
    slug = _SLUG_RX.sub("-", base).strip("-")
    return (slug[:80] or "url") + ".md"
