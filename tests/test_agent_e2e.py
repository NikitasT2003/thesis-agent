"""End-to-end agent tests with a scripted LLM.

These drive the *real* deepagents graph — filesystem middleware, subagent
middleware, sandbox, skill loader — swapping only the chat model for a
fake that replays pre-canned `AIMessage`s. That way we validate the wiring
(tool calls land on disk, subagent delegation works, sandbox enforces) without
paying an LLM a cent.

What we're NOT testing here: whether the LLM makes sensible decisions. That
is a prompt-quality question that needs a real model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage


class ScriptedLLM(FakeMessagesListChatModel):
    """FakeMessagesListChatModel + a `bind_tools` that returns self.

    deepagents binds the tool schema to the model before running; the default
    fake model raises NotImplementedError on bind_tools. We just ignore the
    tools (they still get routed by the graph when our AIMessage contains
    `tool_calls`).
    """

    def bind_tools(self, tools, **kwargs):  # noqa: D401
        return self

    def with_structured_output(self, *a, **kw):  # defensive — some middleware asks
        return self


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id}


def ai(content: str = "", *calls: dict) -> AIMessage:
    return AIMessage(content=content, tool_calls=list(calls))


def final(content: str) -> AIMessage:
    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Workspace fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A minimal but realistic workspace."""
    monkeypatch.chdir(tmp_path)
    # Env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    for v in ("THESIS_PROVIDER", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)

    # Dirs
    (tmp_path / "research" / "raw").mkdir(parents=True)
    (tmp_path / "research" / "wiki").mkdir(parents=True)
    (tmp_path / "style" / "samples").mkdir(parents=True)
    (tmp_path / "thesis" / "chapters").mkdir(parents=True)
    (tmp_path / "data").mkdir()

    # AGENTS.md (tiny placeholder is enough — we don't care about the
    # real content, only that the agent doesn't need network access)
    (tmp_path / "AGENTS.md").write_text("# schema placeholder\n", encoding="utf-8")

    # Outline
    (tmp_path / "thesis" / "outline.md").write_text(
        "# Thesis outline\n## 1. Introduction\n## 2. Background\n",
        encoding="utf-8",
    )
    return tmp_path


def _build_agent_with_scripted_llm(
    workspace: Path, responses: list[AIMessage], *, system_prompt: str | None = None
):
    """Create a real deepagents agent wired to the scripted LLM + disk."""
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    kwargs: dict[str, Any] = {
        "model": ScriptedLLM(responses=responses),
        "tools": [],
        "backend": FilesystemBackend(root_dir=str(workspace), virtual_mode=True),
    }
    if system_prompt is not None:
        kwargs["system_prompt"] = system_prompt

    return create_deep_agent(**kwargs)


def _invoke(agent, user_msg: str) -> dict:
    return agent.invoke({"messages": [{"role": "user", "content": user_msg}]})


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

class TestWritePathIsRealDisk:
    def test_write_file_persists_under_root(self, workspace: Path):
        """Baseline: a single write_file tool call lands on disk under
        root_dir via virtual path."""
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/note.md",
                    "content": "# hello\n",
                }, "w1")),
                final("done"),
            ],
        )
        _invoke(agent, "write a note")
        assert (workspace / "research" / "wiki" / "note.md").read_text(encoding="utf-8") == "# hello\n"

    def test_read_then_write(self, workspace: Path):
        """Agent reads an existing file then writes a new one based on it."""
        (workspace / "research" / "raw" / "source.md").write_text(
            "Body of the source.\n", encoding="utf-8"
        )
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("read_file", {
                    "file_path": "/research/raw/source.md",
                }, "r1")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/source.md",
                    "content": "# summary\n[src:source.md]\n",
                }, "w1")),
                final("curated"),
            ],
        )
        _invoke(agent, "curate it")
        out = workspace / "research" / "wiki" / "source.md"
        assert out.exists()
        assert "[src:source.md]" in out.read_text(encoding="utf-8")


class TestCurateUpdatesManifest:
    def test_manifest_status_flips_to_curated(self, workspace: Path):
        """Simulates the wiki-curator flow: read raw, write wiki page,
        edit _index.json to flip status. write_file refuses to overwrite
        existing files, so in-place manifest updates MUST use edit_file —
        this test locks that convention in."""
        raw_dir = workspace / "research" / "raw"
        (raw_dir / "paper.md").write_text("content\n", encoding="utf-8")
        manifest = {
            "version": 1,
            "entries": {
                "paper.md": {
                    "filename": "paper.md", "orig": "paper.md",
                    "orig_ext": ".md", "sha256": "abc", "bytes": 8, "words": 1,
                    "status": "pending", "ingested_at": "2026-04-20",
                    "curated_pages": [],
                },
            },
        }
        (raw_dir / "_index.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("read_file", {"file_path": "/research/raw/paper.md"}, "r1")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/paper.md",
                    "content": "# paper\n\n## Key claims\n- Claim. [src:paper.md]\n",
                }, "w1")),
                ai("", tool_call("read_file", {"file_path": "/research/raw/_index.json"}, "r2")),
                # Flip status via edit_file.
                ai("", tool_call("edit_file", {
                    "file_path": "/research/raw/_index.json",
                    "old_string": '"status": "pending"',
                    "new_string": '"status": "curated"',
                }, "e1")),
                # Add curated_pages via another edit.
                ai("", tool_call("edit_file", {
                    "file_path": "/research/raw/_index.json",
                    "old_string": '"curated_pages": []',
                    "new_string": '"curated_pages": ["paper.md"]',
                }, "e2")),
                final("curated 1 source"),
            ],
        )
        _invoke(agent, "curate pending")

        wiki_page = workspace / "research" / "wiki" / "paper.md"
        assert wiki_page.exists()
        assert "[src:paper.md]" in wiki_page.read_text(encoding="utf-8")
        updated = json.loads((workspace / "research" / "raw" / "_index.json").read_text(encoding="utf-8"))
        assert updated["entries"]["paper.md"]["status"] == "curated"
        assert updated["entries"]["paper.md"]["curated_pages"] == ["paper.md"]


class TestStyleLearnerE2E:
    def test_reads_samples_and_writes_style_md(self, workspace: Path):
        (workspace / "style" / "samples" / "a.md").write_text(
            "Short sentences. Specific verbs. No hedging.\n",
            encoding="utf-8",
        )
        style_md = (
            "# Writing Style Guide\n\n## Voice\nDirect, concrete.\n\n"
            "## Sentence rhythm\nAverage 16 words.\n"
        )
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("ls", {"path": "/style/samples"}, "l1")),
                ai("", tool_call("read_file", {"file_path": "/style/samples/a.md"}, "r1")),
                ai("", tool_call("write_file", {
                    "file_path": "/style/STYLE.md",
                    "content": style_md,
                }, "w1")),
                final("STYLE.md written"),
            ],
        )
        _invoke(agent, "learn my style")
        written = (workspace / "style" / "STYLE.md").read_text(encoding="utf-8")
        assert "Writing Style Guide" in written
        assert "Sentence rhythm" in written


class TestDrafterE2E:
    def test_drafts_chapter_with_citation(self, workspace: Path):
        (workspace / "research" / "wiki" / "source.md").write_text(
            "# source\n- Claim A. [src:source.md]\n",
            encoding="utf-8",
        )
        (workspace / "style" / "STYLE.md").write_text(
            "# Style\nDirect.\n",
            encoding="utf-8",
        )
        chapter = (
            "# 2.1 Background\n\n"
            "The first move is framing a question.\n"
            "Claim A holds across sources [src:source.md].\n"
        )
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("read_file", {"file_path": "/style/STYLE.md"}, "r1")),
                ai("", tool_call("read_file", {"file_path": "/research/wiki/source.md"}, "r2")),
                ai("", tool_call("write_file", {
                    "file_path": "/thesis/chapters/02.md",
                    "content": chapter,
                }, "w1")),
                final("wrote chapter 2"),
            ],
        )
        _invoke(agent, "draft 2.1")
        out = workspace / "thesis" / "chapters" / "02.md"
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "[src:source.md]" in text
        assert "2.1 Background" in text


# ---------------------------------------------------------------------------
# Error + safety paths
# ---------------------------------------------------------------------------

class TestAgentGracefulOnToolError:
    def test_read_missing_file_then_recover(self, workspace: Path):
        """Tool errors are observable; agent should not crash."""
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("read_file", {
                    "file_path": "/research/wiki/does-not-exist.md",
                }, "r1")),
                # After seeing the error message, write a fallback.
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/index.md",
                    "content": "# index\nempty wiki.\n",
                }, "w1")),
                final("recovered"),
            ],
        )
        res = _invoke(agent, "go")
        # The agent run must finish normally
        assert res["messages"][-1].content == "recovered"
        # And the fallback write landed
        assert (workspace / "research" / "wiki" / "index.md").exists()
        # Inspect that a ToolMessage carrying the error is in the transcript
        from langchain_core.messages import ToolMessage
        tool_msgs = [m for m in res["messages"] if isinstance(m, ToolMessage)]
        assert any("not found" in (m.content or "").lower() for m in tool_msgs)


class TestDeterministicOutput:
    def test_agent_returns_final_scripted_message(self, workspace: Path):
        """Smoke: without any tool calls, the scripted final message is
        exactly what the caller sees back."""
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[final("hello back")],
        )
        res = _invoke(agent, "hi")
        assert res["messages"][-1].content == "hello back"


class TestLLMWikiPatternIngest:
    """The Karpathy LLM Wiki pattern requires a single ingest to touch
    many pages — source summary + entity pages + concept pages + index +
    log. These tests lock in that structure at the file-system layer."""

    def test_multi_page_ingest_produces_all_categories(self, workspace: Path):
        # Seed workspace with the expected wiki subdirs + index + log +
        # a raw source + a pending manifest.
        for sub in ("sources", "entities", "concepts", "queries"):
            (workspace / "research" / "wiki" / sub).mkdir(parents=True, exist_ok=True)
        (workspace / "research" / "wiki" / "index.md").write_text(
            "# Wiki Index\n\n## Concepts\n\n## Entities\n\n## Sources\n\n## Queries\n",
            encoding="utf-8",
        )
        (workspace / "research" / "wiki" / "log.md").write_text(
            "# Wiki Log\n\n", encoding="utf-8",
        )
        raw_file = workspace / "research" / "raw" / "transformer.md"
        raw_file.write_text(
            "# Attention Is All You Need\nVaswani et al. introduce the Transformer.\n",
            encoding="utf-8",
        )
        manifest = {
            "version": 1,
            "entries": {
                "transformer.md": {
                    "filename": "transformer.md", "orig": "transformer.md",
                    "orig_ext": ".md", "sha256": "aaa", "bytes": 60, "words": 10,
                    "status": "pending", "ingested_at": "2026-04-20",
                    "curated_pages": [],
                },
            },
        }
        (workspace / "research" / "raw" / "_index.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8",
        )

        # Script the canonical multi-page ingest: read raw, write source
        # summary, create two entity pages, create one concept page,
        # update index.md, append log.md, flip manifest status.
        source_page = (
            "---\ntitle: Attention Is All You Need\n"
            "type: source\ntags: [transformer, attention]\n"
            "source: transformer.md\ncreated: 2026-04-20\nupdated: 2026-04-20\n---\n\n"
            "# Attention Is All You Need\n\n"
            "## Summary\nIntroduces the Transformer. [src:transformer.md]\n\n"
            "## Key claims\n- Transformer uses self-attention. [src:transformer.md]\n"
            "- No recurrence required. [src:transformer.md]\n\n"
            "## See also\n- [[entities/transformer]] — the architecture\n"
            "- [[entities/self-attention]] — the mechanism\n\n"
            "## Conflicts\n"
        )
        entity_transformer = (
            "---\ntitle: Transformer\ntype: entity\ntags: [architecture]\n"
            "sources: [transformer.md]\ncreated: 2026-04-20\nupdated: 2026-04-20\n---\n\n"
            "# Transformer\n\n## Summary\nAttention-based architecture. "
            "[src:transformer.md]\n\n## Key claims\n"
            "- Uses self-attention layers. [src:transformer.md]\n\n"
            "## See also\n- [[sources/transformer.md]]\n- [[entities/self-attention]]\n"
            "- [[concepts/attention-mechanisms]]\n\n## Conflicts\n"
        )
        entity_selfattn = (
            "---\ntitle: Self-Attention\ntype: entity\ntags: [mechanism]\n"
            "sources: [transformer.md]\ncreated: 2026-04-20\nupdated: 2026-04-20\n---\n\n"
            "# Self-Attention\n\n## Summary\nAllows every token to attend to every "
            "other token. [src:transformer.md]\n\n## Key claims\n"
            "- Scales as O(n^2) in sequence length. [src:transformer.md]\n\n"
            "## See also\n- [[sources/transformer.md]]\n- [[entities/transformer]]\n\n"
            "## Conflicts\n"
        )
        concept_attention = (
            "---\ntitle: Attention Mechanisms\ntype: concept\n"
            "tags: [nn, sequence-modelling]\nsources: [transformer.md]\n"
            "created: 2026-04-20\nupdated: 2026-04-20\n---\n\n"
            "# Attention Mechanisms\n\n## Summary\nLet a model focus on relevant "
            "parts of the input. [src:transformer.md]\n\n## Key claims\n"
            "- Replaces recurrence in sequence modelling. [src:transformer.md]\n\n"
            "## See also\n- [[entities/transformer]]\n- [[entities/self-attention]]\n\n"
            "## Conflicts\n"
        )

        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("read_file", {"file_path": "/research/raw/transformer.md"}, "r1")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/sources/transformer.md",
                    "content": source_page,
                }, "w_src")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/entities/transformer.md",
                    "content": entity_transformer,
                }, "w_e1")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/entities/self-attention.md",
                    "content": entity_selfattn,
                }, "w_e2")),
                ai("", tool_call("write_file", {
                    "file_path": "/research/wiki/concepts/attention-mechanisms.md",
                    "content": concept_attention,
                }, "w_c1")),
                # Update index.md via edit_file (add a bullet under each
                # section). One simple edit per section to keep the script
                # compact.
                ai("", tool_call("edit_file", {
                    "file_path": "/research/wiki/index.md",
                    "old_string": "## Sources\n",
                    "new_string": "## Sources\n- [[sources/transformer.md]] — intro to the Transformer\n",
                }, "e_idx")),
                # Append a log entry
                ai("", tool_call("edit_file", {
                    "file_path": "/research/wiki/log.md",
                    "old_string": "# Wiki Log\n\n",
                    "new_string": (
                        "# Wiki Log\n\n"
                        "## [2026-04-20] ingest | Attention Is All You Need\n"
                        "- New pages: [[sources/transformer.md]], "
                        "[[entities/transformer]], [[entities/self-attention]], "
                        "[[concepts/attention-mechanisms]]\n"
                        "- Conflicts flagged: 0\n\n"
                    ),
                }, "e_log")),
                # Flip manifest status
                ai("", tool_call("edit_file", {
                    "file_path": "/research/raw/_index.json",
                    "old_string": '"status": "pending"',
                    "new_string": '"status": "curated"',
                }, "e_mf")),
                final("curated 1 source, touched 7 pages"),
            ],
        )
        _invoke(agent, "curate pending")

        # Verify every category produced something
        assert (workspace / "research" / "wiki" / "sources" / "transformer.md").exists()
        assert (workspace / "research" / "wiki" / "entities" / "transformer.md").exists()
        assert (workspace / "research" / "wiki" / "entities" / "self-attention.md").exists()
        assert (workspace / "research" / "wiki" / "concepts" / "attention-mechanisms.md").exists()

        # index.md updated
        idx = (workspace / "research" / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "[[sources/transformer.md]]" in idx

        # log.md has the grep-friendly prefix
        log = (workspace / "research" / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "## [2026-04-20] ingest | Attention Is All You Need" in log

        # Manifest flipped
        updated = json.loads((workspace / "research" / "raw" / "_index.json").read_text(encoding="utf-8"))
        assert updated["entries"]["transformer.md"]["status"] == "curated"

        # All four page categories have at least one page
        for sub, required_count in (("sources", 1), ("entities", 2), ("concepts", 1)):
            pages = list((workspace / "research" / "wiki" / sub).glob("*.md"))
            assert len(pages) >= required_count, (
                f"expected >={required_count} page(s) under {sub}/, got {len(pages)}"
            )


class TestWorkspaceSeedsWikiScaffold:
    """The `init` / setup workflow must pre-create the wiki categories +
    index.md + log.md so the agent knows where to write on first curate."""

    def test_init_creates_full_wiki_layout(self, workspace: Path, monkeypatch):
        # Fresh workspace (clobber what our fixture put in place)
        import shutil

        from thesis_agent import cli
        shutil.rmtree(workspace / "research", ignore_errors=True)
        shutil.rmtree(workspace / "thesis", ignore_errors=True)
        monkeypatch.chdir(workspace)

        cli._ensure_workspace()

        # Every category dir exists
        for sub in ("sources", "entities", "concepts", "queries"):
            assert (workspace / "research" / "wiki" / sub).is_dir(), sub
        # index.md + log.md seeded
        idx = (workspace / "research" / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "Concepts" in idx and "Entities" in idx and "Sources" in idx and "Queries" in idx
        log = (workspace / "research" / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "Wiki Log" in log
        # The log explains the grep-friendly prefix convention
        assert "YYYY-MM-DD" in log


class TestSandboxViaFilesystemBackend:
    """The FilesystemBackend enforces a root boundary. These tests confirm
    the agent cannot escape it even when the scripted LLM explicitly tries."""

    def test_parent_traversal_blocked(self, workspace: Path):
        # Try to write above root via '..'
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("write_file", {
                    "file_path": "/../evil.md",
                    "content": "pwned",
                }, "w1")),
                final("handled"),
            ],
        )
        res = _invoke(agent, "attack")
        # Nothing outside workspace got created
        assert not (workspace.parent / "evil.md").exists()
        # The tool returned an error the agent could observe
        from langchain_core.messages import ToolMessage
        tool_msgs = [m for m in res["messages"] if isinstance(m, ToolMessage)]
        assert any(
            "traversal" in (m.content or "").lower() or "error" in (m.content or "").lower()
            for m in tool_msgs
        )

    def test_absolute_windows_path_blocked(self, workspace: Path):
        agent = _build_agent_with_scripted_llm(
            workspace,
            responses=[
                ai("", tool_call("write_file", {
                    "file_path": "C:\\Windows\\System32\\evil.txt",
                    "content": "pwned",
                }, "w1")),
                final("handled"),
            ],
        )
        res = _invoke(agent, "attack")
        from langchain_core.messages import ToolMessage
        tool_msgs = [m for m in res["messages"] if isinstance(m, ToolMessage)]
        # Virtual-mode converts to /C:\Windows... and catches it. Any reject is fine.
        assert any("error" in (m.content or "").lower() for m in tool_msgs)


class TestRecursionLimitStopsRunaway:
    def test_recursion_limit_terminates_loop(self, workspace: Path):
        """A malicious / buggy LLM that never stops tool-calling must be
        bounded by the recursion_limit."""
        # Script many repeated tool calls — agent would loop forever otherwise.
        many_calls = [
            ai("", tool_call("ls", {"path": "/"}, f"c{i}"))
            for i in range(50)
        ] + [final("exhausted")]

        from deepagents import create_deep_agent
        from deepagents.backends import FilesystemBackend

        agent = create_deep_agent(
            model=ScriptedLLM(responses=many_calls),
            tools=[],
            backend=FilesystemBackend(root_dir=str(workspace), virtual_mode=True),
        )
        # LangGraph raises GraphRecursionError when limit hit.
        with pytest.raises(Exception) as excinfo:
            agent.invoke(
                {"messages": [{"role": "user", "content": "go"}]},
                config={"recursion_limit": 5},
            )
        assert "recursion" in str(excinfo.value).lower() or "limit" in str(excinfo.value).lower()


class TestBuildAgentWiringUsesScriptedLLM:
    """Proves our production `build_agent` accepts a scripted model when
    `make_model` is patched — i.e. our wiring doesn't leak provider-specific
    expectations into the graph."""

    def test_build_agent_with_make_model_patched(
        self, workspace: Path, monkeypatch
    ):
        # Skills must live inside the workspace root because FilesystemBackend
        # refuses paths outside root_dir. The production `_find_skills_dir`
        # falls back to the bundled repo skills/, which is outside the temp
        # workspace — point it at an empty in-workspace skills dir instead.
        (workspace / "skills").mkdir()

        from thesis_agent import agent as agent_mod
        from thesis_agent import subagents as sub_mod

        call_log: list[str] = []

        def fake_make_model(model_id, *, role=None, **kw):
            call_log.append(f"{role or 'main'}:{model_id}")
            return ScriptedLLM(responses=[final("fine")])

        monkeypatch.setattr(agent_mod, "make_model", fake_make_model)
        monkeypatch.setattr(sub_mod, "make_model", fake_make_model)

        with agent_mod.build_agent() as a:
            res = a.invoke(
                {"messages": [{"role": "user", "content": "ping"}]},
                config={"configurable": {"thread_id": "t", "recursion_limit": 5}},
            )
        assert res["messages"][-1].content == "fine"
        # build_agent instantiates 1 main + 3 subagents = 4 model calls.
        assert len(call_log) == 4
        # Each subagent tagged with its role.
        roles = {entry.split(":", 1)[0] for entry in call_log}
        assert {"curator", "drafter", "researcher"}.issubset(roles)
