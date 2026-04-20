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


_API_KEY_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_SITE_URL",
    "OPENROUTER_SITE_NAME",
    "THESIS_PROVIDER",
    "THESIS_MODEL_DRAFTER",
    "THESIS_MODEL_CURATOR",
    "THESIS_MODEL_RESEARCHER",
)


def _parse_env_file(path) -> dict[str, str]:
    """Minimal .env parser returning {name: raw_value}. No expansion."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_env(required_api_key: bool = True) -> None:
    """Load `.env` and make sure its values win over stale shell env vars.

    Rationale: the setup wizard writes an explicit, freshly-validated value
    into `.env`. If the user's shell also has the same variable exported
    from an earlier session (e.g. a rotated key), `python-dotenv`'s default
    behaviour would silently keep the shell value and the new key would
    appear to do nothing. We therefore:
      1. Parse `.env` ourselves.
      2. For every variable we own (API keys + model overrides), if the
         file disagrees with the shell, `.env` wins — and we print a one-line
         notice so the user knows what happened.
      3. Fall through to `load_dotenv` for anything else in the file.
    """
    env = paths().env_file
    file_values = _parse_env_file(env)

    overridden: list[str] = []
    for name in _API_KEY_VARS:
        if name not in file_values:
            continue
        shell_val = os.environ.get(name)
        if shell_val is not None and shell_val != file_values[name]:
            overridden.append(name)
        os.environ[name] = file_values[name]

    # Load anything else from .env without clobbering shell env.
    if env.exists():
        load_dotenv(env, override=False)

    if overridden:
        # Best-effort notice so the user understands why a freshly-saved
        # key is suddenly being used instead of their shell export.
        msg = (
            "thesis-agent: .env values overrode shell env for "
            f"{', '.join(overridden)}. "
            "To use your shell values instead, remove those lines from .env."
        )
        # Only print when running from a TTY to avoid spamming CI logs.
        try:
            import sys
            if sys.stderr.isatty():
                print(msg, file=sys.stderr)
        except Exception:
            pass

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
#
# Rationale for the OpenRouter defaults:
#   - GLM 5.1 (`z-ai/glm-5.1`): strong long-horizon coding + writing performance,
#     ~$1 per 1M input tokens — roughly 3x cheaper than Claude Sonnet 4 for the
#     quality-critical drafter + curator roles.
#   - Gemma 4 31B IT (`google/gemma-4-31b-it`): ~$0.13 per 1M input, 256K
#     context, solid instruction-following — great for the researcher role
#     which only reads and reports with citations.
# Users who want the old Anthropic-via-OpenRouter mapping can override with
# THESIS_MODEL_* env vars or pass --provider anthropic.
_DEFAULTS: dict[str, ModelConfig] = {
    "anthropic": ModelConfig(
        drafter="anthropic:claude-sonnet-4-6",
        curator="anthropic:claude-sonnet-4-6",
        researcher="anthropic:claude-haiku-4-5-20251001",
    ),
    "openrouter": ModelConfig(
        drafter="google/gemma-4-31b-it:free",
        curator="google/gemma-4-31b-it:free",
        researcher="google/gemma-4-31b-it:free",
    ),
}

# Default fallback chain for OpenRouter. OpenRouter's `models` routing param
# accepts a list of IDs and falls back in order on provider outage / rate
# limit / content filter. Users can override with THESIS_OPENROUTER_FALLBACK
# (comma-separated) or disable entirely with THESIS_OPENROUTER_FALLBACK="".
_OPENROUTER_DEFAULT_FALLBACK: tuple[str, ...] = ("google/gemma-4-31b-it",)


def openrouter_fallback_chain(primary: str) -> list[str]:
    """Return [primary, *unique_fallbacks] for OpenRouter's `models` routing.

    Honours $THESIS_OPENROUTER_FALLBACK (comma-separated). Empty string
    explicitly disables fallback. The primary is always first, duplicates
    are removed while preserving order, and the primary is never re-listed
    later in the chain.
    """
    raw = os.environ.get("THESIS_OPENROUTER_FALLBACK")
    if raw is None:
        candidates = list(_OPENROUTER_DEFAULT_FALLBACK)
    elif not raw.strip():
        candidates = []
    else:
        candidates = [m.strip() for m in raw.split(",") if m.strip()]

    chain: list[str] = [primary]
    seen = {primary}
    for m in candidates:
        if m not in seen:
            chain.append(m)
            seen.add(m)
    return chain


def models() -> ModelConfig:
    """Resolve model IDs for the current provider, honouring env overrides."""
    prov = provider()
    base = _DEFAULTS.get(prov, _DEFAULTS["anthropic"])
    return ModelConfig(
        drafter=os.environ.get("THESIS_MODEL_DRAFTER") or base.drafter,
        curator=os.environ.get("THESIS_MODEL_CURATOR") or base.curator,
        researcher=os.environ.get("THESIS_MODEL_RESEARCHER") or base.researcher,
    )


def _role_max_tokens(role: str | None) -> int:
    """Per-role output caps. Overridable via env vars.

    Rationale: without a cap Sonnet will emit up to 8K tokens per reply
    and rack up cost fast on multi-turn agent loops. Caps picked from the
    shape of each role's output:
      - drafter   ~ full thesis section  (4K is generous)
      - curator   ~ one wiki page        (2K fits the template + buffer)
      - researcher ~ a citation-backed summary (1K)
      - default   ~ 2K
    """
    defaults = {"drafter": 4000, "curator": 2000, "researcher": 1000}
    env_key = f"THESIS_MAX_TOKENS_{(role or 'DEFAULT').upper()}"
    override = os.environ.get(env_key)
    if override and override.strip().isdigit():
        return int(override)
    return defaults.get(role or "", 2000)


def make_model(
    model_id: str,
    *,
    temperature: float = 0.0,
    role: str | None = None,
    max_tokens: int | None = None,
):
    """Build a LangChain chat model for the current provider.

    - anthropic: uses `init_chat_model("anthropic:<id>")` — deepagents idiom.
    - openrouter: returns a `ChatOpenAI` pointed at OpenRouter with headers.

    `role` (drafter/curator/researcher) drives the default `max_tokens`
    output cap. Explicit `max_tokens` wins over role-derived defaults.
    Env overrides: `THESIS_MAX_TOKENS_DRAFTER` / `..._CURATOR` / `..._RESEARCHER`.
    """
    if max_tokens is None:
        max_tokens = _role_max_tokens(role)

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
        # OpenRouter-specific: use its `models` routing parameter so requests
        # fall back to a cheaper / open model when the primary is unavailable
        # (outage, rate limit, content filter). Disabled with empty env var.
        extra_body: dict = {}
        chain = openrouter_fallback_chain(model_id)
        if len(chain) > 1:
            extra_body["models"] = chain
        return ChatOpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            base_url=base_url,
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            default_headers=headers or None,
            extra_body=extra_body or None,
        )

    # Default: anthropic / init_chat_model string form.
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_id, temperature=temperature, max_tokens=max_tokens)


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
