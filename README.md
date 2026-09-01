# AION

AIONは、**世界の情報をすべて自身で収集するシステムではない。**

AIONは、**すべての仕事を自身で実行するAgentでもない。**

AIONは、

> 既存のSensor、Knowledge System、LLM、Agent、Toolを接続し、
> Observe → Decide → Act → Reconcile の循環を維持する **薄いControl Plane**

である。

---

## 何を自作していないか

これがこのプロジェクトの主要な成果物である。

| 機能 | 実装 | AION内のコード |
|---|---|---|
| Web収集・変化検知 | RSS/Atom (feedparser)、必要なら RSSHub / changedetection.io | Adapter 1つ |
| Agent Runtime | Claude Agent SDK / smolagents | Adapter 2つ |
| Tool Protocol | MCP（Agent Runtime側が話す） | **なし** |
| Workflow Engine | なし（`while` ループ） | **なし** |
| Event Bus | なし（単一プロセス） | **なし** |
| Knowledge Graph | なし（SQLite） | **なし** |
| 出力スキーマ検証 | Anthropic Structured Outputs | **なし** |

AIONが所有しているのは **Control Loop だけ** である。

OSSの選定理由と、採用しなかったものの理由は [`docs/oss-research.md`](docs/oss-research.md) にある。

---

## 循環

```
External Source (RSS / RSSHub / changedetection.io)
        │
        ▼
   Observation ──────────► SQLite
        │
        ▼
  World State 更新
        │
        ▼
   LLM Decision  ──── no_action ────► 安定
        │
   create_work
        │
        ▼
      Work ──► Agent Runtime (Claude Agent SDK / OpenHands)
                        │
                        ▼
                     Result ──────► SQLite
                        │
                        ▼
               World State 更新
                        │
                        └────► 再評価 ────► no_action
```

再評価が `no_action` に収束するのは、Result の反映が
その観測を `investigated: true` にするからである。
収束の責任は Reconciliation にあり、LLMの気分にはない。

---

## 2つの走らせ方

AIONはLLMを2箇所で使う（**判断**と**実作業**）。
どちらも `AION_LLM_PROVIDER` 一つで切り替わる。

| | `anthropic`（既定） | `openai`（ローカルLLM） |
|---|---|---|
| Decision | Anthropic Messages API + Structured Outputs | OpenAI互換 `/chat/completions` |
| Agent | Claude Agent SDK | smolagents |
| 必要なもの | `ANTHROPIC_API_KEY`、認証済み `claude` CLI | ローカルサーバのURLとモデル名だけ |
| 追加install | `.[anthropic]` | `.[local]` |

クラウドに一切出さずに回せる。使う側の部品だけ入れればよい。

---

## セットアップ

```bash
uv venv
cp .env.example .env
```

**Anthropicで動かす場合:**

```bash
uv pip install -e ".[anthropic]"
# .env に ANTHROPIC_API_KEY を入れる
```

Agent層は [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) を使う。
`claude` CLI が PATH 上にあり、認証済みである必要がある。

**OpenAI互換のローカルLLMで動かす場合:**

```bash
uv pip install -e ".[local]"
```

```bash
# .env
AION_LLM_PROVIDER=openai
AION_LLM_BASE_URL=http://localhost:11434/v1   # Ollama。vLLMは :8000、LM Studioは :1234
AION_DECISION_MODEL=qwen3:8b
AION_AGENT_MODEL=qwen3:8b
```

APIキーは不要（`AION_LLM_API_KEY` の既定値 `local` がそのまま送られる）。
**モデル名に既定値は無い。** 環境ごとに違うものを推測しても外れるだけなので、
未設定なら起動時に明示的に失敗する。

### ローカルLLMのために吸収していること

ローカルLLMは指示追従が弱く、サーバごとに対応機能も違う。
AIONはその2点だけを吸収する（判断そのものには手を入れない）。

- **応答形式の交渉**: `response_format` を
  `json_schema` → `json_object` → 指定なし の順に試し、通った形式を記憶する。
  以後は探索しない。`AION_RESPONSE_FORMAT_MODE` で固定もできる。
- **寛容なパース**: `<think>…</think>` の思考ブロック、コードフェンス、
  前後の散文を剥がしてJSONを取り出す。
- **壊れても止まらない**: 判断が取れなかった周回は理由付きの `no_action` に落とし、
  WARNINGを出す。常時稼働を1回の不正出力で落とさない。

## 実行

```bash
aion once     # 1周だけ回す
aion run      # 常時稼働（AION_INTERVAL_SECONDS 間隔）
aion state    # 現在のWorld Stateを表示
```

`aion once` の出力例:

```json
{
  "observations": 3,
  "works": 1,
  "decisions": [
    {"action": "create_work", "reason": "possible downstream impact"},
    {"action": "no_action", "reason": "already investigated"}
  ],
  "settled": true
}
```

`settled: true` は「再評価がno_actionに落ち着いた」= 1周が完走したことを意味する。

## テスト

```bash
pytest
```

- `tests/test_e2e_loop.py` — 外部サービスを呼ばずに循環を1周させ、
  指示書 §19 の完成条件を1項目ずつ検証する
- `tests/test_local_llm_wire.py` — OpenAI互換の最小HTTPサーバを実際に立て、
  ローカル経路を実HTTP越しに1周させる（形式フォールバックとAgent実行を含む）

---

## 構成

```
aion/
├── app.py          エントリポイント（組み立てるだけ）
├── config.py       環境変数
├── core/
│   ├── models.py           Observation / WorldState / Work / Result / Decision
│   ├── loop.py             Control Loop ← AIONの本体はここだけ
│   ├── decision.py         LLM判断（Structured Outputs）
│   └── reconciliation.py   世界状態への反映
├── adapters/
│   ├── observation.py      ObservationSource: RSSAdapter
│   └── agent.py            AgentExecutor: ClaudeAgentAdapter / SmolagentsAdapter
└── storage/
    └── sqlite.py           observations / world_state / works / results
```

## 部品の差し替え

外部部品は Protocol 2つでしか繋がっていない。

```python
class ObservationSource(Protocol):
    def poll(self) -> list[Observation]: ...

class AgentExecutor(Protocol):
    def execute(self, work: Work) -> Result: ...
```

- **観測源を増やす**: `poll()` を持つクラスを1つ書く。
  RSSHubを使う場合はコード変更すら不要で、`AION_FEED_URL` を差し替えるだけ。
- **Agentを差し替える**: `execute()` を持つクラスを1つ書く。
  同梱の2つ（Claude Agent SDK / smolagents）はどちらも50行程度しかない。
  OpenHands を使う場合は [`docs/oss-research.md`](docs/oss-research.md) の
  制約（Python>=3.12）を先に確認すること。

Adapter framework は作らない。Protocol以上のものを足さないこと。

---

## 成功指標

機能数ではなく、これを見る（指示書 §18）。

| 指標 | 現在 |
|---|---|
| AION独自コード | 約850行（`aion/`、docstring込み・テスト除く） |
| 常駐サービス | 0（Docker不要） |
| 自作したインフラ部品 | 0（Agent / Workflow / Event Bus / KG / Tool Protocol いずれも無し） |
| E2Eの周回 | 1本（`observe → decide → act → reconcile → 再評価`） |
| 外部部品の交換点 | Protocol 2つ |
| LLMプロバイダ | 2（クラウド / ローカル、環境変数1つで切替） |

独自コードが大量に増えた場合は設計を再検討すること。

---

## 設計上の制約（意図的に実装していないもの）

独自Agent Framework / 独自Workflow Engine / 独自Knowledge Graph /
独自Event Bus / Multi-Agent orchestration / Goal hierarchy / GUI / Dashboard /
Microservices / Kubernetes / NATS / Temporal。

必要性が実証されてから導入する。

機能を足したくなったら、先に問うこと:

> **同じ機能を提供する成熟したOSSが存在しないか？**

存在する場合は原則としてOSSを使う。AIONを大きくしないこと。
