"""AIONの最小データモデル。

必要性が確認されるまでフィールドを増やさないこと。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class Observation:
    id: str
    source: str
    observed_at: datetime
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldState:
    key: str
    value: dict[str, Any]
    updated_at: datetime


@dataclass
class Work:
    id: str
    objective: str
    context: str
    status: str


@dataclass
class Result:
    work_id: str
    success: bool
    output: str


@dataclass
class Decision:
    """LLMの判断。no_action か create_work のどちらか。"""

    action: Literal["no_action", "create_work"]
    reason: str
    objective: str | None = None
    priority: float = 0.0
