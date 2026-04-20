"""Subagents loader — turns `subagents.yaml` into a list of deepagents
SubAgent dicts.

Uses the same pattern as the canonical deepagents content-builder
example: keep subagent config as YAML in the project folder so the user
(or the agent itself) can edit it without touching Python. The helper
resolves the `model` role tag to the actual model instance via
`thesis_agent.config.make_model`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from thesis_agent.config import ModelConfig, make_model


def load_subagents(path: str | Path, models: ModelConfig) -> list[dict[str, Any]]:
    """Parse `subagents.yaml` and return the list deepagents expects.

    Each YAML entry must have:
      * name           — unique identifier used by the `task` tool
      * description    — when to delegate (read by the orchestrator)
      * system_prompt  — the subagent's identity + scope
      * model          — a role tag: "drafter" / "curator" / "researcher".
                         Resolved to an actual model instance here.

    Unknown role tags fall through to the drafter model.
    """
    p = Path(path)
    if not p.exists():
        return []

    entries = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    if not isinstance(entries, list):
        raise ValueError(
            f"{path}: expected a YAML list of subagent entries, got "
            f"{type(entries).__name__}"
        )

    resolved: list[dict[str, Any]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("model", "drafter"))
        model_id = {
            "drafter": models.drafter,
            "curator": models.curator,
            "researcher": models.researcher,
        }.get(role, models.drafter)
        resolved.append({
            "name": raw["name"],
            "description": raw["description"],
            "system_prompt": raw["system_prompt"],
            "model": make_model(model_id, role=role if role in {"drafter", "curator", "researcher"} else None),
        })
    return resolved
