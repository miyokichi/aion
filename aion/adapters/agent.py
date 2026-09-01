"""Work → 既存Agent Runtime → Result。

AIONはAgentを実装しない。委譲するだけ。
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from aion.core.models import Result, Work


class AgentExecutor(Protocol):
    """作業の実行者。差し替え可能にしておく（OpenHands等は後から足せる）。"""

    def execute(self, work: Work) -> Result:
        ...


_SYSTEM_PROMPT = (
    "You are a research worker inside an autonomous observation system. "
    "You are given one objective and the context that produced it. "
    "Investigate using the tools available, then answer with your findings and "
    "the evidence behind them. Be concrete and state your uncertainty. "
    "Do not ask follow-up questions - you are running unattended."
)


class ClaudeAgentAdapter:
    """Claude Agent SDK への薄いアダプタ。

    Agentループ・ツール実行・権限・セッション管理はすべてSDK側が持つ。
    ここにあるのは「WorkをpromptにしてResultを取り出す」だけ。
    """

    def __init__(
        self,
        model: str = "claude-opus-5",
        max_turns: int = 12,
        allowed_tools: list[str] | None = None,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        # 読むだけのツールに限定する。許可していないツールは実行されない。
        self.allowed_tools = allowed_tools or ["WebSearch", "WebFetch"]

    def execute(self, work: Work) -> Result:
        try:
            output = asyncio.run(self._run(work))
        except Exception as exc:  # Agent側の失敗もWorld Stateに残す
            return Result(work_id=work.id, success=False, output=f"{type(exc).__name__}: {exc}")
        if not output.strip():
            return Result(work_id=work.id, success=False, output="agent returned no output")
        return Result(work_id=work.id, success=True, output=output)

    async def _run(self, work: Work) -> str:
        from claude_agent_sdk import (  # 遅延import
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        options = ClaudeAgentOptions(
            system_prompt=_SYSTEM_PROMPT,
            model=self.model,
            max_turns=self.max_turns,
            allowed_tools=self.allowed_tools,
        )
        prompt = f"# Objective\n{work.objective}\n\n# Context\n{work.context}"

        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        chunks.append(block.text.strip())
        return "\n\n".join(chunks)


class SmolagentsAdapter:
    """smolagents への薄いアダプタ（OpenAI互換 = ローカルLLM向け）。

    Agentループ・ツール呼び出し・プロンプトはすべて smolagents 側が持つ。
    ここにあるのは「WorkをtaskにしてResultを取り出す」だけ。

    Claude Agent SDK はAnthropicのエンドポイントしか話さないので、
    ローカルLLMで動かす経路としてこちらを使う。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "local",
        max_steps: int = 8,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_steps = max_steps

    def execute(self, work: Work) -> Result:
        try:
            output = self._run(work)
        except Exception as exc:
            return Result(work_id=work.id, success=False, output=f"{type(exc).__name__}: {exc}")
        if not output.strip():
            return Result(work_id=work.id, success=False, output="agent returned no output")
        return Result(work_id=work.id, success=True, output=output)

    def _run(self, work: Work) -> str:
        from smolagents import (  # 遅延import
            OpenAIServerModel,
            ToolCallingAgent,
            VisitWebpageTool,
            WebSearchTool,
        )

        agent = ToolCallingAgent(
            tools=[WebSearchTool(), VisitWebpageTool()],
            model=OpenAIServerModel(
                model_id=self.model, api_base=self.base_url, api_key=self.api_key
            ),
        )
        task = f"{_SYSTEM_PROMPT}\n\n# Objective\n{work.objective}\n\n# Context\n{work.context}"
        return str(agent.run(task, max_steps=self.max_steps))
