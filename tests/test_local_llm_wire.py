"""OpenAI互換の実HTTPサーバに対して、ローカル経路を丸ごと1周させる。

モックしたクライアントではなく実際のHTTPを通すことで、
「リクエストの形がサーバに受け付けられるか」まで確認する。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aion.adapters.agent import SmolagentsAdapter
from aion.core.decision import OpenAICompatibleDecisionEngine
from aion.core.loop import ControlLoop
from aion.storage.sqlite import Store
from tests.fakes import StubSource, make_observation

# ローカルLLMにありがちな出力: 思考ブロック + コードフェンス + 後置きの散文
_DECISION_BODY = (
    "<think>This looks consequential, so I should create work.</think>\n"
    "```json\n"
    '{"action": "create_work", "reason": "possible downstream impact",'
    ' "objective": "Investigate the likely impact and summarize findings.",'
    ' "priority": 0.8}\n'
    "```\n"
    "Hope that helps!"
)
_AGENT_ANSWER = "Energy and shipping exposure; two carriers rerouting."


class _Handler(BaseHTTPRequestHandler):
    """/v1/chat/completions だけを喋る最小のOpenAI互換サーバ。"""

    def log_message(self, *args):  # テスト出力を汚さない
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)

        # json_schema 非対応のサーバを模す（フォールバックを実際に踏ませる）
        if body.get("response_format", {}).get("type") == "json_schema":
            return self._send(400, {"error": {"message": "response_format json_schema unsupported"}})

        if any(t.get("function", {}).get("name") == "final_answer" for t in body.get("tools", [])):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "final_answer",
                            "arguments": json.dumps({"answer": _AGENT_ANSWER}),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": _DECISION_BODY}

        self._send(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "model": body.get("model", "stub"),
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def _send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def openai_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def test_local_stack_completes_one_cycle(tmp_path, openai_server):
    server, base_url = openai_server
    store = Store(tmp_path / "aion.db")
    loop = ControlLoop(
        source=StubSource([make_observation()]),
        decision_engine=OpenAICompatibleDecisionEngine(model="stub-model", base_url=base_url),
        agent=SmolagentsAdapter(model="stub-model", base_url=base_url, max_steps=3),
        store=store,
    )

    report = loop.run_once()

    # json_schema を蹴られて json_object に落ちた上で、判断が読めている
    formats = [r.get("response_format", {}).get("type") for r in server.requests]
    assert formats[:2] == ["json_schema", "json_object"]
    assert report.decisions[0].action == "create_work"

    # 実際のAgent Runtimeが実HTTP越しに走り、結果が返っている
    assert len(report.results) == 1
    assert report.results[0].success is True
    assert _AGENT_ANSWER in report.results[0].output

    # 再評価まで到達し、World Stateに反映されている
    assert report.decisions[-1].action == "create_work"  # スタブは常にcreate_workを返す
    assert store.get_result(report.works[0].id) is not None
    store.close()
