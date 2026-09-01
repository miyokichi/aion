"""World Stateの永続化。SQLiteだけ。Event sourcingは導入しない。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aion.core.models import Observation, Result, WorldState, Work

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS world_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
    id        TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    context   TEXT NOT NULL,
    status    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    work_id TEXT PRIMARY KEY,
    success INTEGER NOT NULL,
    output  TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    """AIONが持つ唯一の永続層。"""

    def __init__(self, path: str | Path = "aion.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- observations -------------------------------------------------

    def save_observations(self, observations: list[Observation]) -> list[Observation]:
        """未知のObservationだけを保存し、保存できたものを返す。

        idが既知なら「変化していない」ということなので黙って捨てる。
        重複排除をLLMに任せない（毎回課金されるため）。
        """
        fresh: list[Observation] = []
        for obs in observations:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO observations (id, source, observed_at, content, metadata)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    obs.id,
                    obs.source,
                    obs.observed_at.isoformat(),
                    obs.content,
                    json.dumps(obs.metadata, ensure_ascii=False),
                ),
            )
            if cur.rowcount:
                fresh.append(obs)
        self._conn.commit()
        return fresh

    def count_observations(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    # --- world state --------------------------------------------------

    def put_world_state(self, key: str, value: dict) -> WorldState:
        state = WorldState(key=key, value=value, updated_at=_now())
        self._conn.execute(
            "INSERT INTO world_state (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (state.key, json.dumps(state.value, ensure_ascii=False), state.updated_at.isoformat()),
        )
        self._conn.commit()
        return state

    def get_world_state(self, key: str) -> WorldState | None:
        row = self._conn.execute("SELECT * FROM world_state WHERE key = ?", (key,)).fetchone()
        return _row_to_state(row) if row else None

    def all_world_state(self) -> list[WorldState]:
        rows = self._conn.execute("SELECT * FROM world_state ORDER BY key").fetchall()
        return [_row_to_state(r) for r in rows]

    # --- works / results ----------------------------------------------

    def save_work(self, work: Work) -> None:
        self._conn.execute(
            "INSERT INTO works (id, objective, context, status) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET status=excluded.status",
            (work.id, work.objective, work.context, work.status),
        )
        self._conn.commit()

    def get_work(self, work_id: str) -> Work | None:
        row = self._conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if row is None:
            return None
        return Work(id=row["id"], objective=row["objective"], context=row["context"], status=row["status"])

    def save_result(self, result: Result) -> None:
        self._conn.execute(
            "INSERT INTO results (work_id, success, output) VALUES (?, ?, ?)"
            " ON CONFLICT(work_id) DO UPDATE SET success=excluded.success, output=excluded.output",
            (result.work_id, int(result.success), result.output),
        )
        self._conn.commit()

    def get_result(self, work_id: str) -> Result | None:
        row = self._conn.execute("SELECT * FROM results WHERE work_id = ?", (work_id,)).fetchone()
        if row is None:
            return None
        return Result(work_id=row["work_id"], success=bool(row["success"]), output=row["output"])


def _row_to_state(row: sqlite3.Row) -> WorldState:
    return WorldState(
        key=row["key"],
        value=json.loads(row["value"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
