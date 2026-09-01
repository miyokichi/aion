"""外界 → Observation。OSS固有の処理はここに閉じ込める。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Protocol

from aion.core.models import Observation

log = logging.getLogger("aion.observation")


class ObservationSource(Protocol):
    """観測源。増やすときはこのProtocolを実装するだけ。"""

    name: str

    def poll(self) -> list[Observation]:
        ...


def _stable_id(source: str, raw_key: str) -> str:
    digest = hashlib.sha256(f"{source}\x00{raw_key}".encode()).hexdigest()
    return digest[:32]


class RSSAdapter:
    """RSS/Atomフィード。

    URLがニュースサイトの公式フィードでも、RSSHubが生成したフィードでも
    AIONにとっては同じもの。だからRSSHub連携はこのAdapterで既に済んでいる。
    """

    def __init__(self, url: str, name: str | None = None, limit: int = 10) -> None:
        self.url = url
        self.name = name or url
        self.limit = limit

    def poll(self) -> list[Observation]:
        import feedparser  # 遅延import: RSSを使わない構成で依存を強制しない

        feed = feedparser.parse(self.url)
        if not feed.entries and feed.get("bozo"):
            # 取得失敗を「変化なし」と取り違えないこと。観測できていないだけ。
            log.warning("source %s unreadable: %s", self.name, feed.get("bozo_exception"))

        observations: list[Observation] = []
        for entry in feed.entries[: self.limit]:
            raw_key = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not raw_key:
                continue
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            content = f"{title}\n\n{summary}".strip()
            observations.append(
                Observation(
                    id=_stable_id(self.name, raw_key),
                    source=self.name,
                    observed_at=_entry_time(entry),
                    content=content,
                    metadata={"title": title, "link": entry.get("link", "")},
                )
            )
        return observations


def _entry_time(entry) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
