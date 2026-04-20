"""Project-level schema checks: skills frontmatter, AGENTS.md integrity,
examples layout, README sanity.

These catch drift — renaming a skill without updating AGENTS.md, dropping a
required frontmatter field, or forgetting to ship the example workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

EXPECTED_SKILLS = {
    "ingest-sources",
    "wiki-curator",
    "thesis-writer",
    "style-learner",
    "citation-linter",
}


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            fields[key] = value.strip()
            current_key = key
        elif current_key is not None and line.startswith(" "):
            fields[current_key] = (fields[current_key] + " " + line.strip()).strip()
    return fields


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def test_all_expected_skills_ship():
    present = {p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir()}
    assert present == EXPECTED_SKILLS


@pytest.mark.parametrize("skill", sorted(EXPECTED_SKILLS))
class TestSkillFile:
    def _file(self, skill: str) -> Path:
        return REPO_ROOT / "skills" / skill / "SKILL.md"

    def test_file_exists(self, skill: str):
        assert self._file(skill).exists()

    def test_frontmatter_parses_with_real_yaml(self, skill: str):
        """Regression: an earlier description contained `status: pending`
        which PyYAML parsed as a new mapping key, crashing the agent at
        boot. Every SKILL.md must parse cleanly with yaml.safe_load."""
        import yaml

        text = self._file(skill).read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        assert m, f"{skill}: no YAML frontmatter"
        data = yaml.safe_load(m.group(1))
        assert isinstance(data, dict), f"{skill}: frontmatter did not parse to a mapping"
        assert data.get("name") == skill
        assert "description" in data
        assert isinstance(data["description"], str)
        # Description must be substantive enough to be a useful trigger.
        assert len(data["description"]) >= 80

    def test_has_valid_frontmatter(self, skill: str):
        text = self._file(skill).read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert fm, f"{skill}: no YAML frontmatter"
        assert "name" in fm and fm["name"] == skill
        assert "description" in fm
        # Description must contain useful trigger information
        assert len(fm["description"]) >= 80

    def test_frontmatter_only_allowed_keys(self, skill: str):
        """deepagents spec: only name/description/license/compatibility/allowed-tools/metadata."""
        import yaml

        allowed = {"name", "description", "license", "compatibility", "allowed-tools", "metadata"}
        m = FRONTMATTER_RE.match(self._file(skill).read_text(encoding="utf-8"))
        assert m
        data = yaml.safe_load(m.group(1))
        unexpected = set(data) - allowed
        assert not unexpected, f"{skill}: unexpected frontmatter keys: {unexpected}"

    def test_body_starts_after_frontmatter(self, skill: str):
        text = self._file(skill).read_text(encoding="utf-8")
        after = FRONTMATTER_RE.sub("", text, count=1).lstrip()
        assert after.startswith("#"), f"{skill}: body should start with a markdown heading"


# ---------------------------------------------------------------------------
# AGENTS.md
# ---------------------------------------------------------------------------

class TestAgentsMd:
    @pytest.fixture
    def text(self) -> str:
        return (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    def test_lists_three_layers(self, text: str):
        for phrase in ("research/raw", "research/wiki", "AGENTS.md"):
            assert phrase in text

    def test_declares_citation_format(self, text: str):
        assert "[src:" in text

    def test_declares_no_vector_search(self, text: str):
        assert "no vector search" in text.lower() or "no embeddings" in text.lower()

    def test_hard_rules_section_present(self, text: str):
        assert "Hard rules" in text or "hard rules" in text.lower()

    def test_page_template_present(self, text: str):
        for section in ("## Summary", "## Key claims", "## Conflicts", "## See also"):
            assert section in text


# ---------------------------------------------------------------------------
# Examples layout
# ---------------------------------------------------------------------------

class TestExamplesLayout:
    def test_example_source_ships(self):
        assert (REPO_ROOT / "examples" / "research" / "raw" / "example-source.md").exists()

    def test_sample_essay_ships(self):
        assert (REPO_ROOT / "examples" / "style" / "samples" / "sample-essay.md").exists()

    def test_example_outline_ships(self):
        assert (REPO_ROOT / "examples" / "thesis" / "outline.md").exists()


# ---------------------------------------------------------------------------
# pyproject / README sanity
# ---------------------------------------------------------------------------

class TestPackaging:
    def test_entry_point_in_pyproject(self):
        toml = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'thesis = "thesis_agent.cli:app"' in toml

    def test_mit_license_file(self):
        lic = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in lic

    def test_readme_mentions_both_providers(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "Anthropic" in readme
        assert "OpenRouter" in readme

    def test_readme_mentions_sandbox(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "sandbox" in readme.lower()
