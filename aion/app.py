"""エントリポイント。組み立てるだけ。"""

from __future__ import annotations

import argparse
import json
import logging

from aion.adapters.agent import ClaudeAgentAdapter
from aion.adapters.observation import RSSAdapter
from aion.config import Config
from aion.core.decision import ClaudeDecisionEngine
from aion.core.loop import ControlLoop
from aion.storage.sqlite import Store


def build_loop(config: Config, store: Store) -> ControlLoop:
    return ControlLoop(
        source=RSSAdapter(config.feed_url, name=config.feed_name, limit=config.feed_limit),
        decision_engine=ClaudeDecisionEngine(model=config.decision_model),
        agent=ClaudeAgentAdapter(model=config.agent_model, max_turns=config.agent_max_turns),
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

    config = Config.from_env()
    with Store(config.db_path) as store:
        if args.command == "state":
            for state in store.all_world_state():
                print(f"{state.key}\t{state.updated_at.isoformat()}")
                print(json.dumps(state.value, ensure_ascii=False, indent=2))
            return 0

        loop = build_loop(config, store)
        if args.command == "once":
            report = loop.run_once()
            print(
                json.dumps(
                    {
                        "observations": len(report.observations),
                        "works": len(report.works),
                        "decisions": [d.action for d in report.decisions],
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
