"""LLM Decision。ObservationとWorld Stateを見て no_action / create_work を決める。"""

from __future__ import annotations

import json
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from aion.core.models import Decision, Observation, WorldState

_SYSTEM_PROMPT = """\
You are the decision layer of an autonomous observation system called AION.

You are given newly observed events and the system's current world state.
Decide exactly one of:

- "no_action": nothing here changes what the system should be doing. This is the
  correct answer most of the time, and it is the correct answer whenever the
  world state already contains an investigation of this event.
- "create_work": this observation plausibly has downstream consequences that are
  worth investigating, and the world state does not already cover it. Give a
  single, self-contained objective a research worker can act on unattended.

Prefer no_action. Creating redundant work is worse than missing a marginal event.
"""


class _DecisionOutput(BaseModel):
    """LLMに守らせるスキーマ（Structured Outputs）。"""

    action: Literal["no_action", "create_work"]
    reason: str = Field(description="One sentence explaining the decision.")
    objective: str | None = Field(
        default=None,
        description="Required when action is create_work; null otherwise.",
    )
    priority: float = Field(default=0.0, ge=0.0, le=1.0)


class DecisionEngine(Protocol):
    def evaluate(
        self, observations: list[Observation], world_state: list[WorldState]
    ) -> Decision:
        ...


def render_context(observations: list[Observation], world_state: list[WorldState]) -> str:
    """LLMに渡す入力を組み立てる。ここ以外にプロンプトを散らかさない。"""

    obs_lines = [
        f"- [{o.source}] {o.observed_at.isoformat()}\n  {o.content}" for o in observations
    ] or ["(none)"]
    state_lines = [
        f"- {s.key} (updated {s.updated_at.isoformat()}):\n  "
        + json.dumps(s.value, ensure_ascii=False)
        for s in world_state
    ] or ["(empty)"]
    return (
        "# New observations\n"
        + "\n".join(obs_lines)
        + "\n\n# Current world state\n"
        + "\n".join(state_lines)
    )


class ClaudeDecisionEngine:
    """Anthropic Messages API + Structured Outputs。

    出力形式の検証はAPI側に任せる。パーサを自作しない。
    """

    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic  # 遅延import

            self._client = anthropic.Anthropic()
        return self._client

    def evaluate(
        self, observations: list[Observation], world_state: list[WorldState]
    ) -> Decision:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": render_context(observations, world_state)}],
            output_format=_DecisionOutput,
        )
        return _to_decision(response.parsed_output)


def _to_decision(parsed: _DecisionOutput) -> Decision:
    # objectiveの無いcreate_workは実行できないので no_action に倒す。
    if parsed.action == "create_work" and not (parsed.objective or "").strip():
        return Decision(
            action="no_action",
            reason=f"create_work without an objective; treated as no_action ({parsed.reason})",
        )
    return Decision(
        action=parsed.action,
        reason=parsed.reason,
        objective=parsed.objective,
        priority=parsed.priority,
    )
