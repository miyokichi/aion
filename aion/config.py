"""設定。環境変数だけ。設定フレームワークは持ち込まない。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    db_path: str = "aion.db"
    feed_url: str = "https://feeds.bbci.co.uk/news/world/rss.xml"
    feed_name: str = "world-news"
    feed_limit: int = 5
    decision_model: str = "claude-opus-5"
    agent_model: str = "claude-opus-5"
    agent_max_turns: int = 12
    interval_seconds: float = 300.0
    max_works_per_cycle: int = 1

    @classmethod
    def from_env(cls) -> "Config":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        d = cls()
        return cls(
            db_path=os.getenv("AION_DB_PATH", d.db_path),
            feed_url=os.getenv("AION_FEED_URL", d.feed_url),
            feed_name=os.getenv("AION_FEED_NAME", d.feed_name),
            feed_limit=int(os.getenv("AION_FEED_LIMIT", d.feed_limit)),
            decision_model=os.getenv("AION_DECISION_MODEL", d.decision_model),
            agent_model=os.getenv("AION_AGENT_MODEL", d.agent_model),
            agent_max_turns=int(os.getenv("AION_AGENT_MAX_TURNS", d.agent_max_turns)),
            interval_seconds=float(os.getenv("AION_INTERVAL_SECONDS", d.interval_seconds)),
            max_works_per_cycle=int(os.getenv("AION_MAX_WORKS_PER_CYCLE", d.max_works_per_cycle)),
        )
