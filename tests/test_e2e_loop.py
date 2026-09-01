"""指示書 §13 / §19 のE2E。

External Observation → Observation → SQLite → LLM評価 → create_work →
Agent委譲 → 実作業 → Result → SQLite → World State更新 → 再評価 → no_action
"""

from aion.core.loop import ControlLoop
from aion.core.reconciliation import observation_key, work_key
from aion.storage.sqlite import Store
from tests.fakes import (
    FailingAgent,
    StubAgent,
    StubSource,
    WorldStateAwareDecisionEngine,
    make_observation,
)


def obs_id(report):
    return report.observations[0].id


def build(tmp_path, agent=None):
    store = Store(tmp_path / "aion.db")
    source = StubSource([make_observation()])
    engine = WorldStateAwareDecisionEngine()
    agent = agent or StubAgent()
    loop = ControlLoop(source, engine, agent, store)
    return loop, store, source, engine, agent


def test_full_cycle_settles_at_no_action(tmp_path):
    loop, store, source, engine, agent = build(tmp_path)

    report = loop.run_once()

    # 外部情報を1種類取得し、Observationへ正規化できた
    assert source.polls == 1
    assert len(report.observations) == 1
    obs = report.observations[0]

    # SQLiteへ保存できた
    assert store.count_observations() == 1

    # World Stateを更新できた
    observed = store.get_world_state(observation_key(obs.id))
    assert observed is not None
    assert observed.value["source"] == "stub"

    # create_work → Work生成 → 既存Agentへ委譲 → 実作業
    assert report.decisions[0].action == "create_work"
    assert len(report.works) == 1
    work = report.works[0]
    assert agent.executed == [work]
    assert work.objective

    # Workのcontextには観測と世界状態が入っている（Agentが文脈を持てる）
    assert obs.content in work.context

    # Resultを取得・保存できた
    assert len(report.results) == 1
    assert store.get_result(work.id).output == report.results[0].output
    assert store.get_work(work.id).status == "done"

    # ResultをWorld Stateへ反映できた
    reflected = store.get_world_state(work_key(work.id))
    assert reflected.value["success"] is True
    assert reflected.value["observation_ids"] == [obs.id]
    assert store.get_world_state(observation_key(obs.id)).value["investigated"] is True

    # 再評価し、no_actionで安定状態に入った
    assert engine.calls == 2
    assert report.decisions[-1].action == "no_action"
    assert report.settled is True

    store.close()


def test_second_cycle_observes_nothing_new(tmp_path):
    loop, store, source, engine, _ = build(tmp_path)
    loop.run_once()
    calls_after_first = engine.calls

    report = loop.run_once()

    assert source.polls == 2
    assert report.observations == []
    assert report.decisions == []
    # 変化がなければLLMを呼ばない
    assert engine.calls == calls_after_first
    store.close()


def test_work_budget_stops_runaway_cycles(tmp_path):
    """Agentが失敗して観測が未調査のままでも、1周のWorkは上限で止まる。"""
    loop, store, *_ = build(tmp_path, agent=FailingAgent())
    loop.max_works_per_cycle = 1

    report = loop.run_once()

    assert len(report.works) == 1
    assert report.results[0].success is False
    assert store.get_work(report.works[0].id).status == "failed"
    # 失敗しても結果は世界状態に残る
    assert store.get_world_state(work_key(report.works[0].id)).value["success"] is False
    # 失敗したので観測は未調査のまま。再評価はまたcreate_workを返すが、
    # Work予算が尽きているのでこの周回はそこで止まる（安定はしていない）。
    assert store.get_world_state(observation_key(obs_id(report))).value["investigated"] is False
    assert [d.action for d in report.decisions] == ["create_work", "create_work"]
    assert report.settled is False
    store.close()
