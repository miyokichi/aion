"""エントリポイント。組み立てるだけ。"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from aion.adapters.agent import AgentExecutor, ClaudeAgentAdapter, SmolagentsAdapter
from aion.adapters.observation import RSSAdapter
from aion.config import ANTHROPIC, Config
from aion.core.decision import (
    ClaudeDecisionEngine,
    DecisionEngine,
    OpenAICompatibleDecisionEngine,
)
from aion.core.loop import ControlLoop
from aion.storage.sqlite import Store


def build_decision_engine(config: Config) -> DecisionEngine:
    model = config.require_model("decision", config.decision_model)
    if config.llm_provider == ANTHROPIC:
        return ClaudeDecisionEngine(model=model)
    return OpenAICompatibleDecisionEngine(
        model=model,
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        response_format_mode=config.response_format_mode,
    )


def build_agent(config: Config) -> AgentExecutor:
    model = config.require_model("agent", config.agent_model)
    if config.llm_provider == ANTHROPIC:
        return ClaudeAgentAdapter(model=model, max_turns=config.agent_max_turns)
    # Claude Agent SDK はAnthropicのエンドポイントしか話さないので、
    # ローカルLLMではOpenAI互換を話すAgent Runtimeに差し替える。
    return SmolagentsAdapter(
        model=model,
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        max_steps=config.agent_max_steps,
    )


def build_loop(config: Config, store: Store) -> ControlLoop:
    return ControlLoop(
        source=RSSAdapter(config.feed_url, name=config.feed_name, limit=config.feed_limit),
        decision_engine=build_decision_engine(config),
        agent=build_agent(config),
        store=store,
        max_works_per_cycle=config.max_works_per_cycle,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aion")
    parser.add_argument("command", choices=["once", "run", "state"])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = Config.from_env()
    except ValueError as exc:
        # 設定ミスにトレースバックは要らない。何を直せばいいかだけ出す。
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    with Store(config.db_path) as store:
        if args.command == "state":
            for state in store.all_world_state():
                print(f"{state.key}\t{state.updated_at.isoformat()}")
                print(json.dumps(state.value, ensure_ascii=False, indent=2))
            return 0

        try:
            loop = build_loop(config, store)
        except ValueError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        if args.command == "once":
            report = loop.run_once()
            print(
                json.dumps(
                    {
                        "observations": len(report.observations),
                        "works": len(report.works),
                        "decisions": [
                            {"action": d.action, "reason": d.reason} for d in report.decisions
                        ],
                        "settled": report.settled,
                    },
                    indent=2,
                )
            )
            return 0

        loop.run_forever(interval=config.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
