# AION OSS調査

コードを書く前の調査結果（指示書 §5）。

判断基準は一つだけ:

> AIONが自作せずに済むものは何か。

調査日: 2026-09-01

---

## サマリ（分類）

| 分類 | OSS | 理由 |
|---|---|---|
| **USE NOW** | RSS/Atom (feedparser) | 外界の一次ソース。最も単純で依存が軽い。RSSHub等の出力もそのまま食える |
| **USE NOW** | SQLite (stdlib) | World State永続化。追加依存ゼロ |
| **USE NOW** | Anthropic API (`anthropic`) + Structured Outputs | LLM Decision。判断スキーマの検証を自作しない |
| **USE NOW** | Claude Agent SDK (`claude-agent-sdk`) | 既存Agent Runtime。ループ・ツール・権限・セッションを自作しない |
| **USE LATER** | RSSHub | 非RSSソース（SNS等）が必要になったら、URLを差し替えるだけで載る |
| **USE LATER** | changedetection.io | 「RSSを持たないWebページ」の変化検知が必要になった時点で |
| **USE LATER** | OpenHands | コード実行・リポジトリ操作を伴うWorkが必要になった時点で |
| **USE LATER** | MCP | 外部ツールを増やす時。Agent SDK側の設定として入る（AION本体は無改造） |
| **NOT NEEDED** | World Monitor | 「World Monitor」という確立したOSSは存在しない（後述） |
| **NOT NEEDED** | Huginn | Ruby/Rails + DB。RSSAdapterで足りる範囲に対して統合コストが重すぎる |
| **NOT NEEDED** | Semantica | KG不要。SQLiteで足りる（指示書 §4） |
| **NOT NEEDED** | Temporal | 単一プロセスのループにdurable workflowは過剰（指示書 §4） |
| **NOT NEEDED** | NATS JetStream | 単一プロセス内。Event Bus不要（指示書 §4） |

---

## 各OSS詳細

### World Monitor

| 項目 | 内容 |
|---|---|
| Role | Observation（外界の観測） |
| Interface | — |
| Deployment | — |
| Complexity | 高（不確実） |
| MVP必要性 | **不要** |
| Replacement | — |

調査の結論: **「World Monitor」という単一の確立したOSSは存在しない。**
GitHub上には同名・類似名のプロジェクトが多数あるが（`tncsharetool/worldmonitor`,
`sjkncs/worldmonitor`, `koala73/worldmonitor`, `rodgersgitau/world-monitor`,
`SageHourihan/clermont` 等）、いずれも
「地政学インテリジェンス・ダッシュボード」であり、

- 互いに無関係な別プロジェクト
- 成果物はGUIダッシュボード（AIONが欲しいのは機械可読な観測ストリーム）
- 安定した外部向けAPI契約が公開されていない
- どれが「本家」か決められない

指示書 §6 は「World Monitorが簡単に接続できるなら使う。難しければRSS/API等
もっと単純なソースから開始してよい」としている。**難しい側**に該当するため、
MVPではRSSから開始する。

将来これらのどれかが安定APIを出したなら、`ObservationSource` を1つ足すだけで載る。

---

### changedetection.io

| 項目 | 内容 |
|---|---|
| Role | Observation（Webページの変化検知） |
| Interface | REST API（watch/tag/notification のCRUD、OpenAPI仕様あり）。通知はApprise経由 |
| Deployment | `docker compose up -d` / `pip3 install changedetection.io` |
| Complexity | 中（常駐プロセス1つ + APIキー） |
| MVP必要性 | **不要（USE LATER）** |
| Replacement | Webスクレイパ、差分検出、JS描画、プロキシ管理 |

License: Apache-2.0。
RSSを持たないページを見たくなった時点で `ChangedetectionAdapter` を足す。
そのときもAION本体のコードは変わらない（`ObservationSource` 実装が1つ増えるだけ）。

---

### RSSHub

| 項目 | 内容 |
|---|---|
| Role | Observation（非RSSソース → RSS化） |
| Interface | RSS/Atom/JSON Feed のHTTPエンドポイント |
| Deployment | Docker / npm / Vercel。公開インスタンス `rsshub.app` あり |
| Complexity | **極小**（AION側は追加コードゼロ。URLを変えるだけ） |
| MVP必要性 | **不要だが、いつでも使える（USE LATER）** |
| Replacement | Twitter/YouTube/Bilibili等の個別APIクライアント |

License: AGPL-3.0（自己ホストする場合はライセンスに注意。公開インスタンスを
HTTPで叩くだけならAIONの配布物には影響しない）。

**重要**: AIONの `RSSAdapter` は「RSSのURL」しか知らない。
そのURLがニュースサイトの公式フィードでも、RSSHubが生成したフィードでも、
AIONにとっては同じもの。だからRSSHubは「後から入れる」ではなく
**「最初から入っている」** に近い。設定値の問題でしかない。

---

### Huginn

| 項目 | 内容 |
|---|---|
| Role | Observation + 簡易オートメーション |
| Interface | Web UI中心。WebHookの送受信。外部向けRESTは限定的 |
| Deployment | Ruby on Rails + MySQL/PostgreSQL（Docker推奨） |
| Complexity | **高**（別言語ランタイム + RDBMS） |
| MVP必要性 | **不要** |
| Replacement | スケジューラ、イベントグラフ、多数のサービス連携 |

License: MIT。
機能は強力だが、AIONが欲しいのは「観測の取得」だけであり、
そのためにRails+DBを常駐させるのは指示書 §2「過剰な抽象化をしない」
「独自コード量を減らす」の趣旨に反する（AION側のコードは減らないのに
運用対象が増える）。RSS/changedetection.io で足りる。

---

### OpenHands

| 項目 | 内容 |
|---|---|
| Role | Agent Runtime（実作業） |
| Interface | `openhands-sdk`（Python: `LLM` / `Agent` / `Conversation`）、`openhands-agent-server`（REST/WebSocket）、CLI |
| Deployment | Docker Desktop/Engine、または Node.js 22.12+ と `uv`。作業用workspaceディレクトリが必要 |
| Complexity | 中〜高（Dockerランタイム、sandbox、LLM設定） |
| MVP必要性 | **不要（USE LATER）** |
| Replacement | Agentループ、ツール実行、sandbox管理 |

License: MIT。

MVPの最初のE2E（指示書 §14 のデモ例）は **調査タスク** であり、
コード実行やリポジトリ操作を必要としない。OpenHandsの主戦場は
「コーディングエージェント」であり、そこにDockerランタイムを持ち込む
必然性が今はない。

Workが「コードを書く/リポジトリを直す」に広がった時点で
`OpenHandsAdapter`（`openhands-agent-server` へのHTTPクライアント）を足す。
`AgentExecutor` プロトコルはそのために存在する。

---

### MCP (Model Context Protocol)

| 項目 | 内容 |
|---|---|
| Role | Tool Integration |
| Interface | stdio / Streamable HTTP。Python実装は `mcp` パッケージ |
| Deployment | サーバプロセス（stdio subprocess or HTTP） |
| Complexity | 小〜中 |
| MVP必要性 | **不要（USE LATER）** |
| Replacement | 独自Tool Protocol |

MVPで独自Tool Protocolを作らない、という原則はすでに満たされている。
理由: 採用したAgent Runtime（Claude Agent SDK）が **MCPをネイティブに話す**。
つまりAIONにツールを足すのは「AIONにコードを足す」ことではなく
「Agentの設定にMCPサーバを1行足す」ことになる。

AION本体にMCPクライアントを実装する必要は今のところ無い。

---

### Semantica

| 項目 | 内容 |
|---|---|
| Role | Knowledge（Knowledge Graph / セマンティックレイヤ） |
| Interface | Pythonフレームワーク（リポジトリにより異なる） |
| Deployment | ライブラリ |
| Complexity | 中〜高 |
| MVP必要性 | **不要** |
| Replacement | オントロジー、グラフ推論、provenance |

注意: 「Semantica」も **同名プロジェクトが複数存在** する
（`semantica-agi/semantica`, `BitDanceLabels/semantica-layer`,
`Hawksight-AI/semantica` 等）。どれも比較的新しく、成熟度・後方互換性が読めない。

指示書 §4 の通り「MVPではSQLiteで十分なら無理に導入しない」。
World Stateは今のところ key → JSON の集合で足りており、
グラフ問い合わせを必要とする要件がまだ存在しない。
**必要性が実証されてから** 接続する。

---

### Temporal

| 項目 | 内容 |
|---|---|
| Role | Durable Workflow |
| Interface | Python SDK（`temporalio`, asyncioネイティブ） |
| Deployment | Temporal Server（別プロセス/クラスタ） + Worker |
| Complexity | 高 |
| MVP必要性 | **不要（指示書 §4 で明示的に除外）** |
| Replacement | リトライ、再開、耐障害性、履歴 |

将来、Workが「数時間〜数日かかる」「途中でプロセスが落ちても再開したい」
段階に来たら検討する。MVPの `while True` は1周が数十秒で終わる。

---

### NATS JetStream

| 項目 | 内容 |
|---|---|
| Role | Event Bus / 永続ストリーム |
| Interface | `nats-py`（asyncio） |
| Deployment | nats-server（別プロセス） |
| Complexity | 中 |
| MVP必要性 | **不要（指示書 §4 で明示的に除外）** |
| Replacement | プロセス間のイベント配送、再生、at-least-once |

AIONが単一プロセスである限り、関数呼び出しがEvent Busである。
複数プロセスに割れた時が導入時期。

---

## MVP構成の決定

指示書 §6 の推奨初期構成:

```
External Source + LLM + Agent + SQLite + AION Core
```

に対する具体化:

```
RSS/Atom (feedparser)          ← External Source
Anthropic Messages API          ← LLM (Structured Outputs)
Claude Agent SDK                ← Agent
SQLite (stdlib)                 ← World State
AION Core                       ← Control Loop（ここだけが自作）
```

常駐サービス: **ゼロ**。Docker: **不要**。

AIONが自作したものは Control Loop だけであり、
Web crawler / Agent Runtime / Workflow Engine / Event Bus / Knowledge Graph /
Tool Protocol は **一つも実装していない**。
