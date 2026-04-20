"""Config module: provider selection, env loading, model resolution, thread persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from thesis_agent.config import (
    ModelConfig,
    load_env,
    make_model,
    models,
    paths,
    provider,
    read_thread_id,
    write_thread_id,
)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch):
    """Isolated workspace with all relevant env vars cleared."""
    monkeypatch.chdir(tmp_path)
    for v in (
        "THESIS_PROVIDER",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_SITE_NAME",
        "THESIS_MODEL_DRAFTER",
        "THESIS_MODEL_CURATOR",
        "THESIS_MODEL_RESEARCHER",
    ):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def test_paths_all_under_root(ws: Path):
    p = paths()
    assert p.root == ws.resolve()
    # Every derived path must be inside root
    for sub in (
        p.research, p.raw, p.wiki, p.urls_file, p.index_json, p.wiki_index,
        p.style_dir, p.style_samples, p.style_guide,
        p.thesis_dir, p.outline, p.chapters,
        p.data_dir, p.checkpoints_db, p.store_db, p.thread_file,
        p.env_file, p.agents_md,
    ):
        assert sub.is_relative_to(p.root) or sub == p.root, f"{sub} escapes {p.root}"


def test_paths_writable_roots_do_not_include_raw_or_data(ws: Path):
    p = paths()
    writable = p.all_writable_roots()
    deny = p.all_deny_roots()
    assert p.raw in deny
    assert p.data_dir in deny
    assert p.raw not in writable
    assert p.data_dir not in writable


# ---------------------------------------------------------------------------
# provider()
# ---------------------------------------------------------------------------

def test_provider_defaults_to_anthropic(ws: Path):
    assert provider() == "anthropic"


def test_provider_reads_env_var(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    assert provider() == "openrouter"


def test_provider_normalises_case_and_spaces(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "  OpenRouter  ")
    assert provider() == "openrouter"


# ---------------------------------------------------------------------------
# load_env()
# ---------------------------------------------------------------------------

def test_load_env_raises_when_anthropic_key_missing(ws: Path):
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        load_env(required_api_key=True)


def test_load_env_raises_when_openrouter_key_missing(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        load_env(required_api_key=True)


def test_load_env_raises_on_unknown_provider(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "bogus")
    with pytest.raises(RuntimeError, match="unknown THESIS_PROVIDER"):
        load_env(required_api_key=True)


def test_load_env_noop_when_not_required(ws: Path):
    # No key, no raise
    load_env(required_api_key=False)


def test_load_env_reads_dotenv_file(ws: Path, monkeypatch):
    (ws / ".env").write_text(
        "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-xxx\n",
        encoding="utf-8",
    )
    # Ensure the value isn't already in env
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    load_env(required_api_key=True)
    import os
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-xxx"


def test_load_env_dotenv_overrides_shell_for_api_keys(ws: Path, monkeypatch):
    """Regression: a stale shell export used to override a freshly-saved
    .env value, leaving the agent with a bad key. `.env` now wins for
    the variables the wizard owns."""
    (ws / ".env").write_text(
        "THESIS_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-fresh-from-env\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-stale-from-shell")
    load_env(required_api_key=True)
    import os
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-fresh-from-env"


def test_load_env_keeps_shell_value_when_dotenv_missing_key(ws: Path, monkeypatch):
    """If .env doesn't mention the variable, the shell value must be
    preserved — we only override for vars we actually own."""
    (ws / ".env").write_text("THESIS_PROVIDER=anthropic\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-shell-only")
    load_env(required_api_key=True)
    import os
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-from-shell-only"


def test_load_env_preserves_unrelated_shell_vars(ws: Path, monkeypatch):
    """Shell vars we don't own (PATH, HOME, etc.) must not be touched."""
    (ws / ".env").write_text(
        "THESIS_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-ant-x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOME_UNRELATED_VAR", "keep-me")
    load_env(required_api_key=True)
    import os
    assert os.environ.get("SOME_UNRELATED_VAR") == "keep-me"


# ---------------------------------------------------------------------------
# models()
# ---------------------------------------------------------------------------

def test_models_anthropic_defaults(ws: Path):
    m = models()
    assert m.drafter.startswith("anthropic:")
    assert m.curator.startswith("anthropic:")
    assert m.researcher.startswith("anthropic:")
    assert "haiku" in m.researcher


def test_models_openrouter_defaults(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    m = models()
    # OpenRouter format: provider/model
    assert "/" in m.drafter
    assert "/" in m.researcher
    assert "haiku" in m.researcher


def test_models_env_overrides_win(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_MODEL_DRAFTER", "custom/drafter")
    monkeypatch.setenv("THESIS_MODEL_CURATOR", "custom/curator")
    monkeypatch.setenv("THESIS_MODEL_RESEARCHER", "custom/researcher")
    m = models()
    assert m == ModelConfig("custom/drafter", "custom/curator", "custom/researcher")


def test_models_unknown_provider_falls_back_to_anthropic_defaults(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "xxx")
    m = models()
    assert m.drafter.startswith("anthropic:")


# ---------------------------------------------------------------------------
# make_model()
# ---------------------------------------------------------------------------

def test_make_model_anthropic_returns_chat_anthropic(ws: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    obj = make_model("anthropic:claude-haiku-4-5-20251001")
    # Duck-type: has .invoke
    assert hasattr(obj, "invoke")
    assert type(obj).__name__ == "ChatAnthropic"


def test_make_model_openrouter_returns_chat_openai_with_base_url(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
    obj = make_model("anthropic/claude-haiku-4-5")
    assert type(obj).__name__ == "ChatOpenAI"
    base = getattr(obj, "openai_api_base", None) or getattr(obj, "base_url", None)
    assert base is not None and "openrouter.ai" in str(base)


def test_make_model_openrouter_strips_openrouter_prefix(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
    obj = make_model("openrouter/anthropic/claude-haiku-4-5")
    # Model name should no longer carry the redundant prefix.
    mn = getattr(obj, "model_name", None) or getattr(obj, "model", None)
    assert mn is not None and not str(mn).startswith("openrouter/")


def test_make_model_openrouter_passes_attribution_headers(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://example.com")
    monkeypatch.setenv("OPENROUTER_SITE_NAME", "My App")
    obj = make_model("anthropic/claude-haiku-4-5")
    headers = getattr(obj, "default_headers", None) or {}
    assert headers.get("HTTP-Referer") == "https://example.com"
    assert headers.get("X-Title") == "My App"


def test_make_model_openrouter_respects_custom_base_url(ws: Path, monkeypatch):
    monkeypatch.setenv("THESIS_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-dummy")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://proxy.example.com/v1")
    obj = make_model("anthropic/claude-haiku-4-5")
    base = getattr(obj, "openai_api_base", None) or getattr(obj, "base_url", None)
    assert base is not None and "proxy.example.com" in str(base)


# ---------------------------------------------------------------------------
# thread id persistence
# ---------------------------------------------------------------------------

def test_read_thread_id_defaults_to_main_when_missing(ws: Path):
    assert read_thread_id() == "main"


def test_write_then_read_thread_id_round_trips(ws: Path):
    write_thread_id("t-1234")
    assert read_thread_id() == "t-1234"


def test_write_thread_id_creates_parent_dir(ws: Path):
    # data/ doesn't exist yet
    assert not (ws / "data").exists()
    write_thread_id("t-X")
    assert (ws / "data" / ".thread").exists()


def test_read_thread_id_strips_and_handles_blank(ws: Path):
    d = ws / "data"
    d.mkdir()
    (d / ".thread").write_text("   \n", encoding="utf-8")
    assert read_thread_id() == "main"  # falls back to default when blank
