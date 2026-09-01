"""テスト用のダミー実装。

外部サービスを呼ばずにControl Loopを1周させるために使う。
"""

from __future__ import annotations

from datetime import datetime, timezone

from aion.core.models import Decision, Observation, Result, Work


class StubSource:
    """毎回同じObservationを返す観測源。重複排除の検証も兼ねる。"""

    def __init__(self, observations: list[Observation]) -> None:
        self.name = "stub"
        self._observations = observations
        self.polls = 0

    def poll(self) -> list[Observation]:
        self.polls += 1
        return list(self._observations)


class WorldStateAwareDecisionEngine:
    """未調査の観測があれば create_work、無ければ no_action。

    LLMを呼ばずに「再評価がno_actionへ収束するか」を検証するための実装。
    収束の責任はreconciliationにあり、この判定はその契約を写している。
    """

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, observations, world_state) -> Decision:
        self.calls += 1
        pending = [
            s
            for s in world_state
            if s.key.startswith("observation:") and not s.value.get("investigated")
        ]
        if not pending:
            return Decision(action="no_action", reason="everything observed has been investigated")
        return Decision(
            action="create_work",
            reason="an unexamined observation may have downstream impact",
            objective="Investigate the likely impact and summarize findings.",
            priority=0.8,
        )


class StubAgent:
    """既存Agent Runtimeの代役。"""

    def __init__(self, output: str = "Findings: energy and shipping exposure.") -> None:
        self.output = output
        self.executed: list[Work] = []

    def execute(self, work: Work) -> Result:
        self.executed.append(work)
        return Result(work_id=work.id, success=True, output=self.output)


class FailingAgent:
    def execute(self, work: Work) -> Result:
        return Result(work_id=work.id, success=False, output="boom")


def make_observation(obs_id: str = "obs-1", content: str = "Major geopolitical event in region X.") -> Observation:
    return Observation(
        id=obs_id,
        source="stub",
        observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        content=content,
        metadata={"title": "Major geopolitical event"},
    )
