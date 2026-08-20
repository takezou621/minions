# 🧞 minions — 個人用ワンショット・コーディングエージェント環境

[Stripe の Minions ブログ](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
([Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)) を参考に、
**goose** をコアにした個人開発向けの「無人・ワンショット」コーディングエージェント基盤です。

タスクを渡すと **worktree で隔離 → goose が実装 → lint/テスト自動修正 → commit → push → CI(最大2周) → PR作成**
まで、人の介入なしで完走します。

## アーキテクチャ (Stripe Minions → 個人版の対応)

| Stripe の概念 | 本実装 (個人版) |
|---|---|
| Minion (無人ワンショットエージェント) | `minion run "タスク"` |
| goose のフォーク (エージェントコア) | **goose 1.46 そのもの** (`goose run --no-session`) |
| Blueprint (決定論ノード+エージェントノードの状態機械) | `lib/minions/blueprint.py` のステートマシン |
| Devbox (隔離・並列実行環境) | **git worktree** (`~/.minion/worktrees/`) |
| エージェントルールファイル (Cursor/CLAUDE.md 共有) | `AGENTS.md` + `CLAUDE.md` シンボリックリンク (`minion init`) |
| サブディレクトリスコープの条件付きルール | サブディレクトリ配下の `AGENTS.md` を hydrate ノードが収集 |
| Toolshed (中央MCP・キュレーション済みツール) | goose の MCP 設定 + `.minion.yaml` の `goose_args` |
| フィードバックの左シフト (ローカルlint → CI最大2周) | lint 自動修正 ≤3周 → テスト → agent修正 ≤2回 → CI ≤2周 |

## Blueprint (状態機械)

```
setup ── hydrate ──▶ implement ──▶ lint(自動修正≤3周) ──▶ test ──┐
(決定)   (決定)      (AGENT)        (決定)              (決定)   │ 失敗
                                                                    ▼
done ◀─ pr ◀─ ci(≤2周) ◀─ push ◀─ commit ◀── test通過 ◀── fix_tests (AGENT)
        (決定)  ▲                                    (決定)              │失敗
                │              fix_ci (AGENT) ◀──── ci失敗 ◀────────────┘
```

- **AGENT ノード**: goose に大きな裁量を与える (実装・失敗修正)
- **決定論ノード**: git 操作・lint・テスト・push・PR は LLM を使わず必ず実行される
  → Stripe の教訓「決定できる小さな判断はコードで決定的に。トークンとCIを節約し、
  エージェントが間違う余地を減らす」

## セットアップ (このPCでは完了済み)

```bash
# 依存: goose, git, gh(任意), python3 — `minion doctor` で確認
ln -sf ~/dev/minions/bin/minion ~/.local/bin/minion   # PATH 通し済み
```

## 使い方

### 1. 対象リポジトリを初期化 (一度だけ)

```bash
cd ~/dev/your-repo
minion init
# → AGENTS.md (ルールファイル), CLAUDE.md (symlink), .minion.yaml (自動検出) を生成
#   AGENTS.md に規約を書き、必ず commit すること (worktree は HEAD から作られるため)
```

### 2. ワンショット実行

```bash
minion run "ログインAPIにレートリミットを追加してテストも書いて"
# 並列化 (Stripe 流: 複数 minion を同時に)
minion run -d "タスクA" &
minion run -d "タスクB" &
minion list
```

### 3. 見守る・確認する

```bash
minion list                # 一覧
minion log -f              # 直近runのtranscriptをtail
minion show <run_id>       # タイムライン + 状態
minion dashboard           # → http://localhost:8765 (Web UI, 5秒自動更新)
minion clean               # 完了runのworktreeを掃除
```

### 4. PR

リモートが GitHub なら `gh pr create` まで自動 (ベースは `.minion.yaml` の `pr_base`)。
PR本文はエージェントが書いた `summary.md` が使われます。人間はレビューだけ。

## `.minion.yaml` リファレンス

```yaml
lint:
  fix: ["ruff check --fix .", "ruff format ."]  # 決定論ノードで実行する自動修正
  check: ["ruff check ."]                        # 検査のみ
test: "python3 -m pytest -q"                     # ローカルテスト
ci: "python3 -m pytest -q"                       # CI相当 (未設定なら test を流用)
pr_base: "main"                                  # PRベースブランチ
goose_args: ["--with-builtin", "developer"]      # gooseへ追加引数 (MIPMツールの「小さい箱」化)
```

## ルールファイル (Stripe の文脈エンジニアリング)

- ルートの `AGENTS.md` は**無条件**に読まれる → 最小限に
- 詳細な規約は **サブディレクトリ直下の `AGENTS.md`** に置く (`services/api/AGENTS.md` 等)
  → hydrate ノードが収集し、実装プロンプトに「READ FIRST」として渡す
- `CLAUDE.md` は symlink なので、goose / Claude Code / (syncすれば)Cursor で**同一のルール**を共有

## MCP (Toolshed 相当)

goose の MCP 機能をそのまま利用:

```bash
goose configure   # MCPサーバ追加 (GitHub, Linear, Notion 等)
```

`.minion.yaml` の `goose_args` で run 単位のツール制限も可能
(Stripe の教訓: 「エージェントはキュレーションされた小さな道具箱で最も良く動く」)。

## ディレクトリ構成

```
~/dev/minions/
├── bin/minion              # CLIエントリ
├── lib/minions/
│   ├── core.py             # run状態・設定検出・gitヘルパー
│   ├── blueprint.py        # 状態機械 (決定論/AGENTノード)
│   ├── cli.py              # init/run/list/log/show/clean/doctor
│   └── dashboard.py        # ローカルWeb UI
├── templates/AGENTS.md     # ルールファイルテンプレート
└── README.md
~/.minion/
├── runs/<run_id>/          # status.json, transcript.log, summary.md, changes.patch
└── worktrees/<repo>-<id>/  # 隔離された作業場 (1タスク=1worktree)
```

## 参考

- [Minions: Stripe's one-shot, end-to-end coding agents — Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Part 2 (Blueprint, Devbox, Toolshed, CI 2周ポリシー)](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- [goose (Block)](https://github.com/block/goose) — Stripe もフォーク元として使用
