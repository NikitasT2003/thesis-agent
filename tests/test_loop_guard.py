"""Infinite-loop guard for the agent.

Previously `thesis curate` and `thesis style` could get stuck making the
same tool call over and over (e.g. a weak model retrying a refused
`write_file` instead of switching to `edit_file`). `recursion_limit=25`
didn't catch it fast enough and the turn would either time out or churn
through the budget before the user's Ctrl-C. These tests lock in:

1. A client-side loop detector in `agent.invoke` that raises
   `ToolCallLoopError` when the same (tool_name, args) appears 3 times
   in the last 10 tool calls.
2. The default recursion_limit raised from 25 → 60, large enough for
   a real multi-page curate pass.
3. The curate/style prompts no longer contain the aggressive
   "redo it" / "you missed the point" language that tells weak models
   to retry the whole operation.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from thesis_agent import agent as agent_mod
from thesis_agent.agent import (
    _DEFAULT_RECURSION_LIMIT,
    ToolCallLoopError,
    _recursion_limit,
    _scan_for_loop,
    _tool_call_signature,
)

# ---------------------------------------------------------------------------
# Loop-detection helpers
# ---------------------------------------------------------------------------

class TestSignature:
    def test_signature_key_order_invariant(self):
        a = {"name": "write_file", "args": {"b": 2, "a": 1}}
        b = {"name": "write_file", "args": {"a": 1, "b": 2}}
        assert _tool_call_signature(a) == _tool_call_signature(b)

    def test_different_args_produce_different_signatures(self):
        a = {"name": "write_file", "args": {"file_path": "/x"}}
        b = {"name": "write_file", "args": {"file_path": "/y"}}
        assert _tool_call_signature(a) != _tool_call_signature(b)

    def test_handles_non_json_args(self):
        # Exotic args shouldn't crash.
        sig = _tool_call_signature({"name": "x", "args": {"obj": object()}})
        assert sig.startswith("x::")


class TestScanForLoop:
    def test_three_in_a_row_flags(self):
        sigs = ["a::{}", "a::{}", "a::{}"]
        assert _scan_for_loop(sigs) == "a::{}"

    def test_two_occurrences_do_not_flag(self):
        assert _scan_for_loop(["a::{}", "a::{}", "b::{}"]) is None

    def test_flags_even_when_interleaved(self):
        sigs = ["a", "b", "a", "c", "a"]  # a appears 3x in last 5
        assert _scan_for_loop(sigs, window=5, threshold=3) == "a"

    def test_respects_window(self):
        # 'a' appeared 3x, but only near the start — everything since has
        # been distinct. Sliding window of 10 ends on the distinct tail,
        # so no repeat detected. (Loops happen NOW; old history is fine.)
        sigs = ["a", "a", "a"] + [f"x{i}" for i in range(20)]
        assert _scan_for_loop(sigs, window=10, threshold=3) is None


# ---------------------------------------------------------------------------
# recursion_limit defaults
# ---------------------------------------------------------------------------

class TestRecursionLimit:
    def test_default_is_large_enough_for_multi_page_ingest(self, monkeypatch):
        """A real curate pass on one substantive source touches 10-15
        pages, each of which is at least one tool call. Default must
        comfortably cover that."""
        monkeypatch.delenv("THESIS_RECURSION_LIMIT", raising=False)
        assert _recursion_limit() == _DEFAULT_RECURSION_LIMIT
        assert _DEFAULT_RECURSION_LIMIT >= 50, (
            "default too low for multi-page ingest; weak models will hit "
            "the ceiling before finishing a curate pass"
        )


# ---------------------------------------------------------------------------
# invoke() integration: loop detector triggers
# ---------------------------------------------------------------------------

class _LoopingAgent:
    """Stub that yields the same tool call on every stream step —
    simulates a model stuck in a loop."""

    def __init__(self):
        self.calls = 0

    def stream(self, payload, *, config=None, stream_mode=None):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        human = HumanMessage(content=payload["messages"][-1]["content"])
        state = [human]
        yield {"messages": list(state)}

        # Yield 5 identical tool calls. The detector should bail after 3.
        for i in range(5):
            self.calls += 1
            state.append(AIMessage(
                content="",
                tool_calls=[{
                    "name": "write_file",
                    "args": {"file_path": "/already-exists.md", "content": "x"},
                    "id": f"c{i}",
                    "type": "tool_call",
                }],
            ))
            yield {"messages": list(state)}
            state.append(ToolMessage(
                content="Cannot write: already exists",
                tool_call_id=f"c{i}",
            ))
            yield {"messages": list(state)}

        state.append(AIMessage(content="give up"))
        yield {"messages": list(state)}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    monkeypatch.delenv("THESIS_RECURSION_LIMIT", raising=False)
    return tmp_path


def test_invoke_raises_on_repeated_tool_call(workspace: Path, monkeypatch):
    agent = _LoopingAgent()

    @contextmanager
    def fake_build_agent(**kw):
        yield agent

    monkeypatch.setattr(agent_mod, "build_agent", fake_build_agent)

    with pytest.raises(ToolCallLoopError) as exc_info:
        agent_mod.invoke("curate", thread_id="t-test")

    # The error names the offending call so the user can read it.
    err = str(exc_info.value)
    assert "write_file" in err
    assert "/already-exists.md" in err
    # Agent was aborted BEFORE the 5th repetition: we want to stop the bleed fast.
    assert agent.calls <= 3


def test_invoke_does_not_raise_on_distinct_calls(workspace: Path, monkeypatch):
    """Sanity: a normal agent making different tool calls each step
    must NOT trigger the loop detector."""
    class _Normal:
        def stream(self, payload, *, config=None, stream_mode=None):
            from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

            human = HumanMessage(content=payload["messages"][-1]["content"])
            state = [human]
            yield {"messages": list(state)}
            for i, fname in enumerate(("a.md", "b.md", "c.md")):
                state.append(AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "write_file",
                        "args": {"file_path": f"/{fname}", "content": "x"},
                        "id": f"c{i}",
                        "type": "tool_call",
                    }],
                ))
                yield {"messages": list(state)}
                state.append(ToolMessage(content="Updated", tool_call_id=f"c{i}"))
                yield {"messages": list(state)}
            state.append(AIMessage(content="done"))
            yield {"messages": list(state)}

    @contextmanager
    def fake_build_agent(**kw):
        yield _Normal()

    monkeypatch.setattr(agent_mod, "build_agent", fake_build_agent)
    result = agent_mod.invoke("go", thread_id="t-ok")
    assert result == "done"


# ---------------------------------------------------------------------------
# Prompt regressions: language that invites weak models to loop is gone
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestNoRetryLanguageInPrompts:
    """The old aggressive 'redo it / missed the point' framing in the
    curate prompt + wiki-curator skill + AGENTS.md told weak models to
    restart if they didn't hit an arbitrary page-count threshold. That
    was the primary cause of the observed infinite-loop bug. These tests
    lock in the softer language."""

    def test_no_redo_it_anywhere(self):
        for rel in (
            "src/thesis_agent/cli.py",
            "skills/wiki-curator/SKILL.md",
            "AGENTS.md",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8").lower()
            assert "redo it" not in text, f"'redo it' still in {rel}"

    def test_no_missed_the_point_anywhere(self):
        for rel in (
            "src/thesis_agent/cli.py",
            "skills/wiki-curator/SKILL.md",
            "AGENTS.md",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8").lower()
            assert "missed the point" not in text, f"'missed the point' still in {rel}"

    def test_wiki_curator_skill_uses_softer_guidance(self):
        skill = (REPO_ROOT / "skills" / "wiki-curator" / "SKILL.md").read_text(encoding="utf-8")
        # Soft guidance words should appear (any of them)
        soft = any(word in skill.lower() for word in ("target", "aim", "goal", "report honestly"))
        assert soft, "wiki-curator skill lost its soft-guidance language"
