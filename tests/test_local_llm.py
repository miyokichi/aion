"""OpenAI互換（ローカルLLM）経路。

ローカルLLMは (a) 応答形式のサポートがサーバごとに違い、
(b) 素直にJSONを返さない。その両方を吸収できているかを見る。
"""

import pytest

from aion.adapters.agent import ClaudeAgentAdapter, SmolagentsAdapter
from aion.app import build_agent, build_decision_engine
from aion.config import Config
from aion.core.decision import (
    ClaudeDecisionEngine,
    OpenAICompatibleDecisionEngine,
    parse_decision_text,
)
from tests.fakes import FakeOpenAIClient, HttpError, make_observation

GOOD = '{"action": "create_work", "reason": "may matter", "objective": "Investigate.", "priority": 0.7}'


def engine(client, **kw):
    return OpenAICompatibleDecisionEngine(
        model="local-model", base_url="http://localhost:11434/v1", client=client, **kw
    )


def evaluate(eng):
    return eng.evaluate([make_observation()], [])


# --- 応答形式のネゴシエーション ----------------------------------------

def test_uses_json_schema_when_the_server_supports_it():
    client = FakeOpenAIClient([GOOD])
    decision = evaluate(engine(client))

    assert decision.action == "create_work"
    assert client.calls[0]["response_format"]["type"] == "json_schema"


def test_falls_back_when_json_schema_is_rejected():
    client = FakeOpenAIClient([HttpError(400, "response_format json_schema not supported"), GOOD])
    eng = engine(client)

    assert evaluate(eng).action == "create_work"
    assert [c["response_format"]["type"] for c in client.calls] == ["json_schema", "json_object"]


def test_falls_back_all_the_way_to_no_response_format():
    client = FakeOpenAIClient([HttpError(400, "bad"), HttpError(400, "bad"), GOOD])

    assert evaluate(engine(client)).action == "create_work"
    assert "response_format" not in client.calls[-1]


def test_working_format_is_remembered():
    client = FakeOpenAIClient([HttpError(400, "nope"), GOOD, GOOD])
    eng = engine(client)

    evaluate(eng)
    evaluate(eng)

    # 2回目は探索しない
    assert [c["response_format"]["type"] for c in client.calls] == [
        "json_schema",
        "json_object",
        "json_object",
    ]


def test_response_format_mode_can_be_pinned():
    client = FakeOpenAIClient([GOOD])
    evaluate(engine(client, response_format_mode="none"))
    assert "response_format" not in client.calls[0]


def test_unknown_response_format_mode_is_rejected():
    with pytest.raises(ValueError):
        engine(FakeOpenAIClient([GOOD]), response_format_mode="magic")


# --- 失敗しても止まらない -----------------------------------------------

def test_non_format_errors_degrade_to_no_action():
    client = FakeOpenAIClient([HttpError(500, "server exploded")])
    decision = evaluate(engine(client))

    assert decision.action == "no_action"
    assert "unavailable" in decision.reason
    # 500は形式の問題ではないので探索を続けない
    assert len(client.calls) == 1


def test_unparseable_output_degrades_to_no_action():
    decision = evaluate(engine(FakeOpenAIClient(["I think we should probably wait."])))
    assert decision.action == "no_action"
    assert "unparseable" in decision.reason


def test_schema_violation_degrades_to_no_action():
    bad = '{"action": "explode", "reason": "x", "objective": null, "priority": 0.1}'
    decision = evaluate(engine(FakeOpenAIClient([bad])))
    assert decision.action == "no_action"
    assert "invalid" in decision.reason


# --- ローカルLLMの出力の癖 ----------------------------------------------

def test_parses_json_wrapped_in_prose_and_code_fence():
    text = f"Sure! Here is my decision:\n\n```json\n{GOOD}\n```\n\nLet me know if that helps."
    assert parse_decision_text(text).action == "create_work"


def test_parses_json_after_a_reasoning_block():
    text = f"<think>\nHmm, {{not json}} at all. I should create work.\n</think>\n{GOOD}"
    decision = parse_decision_text(text)
    assert decision.action == "create_work"
    assert decision.objective == "Investigate."


def test_parses_bare_json_with_trailing_text():
    assert parse_decision_text(GOOD + "\n\nThat is my answer.").action == "create_work"


def test_create_work_without_objective_still_falls_back_to_no_action():
    text = '{"action": "create_work", "reason": "vague", "objective": "", "priority": 0.5}'
    assert parse_decision_text(text).action == "no_action"


# --- 組み立て -----------------------------------------------------------

def test_provider_selects_the_local_stack():
    config = Config(
        llm_provider="openai",
        decision_model="qwen3:8b",
        agent_model="qwen3:8b",
        llm_base_url="http://localhost:11434/v1",
    )
    assert isinstance(build_decision_engine(config), OpenAICompatibleDecisionEngine)
    assert isinstance(build_agent(config), SmolagentsAdapter)


def test_provider_selects_the_anthropic_stack():
    config = Config(llm_provider="anthropic")
    assert isinstance(build_decision_engine(config), ClaudeDecisionEngine)
    assert isinstance(build_agent(config), ClaudeAgentAdapter)


def test_local_provider_requires_an_explicit_model():
    config = Config(llm_provider="openai", decision_model="", agent_model="")
    with pytest.raises(ValueError, match="AION_DECISION_MODEL"):
        build_decision_engine(config)
    with pytest.raises(ValueError, match="AION_AGENT_MODEL"):
        build_agent(config)


def test_env_selects_provider_and_drops_the_anthropic_default(monkeypatch):
    monkeypatch.setenv("AION_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AION_LLM_BASE_URL", "http://localhost:8000/v1")
    config = Config.from_env()

    assert config.llm_provider == "openai"
    assert config.llm_base_url == "http://localhost:8000/v1"
    assert config.decision_model == ""  # ローカルのモデル名を推測しない


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("AION_LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="AION_LLM_PROVIDER"):
        Config.from_env()


def test_cli_reports_config_errors_without_a_traceback(monkeypatch, tmp_path, capsys):
    from aion.app import main

    monkeypatch.setenv("AION_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AION_DECISION_MODEL", "")
    monkeypatch.setenv("AION_DB_PATH", str(tmp_path / "aion.db"))

    assert main(["once"]) == 2
    assert "config error" in capsys.readouterr().err
