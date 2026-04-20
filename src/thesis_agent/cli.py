"""`thesis` CLI. Friendly to non-technical users.

Commands:
  setup   - interactive first-run wizard (API key, workspace, examples)
  init    - non-interactive workspace scaffold
  status  - show what's in the workspace
  ingest  - deterministic source extraction (no LLM)
  curate  - agent builds wiki from pending sources
  style   - agent compiles style/STYLE.md from style/samples/
  chat    - interactive agent REPL
  write   - one-shot draft of a thesis section
  lint    - citation linter over thesis chapters
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Windows' default console code page (cp1252) cannot print common Unicode glyphs
# like arrows or check marks. Force UTF-8 on stdout/stderr if available — this
# is a no-op on terminals that already support it.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from thesis_agent import __version__  # noqa: E402
from thesis_agent.config import paths, read_thread_id, write_thread_id  # noqa: E402

app = typer.Typer(
    name="thesis",
    help="Thesis-writing agent — deepagents + Karpathy LLM Wiki, fully local.",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()


# ---------------------------------------------------------------------------
# utilities
# ---------------------------------------------------------------------------

def _ensure_workspace(force: bool = False) -> None:
    """Create missing workspace folders without clobbering existing files."""
    p = paths()
    dirs = [
        p.raw, p.wiki, p.style_samples, p.chapters, p.data_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    gitkeep_dirs = [p.raw, p.wiki, p.style_samples, p.chapters]
    for d in gitkeep_dirs:
        gk = d / ".gitkeep"
        if not gk.exists():
            gk.touch()

    urls = p.urls_file
    if not urls.exists():
        urls.write_text(
            "# Add URLs here, one per line. Lines starting with # are ignored.\n",
            encoding="utf-8",
        )

    # AGENTS.md: copy from bundled template if workspace lacks one.
    if not p.agents_md.exists() or force:
        src = Path(__file__).resolve().parent.parent.parent / "AGENTS.md"
        if src.exists():
            p.agents_md.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            p.agents_md.write_text(
                "# AGENTS.md\n\n(template missing from install — see repository.)\n",
                encoding="utf-8",
            )

    # Outline stub
    if not p.outline.exists():
        p.outline.write_text(
            "# Thesis outline\n\n"
            "## 1. Introduction\n\n"
            "## 2. Background\n\n"
            "## 3. Method\n\n"
            "## 4. Results\n\n"
            "## 5. Discussion\n\n"
            "## 6. Conclusion\n",
            encoding="utf-8",
        )


def _copy_examples(*, overwrite: bool = False) -> dict[str, int]:
    """Copy `examples/` into the workspace.

    Returns a dict with three counters so the caller can report honestly:
      - `copied`: files written to an empty target
      - `overwritten`: existing files replaced (only when `overwrite=True`)
      - `already_present`: skipped because the target already existed
                           (only when `overwrite=False`)
    A `source_missing` bool indicates the bundled `examples/` tree is absent
    — happens in odd installs (e.g. wheel without examples bundled).
    """
    result = {"copied": 0, "overwritten": 0, "already_present": 0, "source_missing": 0}
    src_root = Path(__file__).resolve().parent.parent.parent / "examples"
    if not src_root.exists():
        result["source_missing"] = 1
        return result
    p = paths()
    mapping = {
        src_root / "research" / "raw": p.raw,
        src_root / "style" / "samples": p.style_samples,
        src_root / "thesis": p.thesis_dir,
    }
    for src, dst in mapping.items():
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if not (f.is_file() and f.name != ".gitkeep"):
                continue
            target = dst / f.name
            if target.exists():
                if overwrite:
                    target.write_bytes(f.read_bytes())
                    result["overwritten"] += 1
                else:
                    result["already_present"] += 1
            else:
                target.write_bytes(f.read_bytes())
                result["copied"] += 1
    return result


# ---------------------------------------------------------------------------
# setup (interactive, non-tech-user friendly)
# ---------------------------------------------------------------------------

_PROVIDER_INFO = {
    "anthropic": {
        "label": "Anthropic (Claude) — direct API",
        "key_env": "ANTHROPIC_API_KEY",
        "key_hint": "starts with sk-ant-",
        "key_url": "https://console.anthropic.com/",
        "key_prefix": "sk-ant-",
    },
    "openrouter": {
        "label": "OpenRouter — unified gateway to many models",
        "key_env": "OPENROUTER_API_KEY",
        "key_hint": "starts with sk-or-",
        "key_url": "https://openrouter.ai/keys",
        "key_prefix": "sk-or-",
    },
}

_NUM_STEPS = 5


class _Cancelled(RuntimeError):
    """User pressed Ctrl-C / Esc to cancel the wizard."""


def _ask(fn, *args, **kwargs):
    """Wrap questionary .ask() with consistent Ctrl-C handling.

    Returns the user's answer, or raises _Cancelled if they bailed.
    Never aborts on empty — callers decide what empty means.
    """
    try:
        result = fn(*args, **kwargs).ask()
    except (KeyboardInterrupt, EOFError) as e:
        raise _Cancelled() from e
    if result is None:  # Ctrl-C inside questionary returns None
        raise _Cancelled()
    return result


def _step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]Step {n}/{_NUM_STEPS}[/] — [bold]{title}[/]")


def _humanise_error(msg: str) -> str:
    """Turn a raw provider exception into something actionable."""
    m = msg.lower()
    if "401" in m or "invalid api key" in m or "authentication" in m or "unauthorized" in m:
        return "the key was rejected by the provider. Double-check you copied the whole key (no spaces, no quotes)."
    if "402" in m or "insufficient" in m or "billing" in m or "credit" in m or "quota" in m:
        return "your account has no credits / billing is not set up. Add a payment method or credits on the provider's website."
    if "429" in m or "rate limit" in m:
        return "rate-limited right now. Wait a minute and rerun `thesis setup`."
    if "timeout" in m or "timed out" in m or "connection" in m or "network" in m:
        return "could not reach the provider — check your internet connection or a firewall/proxy."
    if "not found" in m or "404" in m:
        return "model not found (the wizard's validation model may have been renamed — this is harmless; pick 'Save anyway')."
    return msg[:200]


@app.command()
def setup(
    force: bool = typer.Option(False, "--force", help="Overwrite .env and AGENTS.md if they exist."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Don't prompt. Use flags + existing env only. For CI/scripting."
    ),
    provider_flag: str = typer.Option(
        None, "--provider", help="anthropic | openrouter. Skips the provider prompt.", case_sensitive=False,
    ),
    api_key_flag: str = typer.Option(
        None, "--api-key", help="API key for the chosen provider. Skips the key prompt.",
    ),
    skip_validation: bool = typer.Option(
        False, "--skip-validation", help="Skip the 1-token ping that checks the key.",
    ),
    skip_examples: bool = typer.Option(
        False, "--skip-examples", help="Don't copy example sources.",
    ),
    overwrite_examples: bool = typer.Option(
        False, "--overwrite-examples",
        help="Replace example files in the workspace even if they already exist.",
    ),
    quickstart: bool = typer.Option(
        False, "--quickstart", help="Accept sensible defaults for every prompt.",
    ),
) -> None:
    """Interactive first-run wizard. Handles retries, skips, Ctrl-C, and CI flags."""
    import questionary

    console.print(
        Panel.fit(
            "[bold]thesis-agent setup[/bold]\n\n"
            "Guided first-run. You can press [cyan]Ctrl-C[/] at any prompt to\n"
            "cancel safely — nothing is saved until the last step.\n\n"
            "Need to automate this in CI? Use [cyan]--non-interactive[/] with "
            "[cyan]--provider[/] + [cyan]--api-key[/].\n"
            "Prefer defaults? Add [cyan]--quickstart[/].",
            border_style="cyan",
            title=f"v{__version__}",
        )
    )

    p = paths()

    try:
        # Step 1: Provider ---------------------------------------------------
        _step(1, "Choose LLM provider")
        provider = _resolve_provider(
            provider_flag=provider_flag,
            non_interactive=non_interactive,
            quickstart=quickstart,
        )
        info = _PROVIDER_INFO[provider]
        console.print(f"  [green]→[/] using [cyan]{provider}[/]")

        # Step 2: API key ----------------------------------------------------
        _step(2, f"Provide {info['key_env']}")
        key = _resolve_api_key(
            info=info,
            api_key_flag=api_key_flag,
            force=force,
            non_interactive=non_interactive,
            quickstart=quickstart,
        )
        if key is None:
            console.print(
                Panel.fit(
                    f"Skipped key entry. Add it later by editing [cyan].env[/] and setting\n"
                    f"[cyan]{info['key_env']}=your-key[/], or rerun [cyan]thesis setup[/].",
                    border_style="yellow",
                    title="skipped",
                )
            )

        # Step 2b: OpenRouter extras -----------------------------------------
        extras: dict[str, str] = {}
        if provider == "openrouter" and key is not None and not (non_interactive or quickstart):
            try:
                add = _ask(questionary.confirm,
                    "Add optional OpenRouter attribution headers? (for their model-leaderboard ranking only)",
                    default=False,
                )
            except _Cancelled:
                add = False
            if add:
                extras["OPENROUTER_SITE_URL"] = _ask(
                    questionary.text, "Site URL (blank to skip):", default=""
                ).strip()
                extras["OPENROUTER_SITE_NAME"] = _ask(
                    questionary.text, "Site name (blank to skip):", default=""
                ).strip()

        # Step 3: Validate ---------------------------------------------------
        if key and not skip_validation:
            _step(3, "Validate key (1-token ping)")
            ok, raw = _validate_key(provider, key, extras)
            if ok:
                console.print("  [green]✓[/] key looks good.")
            else:
                nice = _humanise_error(raw)
                console.print(f"  [red]✗ validation failed:[/] {nice}")
                console.print(f"    [dim](raw: {raw[:120]})[/]")
                if non_interactive:
                    raise typer.Exit(1)
                choice = _ask(
                    questionary.select,
                    "What now?",
                    choices=[
                        questionary.Choice("Try a different key", value="retry"),
                        questionary.Choice("Save anyway and continue", value="save"),
                        questionary.Choice("Skip the key — add it later in .env", value="skip"),
                    ],
                    default="retry",
                )
                if choice == "retry":
                    key = _prompt_for_key_loop(info) or key
                    if key:
                        ok2, raw2 = _validate_key(provider, key, extras)
                        if ok2:
                            console.print("  [green]✓[/] key looks good.")
                        else:
                            console.print(f"  [yellow]still failing — saving anyway.[/] ({_humanise_error(raw2)})")
                elif choice == "skip":
                    key = None
        else:
            _step(3, "Validate key (skipped)")

        # Step 4: Workspace --------------------------------------------------
        _step(4, "Create workspace")
        console.print(f"  folder: [cyan]{p.root}[/]")
        if non_interactive or quickstart:
            proceed = True
        else:
            try:
                proceed = _ask(questionary.confirm, "Create workspace folders here?", default=True)
            except _Cancelled:
                raise
        if not proceed:
            console.print("  [yellow]skipped workspace creation.[/]")
        else:
            _ensure_workspace(force=force)
            console.print("  [green]✓[/] workspace ready.")

        # Step 5: Examples ---------------------------------------------------
        _step(5, "Copy examples (optional)")
        if skip_examples:
            copy_ex = False
        elif non_interactive or quickstart:
            copy_ex = not skip_examples
        else:
            try:
                copy_ex = _ask(
                    questionary.confirm,
                    "Copy example sources + sample style essay? (recommended for first run)",
                    default=True,
                )
            except _Cancelled:
                copy_ex = False
        if copy_ex:
            res = _copy_examples(overwrite=overwrite_examples)
            if res["source_missing"]:
                console.print(
                    "  [yellow]bundled examples/ tree not found in this install — "
                    "skipped.[/]"
                )
            elif res["copied"] or res["overwritten"]:
                parts = []
                if res["copied"]:
                    parts.append(f"copied {res['copied']} new")
                if res["overwritten"]:
                    parts.append(f"overwrote {res['overwritten']}")
                if res["already_present"]:
                    parts.append(f"left {res['already_present']} already-present in place")
                console.print(f"  [green]✓[/] examples: {', '.join(parts)}.")
            elif res["already_present"]:
                # The honest report: nothing to do, not a failure.
                console.print(
                    f"  [dim]examples already in your workspace ({res['already_present']} "
                    f"file(s)) — nothing to copy. Use [cyan]--overwrite-examples[/] "
                    f"if you want to replace them.[/]"
                )
            else:
                console.print("  [dim]no example files to copy.[/]")
        else:
            console.print("  [dim]skipped examples.[/]")

        # Persist .env (only AFTER all prompts, so Ctrl-C earlier writes nothing)
        env_updates: dict[str, str] = {"THESIS_PROVIDER": provider}
        if key:
            env_updates[info["key_env"]] = key
        env_updates.update({k: v for k, v in extras.items() if v})
        _write_env(env_updates)
        console.print(f"\n[dim]wrote[/] [cyan]{p.env_file}[/]")

        _print_next_steps(provider, has_key=bool(key))

    except _Cancelled:
        console.print(
            "\n[yellow]cancelled.[/] Nothing saved. Run [cyan]thesis setup[/] again to resume."
        )
        raise typer.Exit(130) from None


def _resolve_provider(
    *, provider_flag: str | None, non_interactive: bool, quickstart: bool,
) -> str:
    """Pick a provider: explicit flag > env > .env > prompt > default 'anthropic'."""
    import questionary

    if provider_flag:
        prov = provider_flag.strip().lower()
        if prov not in _PROVIDER_INFO:
            console.print(f"[red]--provider must be one of {list(_PROVIDER_INFO)}[/]")
            raise typer.Exit(2)
        return prov

    hinted = (
        os.environ.get("THESIS_PROVIDER")
        or _read_env_var("THESIS_PROVIDER")
        or "anthropic"
    ).strip().lower()
    hinted = hinted if hinted in _PROVIDER_INFO else "anthropic"

    if non_interactive or quickstart:
        return hinted

    anthropic_choice = questionary.Choice(_PROVIDER_INFO["anthropic"]["label"], value="anthropic")
    openrouter_choice = questionary.Choice(_PROVIDER_INFO["openrouter"]["label"], value="openrouter")
    default_choice = anthropic_choice if hinted != "openrouter" else openrouter_choice
    return _ask(
        questionary.select,
        "Which LLM provider do you want to use?",
        choices=[anthropic_choice, openrouter_choice],
        default=default_choice,
    )


def _mask_key(key: str) -> str:
    """Show the shape of a key without leaking it.

    Preserves the recognisable prefix (e.g. `sk-or-`, `sk-ant-`) and the last
    4 characters, hiding the middle. `sk-or-abc…wxyz`. For unusually short
    keys we just print the length.
    """
    k = (key or "").strip()
    if not k:
        return "<empty>"
    if len(k) < 12:
        return f"<{len(k)} chars>"
    # Prefix runs up to the second dash if present, otherwise first 6 chars.
    prefix_end = k.find("-", k.find("-") + 1)
    prefix = k[: prefix_end + 1] if 0 < prefix_end < 15 else k[:6]
    return f"{prefix}…{k[-4:]}"


def _resolve_api_key(
    *,
    info: dict,
    api_key_flag: str | None,
    force: bool,
    non_interactive: bool,
    quickstart: bool,
) -> str | None:
    """Return a key, or None if the user chose to skip.

    Precedence: --api-key flag > shell env > .env > interactive prompt (with retry).
    Always tells the user *where* an existing key came from, and shows a
    masked preview so they can recognise it before reusing.
    """
    import questionary

    if api_key_flag:
        return api_key_flag.strip()

    shell_key = (os.environ.get(info["key_env"]) or "").strip() or None
    env_key = _read_env_var(info["key_env"])

    # Source attribution: shell env wins at runtime (it overrides .env when
    # the agent boots via python-dotenv), so honour that precedence here too.
    if shell_key:
        existing = shell_key
        source = "shell environment"
        hint = (
            "Your shell has this variable exported (likely from your profile "
            "or a parent process). It will override any value in .env."
        )
    elif env_key:
        existing = env_key
        source = "the .env file in this workspace"
        hint = ""
    else:
        existing = None
        source = ""
        hint = ""

    if existing and not force:
        preview = _mask_key(existing)
        # Non-interactive or quickstart: still announce the source + preview.
        if non_interactive or quickstart:
            console.print(
                f"  [dim]reusing {info['key_env']} [cyan]{preview}[/] "
                f"from {source}[/]"
            )
            return existing

        console.print(f"  found {info['key_env']}  [cyan]{preview}[/]  [dim](from {source})[/]")
        if hint:
            console.print(f"  [dim]{hint}[/]")
        try:
            use_existing = _ask(
                questionary.confirm,
                "Use this key?",
                default=True,
            )
        except _Cancelled:
            raise
        if use_existing:
            console.print("  [green]reusing existing key.[/]")
            return existing
        # User said No. Warn them about shell-env precedence before taking a new key.
        if shell_key:
            console.print(
                "  [yellow]note:[/] your shell env has "
                f"[cyan]{info['key_env']}[/] exported. Any new key you paste "
                "will be written to [cyan].env[/], but the shell env will "
                "still take precedence until you unset it."
            )
            console.print(
                f"    to unset:  [cyan]unset {info['key_env']}[/]  "
                f"(bash/zsh)  or  [cyan]Remove-Item Env:{info['key_env']}[/]  (PowerShell)\n"
            )
        else:
            console.print("  [dim]ok — enter a new key.[/]\n")

    if non_interactive:
        console.print(f"[red]no {info['key_env']} provided (required for --non-interactive)[/]")
        raise typer.Exit(2)

    return _prompt_for_key_loop(info)


def _prompt_for_key_loop(info: dict) -> str | None:
    """Prompt with retries. Returns a key, or None if user chose 'skip for now'."""
    import questionary

    console.print(f"  [dim]get a key at[/] [cyan]{info['key_url']}[/]")

    retry_choices = [
        questionary.Choice("Try again (paste the key)", value="retry"),
        questionary.Choice("Skip for now — add it later in .env", value="skip"),
        questionary.Choice("Cancel setup", value="cancel"),
    ]

    for attempt in range(1, 4):
        try:
            raw = _ask(
                questionary.password,
                f"Paste your {info['key_env']} ({info['key_hint']}):",
            )
        except _Cancelled:
            raise
        key = (raw or "").strip().strip("'").strip('"')

        if key and key.startswith(info["key_prefix"]):
            return key  # happy path

        if not key:
            console.print("  [yellow]empty input.[/]")
            problem = "empty"
        else:
            console.print(
                f"  [yellow]that doesn't look like a {info['key_env']}[/] "
                f"(expected prefix [cyan]{info['key_prefix']}[/])."
            )
            try:
                keep = _ask(
                    questionary.confirm,
                    "Use this key anyway (maybe you have a custom key format)?",
                    default=False,
                )
            except _Cancelled:
                raise
            if keep:
                return key
            problem = "wrong prefix"

        if attempt == 3:
            console.print(f"[yellow]three attempts ({problem}) — skipping key entry.[/]")
            return None

        try:
            action = _ask(
                questionary.select,
                "What now?",
                choices=retry_choices,
                default="retry",
            )
        except _Cancelled:
            raise
        if action == "skip":
            return None
        if action == "cancel":
            raise _Cancelled()
        # action == "retry" → next loop iteration

    return None  # defensive; unreachable


def _print_next_steps(provider: str, *, has_key: bool) -> None:
    lines = [
        "[bold green]All set![/]",
        "",
        f"Provider: [cyan]{provider}[/]",
    ]
    if not has_key:
        lines.append(
            "[yellow]No API key saved yet.[/] "
            f"Add [cyan]{_PROVIDER_INFO[provider]['key_env']}=...[/] to [cyan].env[/] before running agent commands."
        )
    lines += [
        "",
        "Next steps:",
        "  1. Drop sources in [cyan]research/raw/[/] "
        "(URLs: add to [cyan]research/raw/urls.txt[/]).",
        "  2. Drop 3-5 of your prior writing samples in [cyan]style/samples/[/].",
        "  3. [cyan]uv run thesis ingest[/]  (normalise sources)",
        "  4. [cyan]uv run thesis style[/]   (learn your voice)",
        "  5. [cyan]uv run thesis curate[/]  (build the wiki)",
        "  6. [cyan]uv run thesis chat[/]    (write with the agent)",
    ]
    console.print(Panel.fit("\n".join(lines), title="Next", border_style="green"))


def _validate_key(provider: str, key: str, extras: dict | None = None) -> tuple[bool, str]:
    """1-token ping to prove the key works. Cheap."""
    extras = extras or {}
    if provider == "anthropic":
        try:
            from anthropic import Anthropic
        except Exception as e:
            return False, f"anthropic package missing: {e}"
        try:
            client = Anthropic(api_key=key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True, "ok"
        except Exception as e:
            return False, str(e)

    if provider == "openrouter":
        try:
            from openai import OpenAI  # comes in via langchain-openai
        except Exception as e:
            return False, f"openai package missing: {e}"
        headers: dict[str, str] = {}
        if site := extras.get("OPENROUTER_SITE_URL"):
            headers["HTTP-Referer"] = site
        if name := extras.get("OPENROUTER_SITE_NAME"):
            headers["X-Title"] = name
        try:
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
            client.chat.completions.create(
                model="anthropic/claude-haiku-4-5",
                max_tokens=1,
                extra_headers=headers or None,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True, "ok"
        except Exception as e:
            return False, str(e)

    return False, f"unknown provider: {provider}"


def _read_env_var(name: str) -> str | None:
    p = paths().env_file
    if not p.exists():
        return None
    prefix = f"{name}="
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip('"').strip("'")
    return None


def _write_env(updates: dict[str, str]) -> None:
    """Merge updates into .env, replacing existing keys; leave other lines alone."""
    p = paths().env_file
    lines: list[str] = []
    seen: set[str] = set()
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            stripped = ln.strip()
            matched = False
            for key in updates:
                if stripped.startswith(f"{key}="):
                    matched = True
                    break
            if not matched:
                lines.append(ln)
    # Prepend/refresh updates at the top
    head = [f"{k}={v}" for k, v in updates.items() if v]
    seen.update(updates.keys())
    out = head + [""] + lines if head else lines
    p.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# init / status
# ---------------------------------------------------------------------------

@app.command()
def init(force: bool = typer.Option(False, "--force", help="Overwrite AGENTS.md if present.")) -> None:
    """Create workspace folders without prompts (for scripted / CI use)."""
    _ensure_workspace(force=force)
    console.print(f"[green]workspace initialised at[/] {paths().root}")


@app.command()
def status() -> None:
    """Show what's in the workspace (no LLM calls)."""
    p = paths()
    tbl = Table(title="thesis-agent status", show_header=True, header_style="bold")
    tbl.add_column("thing")
    tbl.add_column("value")

    def _exists(path: Path) -> str:
        return "[green]yes[/]" if path.exists() else "[red]no[/]"

    tbl.add_row("workspace", str(p.root))
    tbl.add_row("AGENTS.md", _exists(p.agents_md))
    tbl.add_row(".env", _exists(p.env_file))
    tbl.add_row("style/STYLE.md", _exists(p.style_guide))
    tbl.add_row("thesis/outline.md", _exists(p.outline))

    raw_count = (
        sum(1 for f in p.raw.iterdir() if f.is_file() and not f.name.startswith("_"))
        if p.raw.exists() else 0
    )
    wiki_count = (
        sum(1 for f in p.wiki.iterdir() if f.is_file() and f.suffix == ".md")
        if p.wiki.exists() else 0
    )
    chap_count = (
        sum(1 for f in p.chapters.iterdir() if f.is_file() and f.suffix == ".md")
        if p.chapters.exists() else 0
    )
    sample_count = (
        sum(1 for f in p.style_samples.iterdir() if f.is_file() and f.suffix in {".md", ".txt"})
        if p.style_samples.exists() else 0
    )

    tbl.add_row("raw sources", str(raw_count))
    tbl.add_row("wiki pages", str(wiki_count))
    tbl.add_row("thesis chapters", str(chap_count))
    tbl.add_row("style samples", str(sample_count))

    cp = p.checkpoints_db
    st = p.store_db
    tbl.add_row("checkpoints.db", f"{cp.stat().st_size} B" if cp.exists() else "[dim]not yet[/]")
    tbl.add_row("store.db", f"{st.stat().st_size} B" if st.exists() else "[dim]not yet[/]")
    tbl.add_row("current thread", read_thread_id())

    console.print(tbl)


# ---------------------------------------------------------------------------
# ingest (pure Python)
# ---------------------------------------------------------------------------

@app.command()
def ingest(
    source_dir: Path | None = typer.Argument(None, help="Directory to ingest. Defaults to research/raw."),
) -> None:
    """Normalise source files to markdown + update _index.json. No LLM."""
    from thesis_agent.ingest.manifest import run_ingest

    p = paths()
    target = (source_dir or p.raw).resolve()
    if not target.exists():
        console.print(f"[red]no such directory:[/] {target}")
        raise typer.Exit(1)

    _ensure_workspace()
    result = run_ingest(target, p)
    console.print(
        f"[green]done[/] — added {result['added']}, updated {result['updated']}, "
        f"skipped {result['skipped']}, failed {len(result['failed'])}"
    )
    for ref, err in result["failed"]:
        console.print(f"  [red]\u2717[/] {ref}: {err}")
    if result["failed"]:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# agent-backed commands
# ---------------------------------------------------------------------------

def _run(prompt: str, thread_id: str) -> None:
    from thesis_agent.agent import invoke

    try:
        reply = invoke(prompt, thread_id=thread_id)
    except Exception as e:
        console.print(f"[red]agent error:[/] {e}")
        raise typer.Exit(1) from e
    console.print(reply)


@app.command()
def curate(
    thread: str = typer.Option(None, "--thread", help="Thread ID (defaults to persisted)."),
) -> None:
    """Delegate to the wiki-curator to build wiki pages from pending sources."""
    tid = thread or read_thread_id()
    write_thread_id(tid)
    _run(
        "Curate all pending sources per AGENTS.md. For each entry in "
        "`research/raw/_index.json` with status 'pending', delegate to the "
        "wiki-curator subagent, build the wiki page, update `index.md`, flag "
        "conflicts, then flip status to 'curated'.",
        tid,
    )


@app.command()
def style(
    thread: str = typer.Option(None, "--thread"),
) -> None:
    """Compile style/STYLE.md from samples in style/samples/."""
    tid = thread or read_thread_id()
    write_thread_id(tid)
    _run(
        "Invoke the style-learner skill. Read every file under `style/samples/` "
        "and produce/update `style/STYLE.md` as a prescriptive style guide.",
        tid,
    )


@app.command()
def write(
    section: str = typer.Argument(..., help="Section identifier from thesis/outline.md, e.g. '2.1'."),
    thread: str = typer.Option(None, "--thread"),
) -> None:
    """Draft one thesis section, grounded in the wiki, in your style."""
    tid = thread or read_thread_id()
    write_thread_id(tid)
    _run(
        f"Invoke the thesis-writer skill to draft section '{section}' from "
        f"`thesis/outline.md`. Follow `style/STYLE.md` and cite every factual "
        f"claim with `[src:<raw_filename>]`. Write to `thesis/chapters/`.",
        tid,
    )


@app.command()
def lint(
    file: Path | None = typer.Argument(None, help="Chapter file to lint. Defaults to all chapters."),
    thread: str = typer.Option(None, "--thread"),
) -> None:
    """Run the citation-linter over thesis chapters."""
    tid = thread or read_thread_id()
    write_thread_id(tid)
    target = str(file) if file else "`thesis/chapters/*.md`"
    _run(
        f"Invoke the citation-linter skill on {target}. Report dead citations "
        f"and ungrounded paragraphs. Do not auto-edit.",
        tid,
    )


@app.command()
def chat(
    thread: str = typer.Option(None, "--thread", help="Thread ID (defaults to persisted)."),
    new: bool = typer.Option(False, "--new", help="Start a fresh thread."),
) -> None:
    """Interactive REPL with the agent. Ctrl-D / Ctrl-C to quit."""
    from thesis_agent.agent import build_agent

    p = paths()
    if new:
        import time
        tid = f"t-{int(time.time())}"
    else:
        tid = thread or read_thread_id()
    write_thread_id(tid)

    console.print(
        Panel.fit(
            f"thread: [cyan]{tid}[/]    type [bold]/new[/] for a fresh thread, "
            f"[bold]/quit[/] to exit.",
            border_style="dim",
        )
    )

    with build_agent(p=p) as agent:
        while True:
            try:
                msg = console.input("[bold cyan]you >[/] ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]bye.[/]")
                break
            if not msg.strip():
                continue
            if msg.strip() in {"/quit", "/exit"}:
                break
            if msg.strip() == "/new":
                import time
                tid = f"t-{int(time.time())}"
                write_thread_id(tid)
                console.print(f"[dim]new thread: {tid}[/]")
                continue

            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": msg}]},
                    config={"configurable": {"thread_id": tid}},
                )
                msgs = result.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    content = getattr(last, "content", None) or last.get("content", "")
                    console.print(f"[bold green]agent >[/] {content}\n")
            except Exception as e:
                console.print(f"[red]agent error:[/] {e}")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    if version:
        console.print(f"thesis-agent {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
