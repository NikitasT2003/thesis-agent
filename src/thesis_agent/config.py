"""Runtime configuration and workspace paths.

Single source of truth for where files live. `workspace_root()` is the user's
current directory when they invoke `thesis`; everything hangs off it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def workspace_root() -> Path:
    """The user's workspace = the directory they ran `thesis` from."""
    return Path.cwd().resolve()


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def research(self) -> Path:
        return self.root / "research"

    @property
    def raw(self) -> Path:
        return self.research / "raw"

    @property
    def wiki(self) -> Path:
        return self.research / "wiki"

    @property
    def urls_file(self) -> Path:
        return self.raw / "urls.txt"

    @property
    def index_json(self) -> Path:
        return self.raw / "_index.json"

    @property
    def wiki_index(self) -> Path:
        return self.wiki / "index.md"

    @property
    def style_dir(self) -> Path:
        return self.root / "style"

    @property
    def style_samples(self) -> Path:
        return self.style_dir / "samples"

    @property
    def style_guide(self) -> Path:
        return self.style_dir / "STYLE.md"

    @property
    def thesis_dir(self) -> Path:
        return self.root / "thesis"

    @property
    def outline(self) -> Path:
        return self.thesis_dir / "outline.md"

    @property
    def chapters(self) -> Path:
        return self.thesis_dir / "chapters"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def checkpoints_db(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def store_db(self) -> Path:
        return self.data_dir / "store.db"

    @property
    def thread_file(self) -> Path:
        return self.data_dir / ".thread"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def agents_md(self) -> Path:
        return self.root / "AGENTS.md"

    def all_writable_roots(self) -> list[Path]:
        """Paths the agent may write under (subject to WriteGuard scope)."""
        return [self.research / "wiki", self.style_dir, self.thesis_dir, self.index_json]

    def all_deny_roots(self) -> list[Path]:
        """Paths the agent must NEVER write to."""
        return [self.data_dir, self.raw]


def paths() -> Paths:
    return Paths(workspace_root())


@dataclass(frozen=True)
class ModelConfig:
    drafter: str
    curator: str
    researcher: str


def provider() -> str:
    """Current LLM provider: 'anthropic' (default) or 'openrouter'."""
    return (os.environ.get("THESIS_PROVIDER") or "anthropic").strip().lower()


def load_env(required_api_key: bool = True) -> None:
    """Load .env from workspace and (optionally) verify the right key is set."""
    env = paths().env_file
    if env.exists():
        load_dotenv(env)
    if not required_api_key:
        return
    prov = provider()
    if prov == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Run `thesis setup` or edit .env."
            )
    elif prov == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Run `thesis setup` or edit .env."
            )
    else:
        raise RuntimeError(
            f"unknown THESIS_PROVIDER={prov!r} (expected 'anthropic' or 'openrouter')."
        )


# Default model IDs per provider. Per-role overrides via THESIS_MODEL_* env vars.
_DEFAULTS: dict[str, ModelConfig] = {
    "anthropic": ModelConfig(
        drafter="anthropic:claude-sonnet-4-6",
        curator="anthropic:claude-sonnet-4-6",
        researcher="anthropic:claude-haiku-4-5-20251001",
    ),
    "openrouter": ModelConfig(
        drafter="anthropic/claude-sonnet-4-5",
        curator="anthropic/claude-sonnet-4-5",
        researcher="anthropic/claude-haiku-4-5",
    ),
}


def models() -> ModelConfig:
    """Resolve model IDs for the current provider, honouring env overrides."""
    prov = provider()
    base = _DEFAULTS.get(prov, _DEFAULTS["anthropic"])
    return ModelConfig(
        drafter=os.environ.get("THESIS_MODEL_DRAFTER") or base.drafter,
        curator=os.environ.get("THESIS_MODEL_CURATOR") or base.curator,
        researcher=os.environ.get("THESIS_MODEL_RESEARCHER") or base.researcher,
    )


def make_model(model_id: str, *, temperature: float = 0.0):
    """Build a LangChain chat model for the current provider.

    - anthropic: uses `init_chat_model("anthropic:<id>")` — deepagents idiom.
    - openrouter: returns a `ChatOpenAI` pointed at OpenRouter with headers.
    """
    prov = provider()
    if prov == "openrouter":
        from langchain_openai import ChatOpenAI

        base_url = os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
        headers: dict[str, str] = {}
        if site := os.environ.get("OPENROUTER_SITE_URL"):
            headers["HTTP-Referer"] = site
        if name := os.environ.get("OPENROUTER_SITE_NAME"):
            headers["X-Title"] = name
        # Strip an "openrouter/" prefix if the user pasted one.
        model_id = model_id.removeprefix("openrouter/")
        return ChatOpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url=base_url,
            model=model_id,
            temperature=temperature,
            default_headers=headers or None,
        )

    # Default: anthropic / init_chat_model string form.
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_id, temperature=temperature)


def read_thread_id() -> str:
    """Persisted default thread id. Created on first run."""
    p = paths().thread_file
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or "main"
    return "main"


def write_thread_id(thread_id: str) -> None:
    p = paths().thread_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(thread_id, encoding="utf-8")
