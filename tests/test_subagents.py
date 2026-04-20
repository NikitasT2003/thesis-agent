"""Subagent configuration integrity."""

from __future__ import annotations

from thesis_agent.config import ModelConfig
from thesis_agent.subagents import (
    DRAFTER_PROMPT,
    RESEARCHER_PROMPT,
    WIKI_CURATOR_PROMPT,
    get_subagents,
)


def _stub_models() -> ModelConfig:
    return ModelConfig(
        drafter="anthropic:claude-sonnet-4-6",
        curator="anthropic:claude-sonnet-4-6",
        researcher="anthropic:claude-haiku-4-5-20251001",
    )


def test_three_subagents_with_expected_names(monkeypatch):
    # Avoid network: patch make_model to a sentinel.
    import thesis_agent.subagents as sa

    sentinel = object()
    monkeypatch.setattr(sa, "make_model", lambda *a, **kw: sentinel)

    subs = get_subagents(_stub_models())
    assert len(subs) == 3
    names = {s["name"] for s in subs}
    assert names == {"wiki-curator", "drafter", "researcher"}


def test_each_subagent_has_required_fields(monkeypatch):
    import thesis_agent.subagents as sa

    monkeypatch.setattr(sa, "make_model", lambda *a, **kw: object())
    for sub in get_subagents(_stub_models()):
        assert "name" in sub and isinstance(sub["name"], str)
        assert "description" in sub and len(sub["description"]) > 40  # triggers must be informative
        assert "system_prompt" in sub and len(sub["system_prompt"]) > 100
        assert "model" in sub


def test_prompts_mention_grounding_and_scope():
    # Wiki curator must mention its write scope + the citation format.
    assert "research/wiki" in WIKI_CURATOR_PROMPT
    assert "research/raw/_index.json" in WIKI_CURATOR_PROMPT
    assert "[src:" in WIKI_CURATOR_PROMPT

    # Drafter must enforce citations + style + scope.
    assert "[src:" in DRAFTER_PROMPT
    assert "thesis/" in DRAFTER_PROMPT
    assert "STYLE.md" in DRAFTER_PROMPT

    # Researcher must declare itself read-only and refuse writes.
    assert "READ-ONLY" in RESEARCHER_PROMPT or "read-only" in RESEARCHER_PROMPT.lower()
    assert "no write" in RESEARCHER_PROMPT.lower() or "cannot write" in RESEARCHER_PROMPT.lower()


def test_prompts_forbid_web_and_shell():
    for p in (WIKI_CURATOR_PROMPT, DRAFTER_PROMPT, RESEARCHER_PROMPT):
        low = p.lower()
        assert "no web" in low or "no web access" in low
        assert "no shell" in low


def test_subagent_models_come_from_config(monkeypatch):
    import thesis_agent.subagents as sa

    seen: list[str] = []

    def fake(model_id, **kw):
        seen.append(model_id)
        return f"MODEL({model_id})"

    monkeypatch.setattr(sa, "make_model", fake)
    subs = get_subagents(_stub_models())
    # Curator uses curator model, drafter uses drafter model, researcher uses researcher model.
    by_name = {s["name"]: s["model"] for s in subs}
    assert by_name["wiki-curator"] == "MODEL(anthropic:claude-sonnet-4-6)"
    assert by_name["drafter"] == "MODEL(anthropic:claude-sonnet-4-6)"
    assert by_name["researcher"] == "MODEL(anthropic:claude-haiku-4-5-20251001)"
