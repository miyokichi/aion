"""AIONのControl Loop。AIONが所有しているのはこれだけ。

Observe → Reconcile → Decide → Work → Act → Reconcile → 再評価
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from aion.adapters.agent import AgentExecutor
from aion.adapters.observation import ObservationSource
from aion.core.decision import DecisionEngine, render_context
from aion.core.models import Decision, Observation, Result, Work
from aion.core.reconciliation import reconcile_observations, reconcile_result
from aion.storage.sqlite import Store

log = logging.getLogger("aion")


@dataclass
class CycleReport:
    """1周で何が起きたか。テストと運用の両方がこれを読む。"""

    observations: list[Observation] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    works: list[Work] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)

    @property
    def final_decision(self) -> Decision | None:
        return self.decisions[-1] if self.decisions else None

    @property
    def settled(self) -> bool:
        """再評価がno_actionに落ち着いたか。"""
        return self.final_decision is not None and self.final_decision.action == "no_action"


class ControlLoop:
    def __init__(
        self,
        source: ObservationSource,
        decision_engine: DecisionEngine,
        agent: AgentExecutor,
        store: Store,
        max_works_per_cycle: int = 1,
    ) -> None:
        self.source = source
        self.decision_engine = decision_engine
        self.agent = agent
        self.store = store
        self.max_works_per_cycle = max_works_per_cycle

    def run_once(self) -> CycleReport:
        report = CycleReport()

        observations = self.store.save_observations(self.source.poll())
        if not observations:
            log.info("no new observations")
            return report
        report.observations = observations
        log.info("observed %d new item(s)", len(observations))

        reconcile_observations(self.store, observations)
        observation_ids = [o.id for o in observations]

        while True:
            decision = self.decision_engine.evaluate(observations, self.store.all_world_state())
            report.decisions.append(decision)
            log.info("decision=%s reason=%s", decision.action, decision.reason)

            if decision.action == "no_action":
                return report
            if len(report.works) >= self.max_works_per_cycle:
                log.info("work budget for this cycle is spent; stopping here")
                return report

            work = self._create_work(decision, observations)
            report.works.append(work)

            result = self._execute(work)
            report.results.append(result)

            reconcile_result(self.store, work, result, observation_ids)
            # ループ先頭へ戻る = 再評価

    def run_forever(self, interval: float = 300.0) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("cycle failed; continuing")
            time.sleep(interval)

    # --- internals ----------------------------------------------------

    def _create_work(self, decision: Decision, observations: list[Observation]) -> Work:
        work = Work(
            id=uuid.uuid4().hex,
            objective=decision.objective or "",
            context=render_context(observations, self.store.all_world_state()),
            status="running",
        )
        self.store.save_work(work)
        return work

    def _execute(self, work: Work) -> Result:
        result = self.agent.execute(work)
        self.store.save_result(result)
        work.status = "done" if result.success else "failed"
        self.store.save_work(work)
        log.info("work %s -> %s", work.id, work.status)
        return result
