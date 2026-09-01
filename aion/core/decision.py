"""LLM Decision。ObservationとWorld Stateを見て no_action / create_work を決める。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from aion.core.models import Decision, Observation, WorldState

log = logging.getLogger("aion.decision")

_SYSTEM_PROMPT = """\
You are the decision layer of an autonomous observation system called AION.

You are given newly observed events and the system's current world state.
Decide exactly one of:

- "no_action": nothing here changes what the system should be doing. This is the
  correct answer most of the time, and it is the correct answer whenever the
  world state already contains an investigation of this event.
- "create_work": this observation plausibly has downstream consequences that are
  worth investigating, and the world state does not already cover it. Give a
  single, self-contained objective a research worker can act on unattended.

Prefer no_action. Creating redundant work is worse than missing a marginal event.
"""


class DecisionOutput(BaseModel):
    """LLMに守らせるスキーマ（Structured Outputs）。"""

    action: Literal["no_action", "create_work"]
    reason: str = Field(description="One sentence explaining the decision.")
    objective: str | None = Field(
        default=None,
        description="Required when action is create_work; null otherwise.",
    )
    priority: float = Field(default=0.0, ge=0.0, le=1.0)


class DecisionEngine(Protocol):
    def evaluate(
        self, observations: list[Observation], world_state: list[WorldState]
    ) -> Decision:
        ...


def render_context(observations: list[Observation], world_state: list[WorldState]) -> str:
    """LLMに渡す入力を組み立てる。ここ以外にプロンプトを散らかさない。"""

    obs_lines = [
        f"- [{o.source}] {o.observed_at.isoformat()}\n  {o.content}" for o in observations
    ] or ["(none)"]
    state_lines = [
        f"- {s.key} (updated {s.updated_at.isoformat()}):\n  "
        + json.dumps(s.value, ensure_ascii=False)
        for s in world_state
    ] or ["(empty)"]
    return (
        "# New observations\n"
        + "\n".join(obs_lines)
        + "\n\n# Current world state\n"
        + "\n".join(state_lines)
    )


class ClaudeDecisionEngine:
    """Anthropic Messages API + Structured Outputs。

    出力形式の検証はAPI側に任せる。パーサを自作しない。
    """

    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic  # 遅延import

            self._client = anthropic.Anthropic()
        return self._client

    def evaluate(
        self, observations: list[Observation], world_state: list[WorldState]
    ) -> Decision:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": render_context(observations, world_state)}],
            output_format=DecisionOutput,
        )
        return _to_decision(response.parsed_output)


def _to_decision(parsed: DecisionOutput) -> Decision:
    # objectiveの無いcreate_workは実行できないので no_action に倒す。
    if parsed.action == "create_work" and not (parsed.objective or "").strip():
        return Decision(
            action="no_action",
            reason=f"create_work without an objective; treated as no_action ({parsed.reason})",
        )
    return Decision(
        action=parsed.action,
        reason=parsed.reason,
        objective=parsed.objective,
        priority=parsed.priority,
    )


# --- OpenAI互換（ローカルLLM）------------------------------------------

# 手書きのJSON Schema。pydantic生成のものは `str | None` を anyOf に展開し、
# サーバによっては受け付けないため、移植性の高い形を明示する。
DECISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["no_action", "create_work"]},
        "reason": {"type": "string"},
        "objective": {"type": ["string", "null"]},
        "priority": {"type": "number"},
    },
    "required": ["action", "reason", "objective", "priority"],
    "additionalProperties": False,
}

_JSON_INSTRUCTION = (
    "Respond with a single JSON object and nothing else. Schema:\n"
    '{"action": "no_action" | "create_work", "reason": string, '
    '"objective": string | null, "priority": number between 0 and 1}'
)

# 応答形式のサポートはサーバごとに違う。強い方から順に試して落とす。
_RESPONSE_FORMAT_MODES = ("json_schema", "json_object", "none")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class OpenAICompatibleDecisionEngine:
    """OpenAI互換エンドポイント（Ollama / llama.cpp / vLLM / LM Studio 等）。

    ローカルLLMは指示追従が弱く、応答形式のサポートもサーバごとに違う。
    そこで2段構えにする:

    1. `response_format` を json_schema → json_object → 指定なし の順に試し、
       通った形式を記憶する（毎回の探索はしない）
    2. どの形式でも、返ってきたテキストは寛容にパースする
       （思考タグ、コードフェンス、前後の散文を剥がす）

    ここで吸収しているのは「ローカルLLMの癖」だけで、判断そのものではない。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "local",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format_mode: str = "auto",
        client: Any = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client
        if response_format_mode == "auto":
            self._modes = list(_RESPONSE_FORMAT_MODES)
        elif response_format_mode in _RESPONSE_FORMAT_MODES:
            self._modes = [response_format_mode]
        else:
            raise ValueError(f"unknown response_format_mode: {response_format_mode}")

    @property
    def client(self):
        if self._client is None:
            import openai  # 遅延import

            self._client = openai.OpenAI(base_url=self.base_url, api_key=self.api_key)
        return self._client

    def evaluate(
        self, observations: list[Observation], world_state: list[WorldState]
    ) -> Decision:
        messages = [
            {"role": "system", "content": f"{_SYSTEM_PROMPT}\n\n{_JSON_INSTRUCTION}"},
            {"role": "user", "content": render_context(observations, world_state)},
        ]
        text = self._complete(messages)
        if text is None:
            return Decision(action="no_action", reason="decision unavailable: LLM call failed")
        return parse_decision_text(text)

    def _complete(self, messages: list[dict]) -> str | None:
        """通る応答形式が見つかるまで落としながら試し、その形式を記憶する。"""
        last_error: Exception | None = None
        for mode in list(self._modes):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **_response_format(mode),
                )
            except Exception as exc:  # 形式非対応は400で返ることが多い
                last_error = exc
                if _is_unsupported_format(exc):
                    log.info("response_format=%s rejected by the server; falling back", mode)
                    continue
                log.warning("decision call failed: %s", exc)
                return None
            # 通った形式だけを以後使う
            self._modes = [mode]
            return response.choices[0].message.content or ""
        log.warning("no usable response_format; last error: %s", last_error)
        return None


def _response_format(mode: str) -> dict:
    if mode == "json_schema":
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "aion_decision", "schema": DECISION_JSON_SCHEMA},
            }
        }
    if mode == "json_object":
        return {"response_format": {"type": "json_object"}}
    return {}


def _is_unsupported_format(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (400, 404, 422, 501):
        return True
    text = str(exc).lower()
    return "response_format" in text or "json_schema" in text


def parse_decision_text(text: str) -> Decision:
    """LLMの生テキストからDecisionを取り出す。散文に埋もれていても拾う。"""
    payload = _extract_json(text)
    if payload is None:
        log.warning("decision output was not JSON: %.200s", text)
        return Decision(action="no_action", reason="decision unparseable: no JSON object found")
    try:
        return _to_decision(DecisionOutput.model_validate(payload))
    except ValidationError as exc:
        log.warning("decision output failed validation: %s", exc)
        return Decision(action="no_action", reason=f"decision invalid: {exc.error_count()} error(s)")


def _extract_json(text: str) -> dict | None:
    text = _THINK_BLOCK.sub("", text or "").strip()
    fenced = _CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    for candidate in _json_candidates(text):
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


def _json_candidates(text: str):
    """先頭から順に、括弧の釣り合った {...} を切り出す。"""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                yield text[start : i + 1]
                start = -1
            elif depth < 0:
                depth = 0
