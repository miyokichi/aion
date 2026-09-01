"""設定。環境変数だけ。設定フレームワークは持ち込まない。"""

from __future__ import annotations

import os
from dataclasses import dataclass

ANTHROPIC = "anthropic"
OPENAI = "openai"  # OpenAI互換エンドポイント全般（Ollama / llama.cpp / vLLM / LM Studio 等）
PROVIDERS = (ANTHROPIC, OPENAI)

_ANTHROPIC_DEFAULT_MODEL = "claude-opus-5"


@dataclass
class Config:
    db_path: str = "aion.db"
    feed_url: str = "https://feeds.bbci.co.uk/news/world/rss.xml"
    feed_name: str = "world-news"
    feed_limit: int = 5

    # どのLLMで回すか。Decision層とAgent層の両方がこれに従う。
    llm_provider: str = ANTHROPIC
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "local"
    response_format_mode: str = "auto"

    decision_model: str = _ANTHROPIC_DEFAULT_MODEL
    agent_model: str = _ANTHROPIC_DEFAULT_MODEL
    agent_max_turns: int = 12  # Claude Agent SDK
    agent_max_steps: int = 8  # smolagents

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
        provider = os.getenv("AION_LLM_PROVIDER", d.llm_provider).strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"AION_LLM_PROVIDER must be one of {PROVIDERS}, got {provider!r}")

        # ローカルモデル名は環境ごとに違うので、当てずっぽうの既定値を置かない。
        default_model = _ANTHROPIC_DEFAULT_MODEL if provider == ANTHROPIC else ""

        return cls(
            db_path=os.getenv("AION_DB_PATH", d.db_path),
            feed_url=os.getenv("AION_FEED_URL", d.feed_url),
            feed_name=os.getenv("AION_FEED_NAME", d.feed_name),
            feed_limit=int(os.getenv("AION_FEED_LIMIT", d.feed_limit)),
            llm_provider=provider,
            llm_base_url=os.getenv("AION_LLM_BASE_URL", d.llm_base_url),
            llm_api_key=os.getenv("AION_LLM_API_KEY", d.llm_api_key),
            response_format_mode=os.getenv("AION_RESPONSE_FORMAT_MODE", d.response_format_mode),
            decision_model=os.getenv("AION_DECISION_MODEL", default_model),
            agent_model=os.getenv("AION_AGENT_MODEL", default_model),
            agent_max_turns=int(os.getenv("AION_AGENT_MAX_TURNS", d.agent_max_turns)),
            agent_max_steps=int(os.getenv("AION_AGENT_MAX_STEPS", d.agent_max_steps)),
            interval_seconds=float(os.getenv("AION_INTERVAL_SECONDS", d.interval_seconds)),
            max_works_per_cycle=int(os.getenv("AION_MAX_WORKS_PER_CYCLE", d.max_works_per_cycle)),
        )

    def require_model(self, role: str, model: str) -> str:
        if not model.strip():
            raise ValueError(
                f"AION_{role.upper()}_MODEL must be set when AION_LLM_PROVIDER={self.llm_provider}"
                " (ローカルLLMのモデル名は環境ごとに違うため既定値を置いていない)"
            )
        return model
