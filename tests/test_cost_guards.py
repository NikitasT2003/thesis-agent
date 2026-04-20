"""Cost safety: per-role output caps + recursion limit.

Context: a user burned $10 in a minute running Claude Sonnet 4.5 because
(a) `make_model` didn't set `max_tokens`, so replies went up to 8K, and
(b) the agent had no `recursion_limit`, so it looped tens of times on
one source. These tests lock in the caps that prevent that.
"""

from __future__ import annotations

import pytest

from thesis_agent.agent import _DEFAULT_RECURSION_LIMIT, _recursion_limit
from thesis_agent.config import _role_max_tokens, make_model


@pytest.fixture
def clean_env(monkeypatch):
    for v in (
        "THESIS_MAX_TOKENS_DRAFTER",
        "THESIS_MAX_TOKENS_CURATOR",
        "THESIS_MAX_TOKENS_RESEARCHER",
        "THESIS_MAX_TOKENS_DEFAULT",
        "THESIS_RECURSION_LIMIT",
        "THESIS_PROVIDER",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------------------
# _role_max_tokens
# ---------------------------------------------------------------------------

class TestRoleMaxTokens:
    def test_default_caps_are_conservative(self, clean_env):
        assert _role_max_tokens("drafter") == 4000
        assert _role_max_tokens("curator") == 2000
        assert _role_max_tokens("researcher") == 1000
        # Unknown role / default falls back to 2000 (not Sonnet's 8192 ceiling)
        assert _role_max_tokens(None) == 2000
        assert _role_max_tokens("unknown-role") == 2000

    def test_env_override_per_role(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_MAX_TOKENS_DRAFTER", "8000")
        monkeypatch.setenv("THESIS_MAX_TOKENS_CURATOR", "3000")
        assert _role_max_tokens("drafter") == 8000
        assert _role_max_tokens("curator") == 3000
        # Roles without an override still use defaults
        assert _role_max_tokens("researcher") == 1000

    def test_non_digit_env_is_ignored(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_MAX_TOKENS_DRAFTER", "lots")
        assert _role_max_tokens("drafter") == 4000

    def test_default_env_override_affects_unknown_role(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_MAX_TOKENS_DEFAULT", "512")
        # Unknown roles should pick up the DEFAULT override path. Our helper
        # falls back to the hardcoded 2000 for unknowns, BUT if the user sets
        # THESIS_MAX_TOKENS_DEFAULT we honour it for the `None` role.
        assert _role_max_tokens(None) == 512


# ---------------------------------------------------------------------------
# make_model passes max_tokens through
# ---------------------------------------------------------------------------

class TestMakeModelCaps:
    def test_anthropic_model_receives_max_tokens(self, clean_env, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        obj = make_model("anthropic:claude-haiku-4-5-20251001", role="curator")
        # langchain-anthropic stores the cap as .max_tokens
        assert getattr(obj, "max_tokens", None) == 2000

    def test_openrouter_model_receives_max_tokens(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
        obj = make_model("z-ai/glm-5.1", role="drafter")
        cap = getattr(obj, "max_tokens", None) or getattr(obj, "max_completion_tokens", None)
        assert cap == 4000

    def test_explicit_max_tokens_wins_over_role_default(self, clean_env, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        obj = make_model(
            "anthropic:claude-haiku-4-5-20251001",
            role="drafter",
            max_tokens=123,
        )
        assert getattr(obj, "max_tokens", None) == 123


# ---------------------------------------------------------------------------
# _recursion_limit
# ---------------------------------------------------------------------------

class TestRecursionLimit:
    def test_default_is_conservative(self, clean_env):
        assert _recursion_limit() == _DEFAULT_RECURSION_LIMIT
        assert _DEFAULT_RECURSION_LIMIT <= 50  # regression guard — don't raise silently

    def test_env_override(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_RECURSION_LIMIT", "40")
        assert _recursion_limit() == 40

    def test_env_override_has_lower_bound(self, clean_env, monkeypatch):
        # Very low values would make the agent unusable — clamp to >= 5.
        monkeypatch.setenv("THESIS_RECURSION_LIMIT", "1")
        assert _recursion_limit() >= 5

    def test_non_digit_env_is_ignored(self, clean_env, monkeypatch):
        monkeypatch.setenv("THESIS_RECURSION_LIMIT", "unlimited")
        assert _recursion_limit() == _DEFAULT_RECURSION_LIMIT


# ---------------------------------------------------------------------------
# invoke() config passes through recursion_limit
# ---------------------------------------------------------------------------

class TestInvokeConfig:
    def test_invoke_sets_recursion_limit_in_config(self, clean_env, monkeypatch, tmp_path):
        """Smoke test: our `invoke()` wrapper must attach `recursion_limit`
        to the config dict it passes to the underlying agent."""
        from contextlib import contextmanager

        from thesis_agent import agent as agent_mod

        captured: dict = {}

        class _FakeAgent:
            def invoke(self, payload, *, config=None):
                captured.update(config or {})
                return {"messages": [{"role": "assistant", "content": "ok"}]}

        @contextmanager
        def fake_build_agent(**kw):
            yield _FakeAgent()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        monkeypatch.setattr(agent_mod, "build_agent", fake_build_agent)
        agent_mod.invoke("hi", thread_id="t-test")

        assert "recursion_limit" in captured
        assert captured["recursion_limit"] == _DEFAULT_RECURSION_LIMIT
        assert captured["configurable"]["thread_id"] == "t-test"

    def test_env_override_propagates_to_invoke(self, clean_env, monkeypatch, tmp_path):
        from contextlib import contextmanager

        from thesis_agent import agent as agent_mod

        captured: dict = {}

        class _FakeAgent:
            def invoke(self, payload, *, config=None):
                captured.update(config or {})
                return {"messages": [{"role": "assistant", "content": "ok"}]}

        @contextmanager
        def fake_build_agent(**kw):
            yield _FakeAgent()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
        monkeypatch.setenv("THESIS_RECURSION_LIMIT", "7")
        monkeypatch.setattr(agent_mod, "build_agent", fake_build_agent)
        agent_mod.invoke("hi", thread_id="t-test")

        assert captured["recursion_limit"] == 7


# ---------------------------------------------------------------------------
# Cost sanity check: worst-case per-call output bill
# ---------------------------------------------------------------------------

def test_worst_case_output_spend_per_call_is_bounded(clean_env):
    """At Sonnet 4.5 output prices ($15/M) a single drafter reply at its
    cap costs at most: 4000 tokens * $15 / 1_000_000 = $0.06. Sanity check
    the cap hasn't drifted into dangerous territory."""
    price_per_million_output = 15.0  # Sonnet 4.5 worst case
    for role, expected_max in (("drafter", 4000), ("curator", 2000), ("researcher", 1000)):
        cap = _role_max_tokens(role)
        assert cap == expected_max
        max_cost = cap * price_per_million_output / 1_000_000
        assert max_cost <= 0.10, (
            f"{role} cap {cap} would cost ${max_cost:.3f} per reply — too high"
        )
