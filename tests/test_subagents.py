"""Subagent YAML loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent.config import ModelConfig
from thesis_agent.subagents import load_subagents


def _stub_models() -> ModelConfig:
    return ModelConfig(
        drafter="anthropic:claude-sonnet-4-6",
        curator="anthropic:claude-sonnet-4-6",
        researcher="anthropic:claude-haiku-4-5-20251001",
    )


@pytest.fixture
def patch_make_model(monkeypatch):
    """Replace make_model with a stub that records calls and returns a
    sentinel, so we can verify role→model resolution without touching
    provider SDKs."""
    import thesis_agent.subagents as sub_mod

    seen: list[tuple[str, str | None]] = []

    def fake(model_id: str, *, role=None, **kwargs):
        seen.append((model_id, role))
        return f"MODEL({model_id}|{role})"

    monkeypatch.setattr(sub_mod, "make_model", fake)
    return seen


def test_returns_empty_when_yaml_missing(tmp_path: Path):
    assert load_subagents(tmp_path / "nope.yaml", _stub_models()) == []


def test_loads_all_entries(tmp_path: Path, patch_make_model):
    p = tmp_path / "subagents.yaml"
    p.write_text(
        """
- name: alpha
  description: does alpha things
  system_prompt: you are alpha
  model: drafter

- name: beta
  description: does beta things
  system_prompt: you are beta
  model: researcher
""",
        encoding="utf-8",
    )
    out = load_subagents(p, _stub_models())
    assert len(out) == 2
    names = {e["name"] for e in out}
    assert names == {"alpha", "beta"}
    # Required fields pass through
    for entry in out:
        assert "description" in entry
        assert "system_prompt" in entry
        assert "model" in entry


def test_role_tag_resolves_to_configured_model(tmp_path: Path, patch_make_model):
    p = tmp_path / "subagents.yaml"
    p.write_text(
        """
- name: d
  description: drafter
  system_prompt: ""
  model: drafter
- name: c
  description: curator
  system_prompt: ""
  model: curator
- name: r
  description: researcher
  system_prompt: ""
  model: researcher
""",
        encoding="utf-8",
    )
    load_subagents(p, _stub_models())
    resolved = dict(patch_make_model)  # (model_id, role) pairs
    assert resolved["anthropic:claude-sonnet-4-6"] in ("drafter", "curator")
    assert resolved["anthropic:claude-haiku-4-5-20251001"] == "researcher"


def test_unknown_role_falls_back_to_drafter(tmp_path: Path, patch_make_model):
    p = tmp_path / "subagents.yaml"
    p.write_text(
        """
- name: weird
  description: weird role
  system_prompt: ""
  model: genius
""",
        encoding="utf-8",
    )
    load_subagents(p, _stub_models())
    # The drafter model id got used; role arg passed as None (unknown role)
    assert patch_make_model == [("anthropic:claude-sonnet-4-6", None)]


def test_invalid_top_level_raises(tmp_path: Path, patch_make_model):
    p = tmp_path / "subagents.yaml"
    p.write_text("not: a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="list"):
        load_subagents(p, _stub_models())


def test_non_dict_entries_skipped(tmp_path: Path, patch_make_model):
    p = tmp_path / "subagents.yaml"
    p.write_text(
        """
- "just a string"
- name: real
  description: real one
  system_prompt: ""
  model: drafter
""",
        encoding="utf-8",
    )
    out = load_subagents(p, _stub_models())
    assert [e["name"] for e in out] == ["real"]


def test_bundled_subagents_yaml_parses():
    """The repo-level subagents.yaml must load cleanly — prevents the file
    drifting out of sync with the loader."""
    repo_root = Path(__file__).resolve().parent.parent
    bundled = repo_root / "subagents.yaml"
    assert bundled.exists(), "subagents.yaml missing from repo root"
    out = load_subagents(bundled, _stub_models())
    # Three canonical subagents: wiki-curator, drafter, researcher.
    names = {e["name"] for e in out}
    assert names == {"wiki-curator", "drafter", "researcher"}
