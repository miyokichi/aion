"""Observation / Result を World State へ反映する。

ここが「世界が今どうなっているか」を決める唯一の場所。
"""

from __future__ import annotations

from aion.core.models import Observation, Result, WorldState, Work
from aion.storage.sqlite import Store

_MAX_STORED_CHARS = 4000


def _truncate(text: str, limit: int = _MAX_STORED_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + " …(truncated)"


def observation_key(observation_id: str) -> str:
    return f"observation:{observation_id}"


def work_key(work_id: str) -> str:
    return f"work:{work_id}"


def reconcile_observations(store: Store, observations: list[Observation]) -> list[WorldState]:
    """観測されたものを世界状態に載せる。まだ誰も調べていない状態で。"""

    return [
        store.put_world_state(
            observation_key(obs.id),
            {
                "source": obs.source,
                "observed_at": obs.observed_at.isoformat(),
                "content": _truncate(obs.content),
                "investigated": False,
                "work_id": None,
            },
        )
        for obs in observations
    ]


def reconcile_result(
    store: Store,
    work: Work,
    result: Result,
    observation_ids: list[str],
) -> list[WorldState]:
    """Agentの成果を世界状態に戻し、対象の観測に調査済みの印を付ける。

    この2つ目の効果があるから、再評価がno_actionへ収束する。

    失敗したWorkでは investigated を立てない。観測は未調査のまま残り、
    次の周回で再挑戦される（同一周回での暴走は max_works_per_cycle が止める）。
    """

    updated = [
        store.put_world_state(
            work_key(work.id),
            {
                "objective": work.objective,
                "status": work.status,
                "success": result.success,
                "output": _truncate(result.output),
                "observation_ids": observation_ids,
            },
        )
    ]
    for obs_id in observation_ids:
        current = store.get_world_state(observation_key(obs_id))
        if current is None:
            continue
        value = dict(current.value)
        value["investigated"] = result.success
        value["work_id"] = work.id
        updated.append(store.put_world_state(current.key, value))
    return updated
