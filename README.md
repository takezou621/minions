# 🧞 minions — 個人用ワンショット・コーディングエージェント環境

日本語 | **[English](README.en.md)**

[Stripe の Minions ブログ](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
([Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)) を参考に、
**goose** をコアにした個人開発向けの「無人・ワンショット」コーディングエージェント基盤です。

タスクを渡すと **worktree で隔離 → goose が実装 → lint/テスト自動修正 → commit → push → CI(最大2周) → PR作成**
まで、人の介入なしで完走します。

## 🤖 minions とは？ — 初めての方へ

### 一言でいうと

**minions は「タスクを投げたら PR ができるまで勝手に進める、個人用 AI コーディング部下」です。**

```bash
minion run "ログインAPIにレートリミットを追加してテストも書いて"
```

この 1 コマンドで、minions が次をすべて**無人**で実行します:

1. 元リポジトリを汚さない**隔離作業場 (git worktree)** を自動作成
2. AI エージェント (goose) がルールファイルを読んでコードを実装
3. lint 自動修正・テスト実行、失敗すれば AI が原因を調べて自己修正
4. commit → push → CI (最大2周、失敗しても AI が修正して再挑戦) → **PR 自動作成**

人間がやるのは最後の **PR レビューだけ**。「実装を投げて、出来上がった PR だけ見る」ワークフローを実現します。

### なぜ作ったのか (解決する課題)

AI コーディングエージェントをそのまま使うと、次のような課題にぶつかります。

| 課題 | minions の答え |
|---|---|
| エージェントが作業中のブランチを汚す | **1タスク = 1 worktree** で完全隔離。複数タスクの並列実行も安全 |
| 途中で質問されて止まる | 無人前提の one-shot 設計。質問禁止の指示を与えて最後まで走り切る |
| lint / テスト / CI のたびに人間が直す | 決定論ノードが自動修正し、失敗ログを食わせて AI が自己修復 |
| git 操作を LLM に任せると事故る | commit / push / PR は **LLM を使わない決定的コード**が担当 |
| ツールごとにルールファイルがバラバラ | `AGENTS.md` 1つを goose / Claude Code / Cursor で共有 |

設計思想は [Stripe の Minions](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents) の
**「決定できることはコードで決定的に、創造性が必要なことだけエージェントに」** を、個人開発規模に縮小移植したものです。

### できること / 想定していないこと

- ✅ 明確に指示できるタスク (機能追加・リファクタ・バグ修正・テスト追加) を投げて PR まで受け取る
- ✅ 複数タスクを並列実行して自分はレビューに専念する
- ❌ 対話しながら進めるペアプロ (無人前提のため質問には答えられません)
- ❌ git 操作の代理人 (エージェントへの commit/push は禁止し、オーケストレータが決定的に実行します)

### 主要コンセプト (用語集)

| 用語 | 意味 |
|---|---|
| **minion** | 1つのタスクを遂行するワンショットエージェントの実行 1 回分。`minion run` ごとに 1 体起動する |
| **minions** | 本リポジトリ / ツールの名前。minion の起動・隔離・監視 (Blueprint) を担う基盤 |
| **one-shot (ワンショット)** | 人の介入なしに、タスク開始から完了まで一度きりで走り切ること |
| **worktree** | git の機能で作る「同じリポジトリの独立した作業場」。1タスク=1worktree で他の作業と干渉しない |
| **Blueprint** | タスク遂行の状態機械。「決定論ノード」と「AGENT ノード」を組み合わせた処理の流れ全体 |
| **決定論ノード** | LLM を使わず必ず同じ挙動をする処理 (worktree 作成・lint・commit・push・PR) |
| **AGENT ノード** | goose に裁量を与える処理 (実装、テスト/CI 失敗の原因追究と修正) |
| **run** | minion の 1 実行単位。`~/.minion/runs/<run_id>/` にログ・状態・成果物が残る |
| **AGENTS.md** | エージェントが従うべきプロジェクト規約ファイル。`minion init` で生成 |
| **`.minion.yaml`** | 対象リポジトリごとの設定 (lint/test/CI コマンド、PR ベースなど) |

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

### なぜ goose を fork しないのか (Stripe との最大の相違点)

Stripe は 2024 年末に goose を内部 fork し、エージェントループ自体に手を入れています
(社内 LLM インフラへの統合、権限プロンプト除去による無人実行、ループと決定論コードの交互実行)。
本プロジェクトは意図的に **fork せず、goose を CLI 経由でサブプロセス呼び出し** します:

| Stripe が fork で実現したこと | 個人版での実現手段 |
|---|---|
| 社内 LLM インフラへの統合 | goose の provider 設定 (ローカルで完結) |
| 無人実行 (対話プロンプト除去) | `goose run --no-session` + `GOOSE_MODE=auto` |
| ループと決定論コードの交互実行 | **Blueprint を goose の外 (Python) に置き**、AGENT ノードだけ `goose run` を呼ぶ |
| Toolshed (社内キュレーションツール) | goose の MCP 機能 + `.minion.yaml` の `goose_args` |
| devbox (隔離・並列環境) | git worktree (Stripe は「worktree は Stripe 規模ではスケールしない」と明言 — 個人規模なら十分) |

Stripe は「エージェントランタイムの中にオーケストレーションを入れる」構造ですが、
本プロジェクトは「オーケストレーションの中にエージェントを使う」構造です。エージェントコアを
変更せずに状態機械側を自由に進化させられ、goose のリリース・拡張機能 (MCP, レシピ) を
そのまま追従できるのが利点です。

fork は upstream 追従・セキュリティパッチ・ビルド配布の恒常コストを伴い、
**エージェントループ自体を変えたいときだけ**正当化されます。必要な拡張は
`CLI フラグ → MCP/レシピ → 上流への PR` の順で解決し、fork は最終手段と位置づけています。

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

## セットアップ

前提: [goose](https://github.com/block/goose) / git / python3 (3.9+)。PR自動作成には [gh](https://cli.github.com/) (要 `gh auth login`、任意)。

```bash
git clone https://github.com/takezou621/minions.git
mkdir -p ~/.local/bin
ln -sf "$(pwd)/minions/bin/minion" ~/.local/bin/minion
export PATH="$HOME/.local/bin:$PATH"   # 常用するなら ~/.zshrc などに追記
minion doctor   # 依存とPATHを確認
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
minion clean               # 完了/失敗runのworktreeを掃除
```

### 4. PR

リモートが GitHub なら `gh pr create` まで自動 (ベースは `.minion.yaml` の `pr_base`)。
PR本文はエージェントが書いた `summary.md` (なければ最終コミットのログ) が使われます。人間はレビューだけ。

## `.minion.yaml` リファレンス

```yaml
lint:
  fix: ["ruff check --fix .", "ruff format ."]  # 決定論ノードで実行する自動修正
  check: ["ruff check ."]                        # 検査のみ
test: "python3 -m pytest -q"                     # ローカルテスト
ci: "python3 -m pytest -q"                       # CI相当のローカル実行 (未設定なら test、ci/test両方未設定なら GitHub Actions を監視)
pr_base: "main"                                  # PRベースブランチ
goose_args: ["--with-builtin", "developer"]      # gooseへ追加引数 (MIPMツールの「小さい箱」化)
```

## ルールファイル (Stripe の文脈エンジニアリング)

- ルートの `AGENTS.md` は**無条件**に読まれる → 最小限に
- 詳細な規約は **サブディレクトリ直下の `AGENTS.md`** に置く (`services/api/AGENTS.md` 等)
  → hydrate ノードが収集し (`.cursorrules` も収集)、実装プロンプトに「READ FIRST」として渡す
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
リポジトリルート (clone先)/
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

## ユースケース早見表

README 記載の機能から導かれる想定ユースケースの一覧。

| カテゴリ | ユースケース | キー (コマンド/設定) |
|---|---|---|
| **タスク実行** | 機能追加+テストをワンショット完走 | `minion run "タスク"` → PR まで無人 |
| | リファクタ / バグ修正 / テスト追加を同様に完走 | 同上 (タスク文を変えるだけ) |
| | 自己修復: lint は ≤3 周自動修正、test/CI 失敗は agent が失敗ログを読み ≤2 回修復 | Blueprint 周回上限 |
| **実行形態** | フォアグラウンド実行、終了コードで成否判定 | `minion run` (exit 0/1) |
| | 並列実行 — 自分はレビューに専念 | `minion run -d "タスク" &` × N (1タスク=1worktree) |
| | 複数リポジトリで運用 | 対象 repo ごとに `minion init` |
| **監視・確認** | 進行中/事後の状況把握 | `minion list` / `log -f` / `show <run_id>` |
| | Web UI で並列 run を監視 | `minion dashboard` (:8765, 5秒自動更新) |
| | 成果物の監査・参照 | `~/.minion/runs/<id>/` の `summary.md` / `changes.patch` / `transcript.log` |
| **PR 受け取り** | agent 作成の要約を PR 本文として受け取る | `summary.md` → `gh pr create` 本文 |
| | PR ベースブランチの出し分け | `.minion.yaml` の `pr_base` |
| **環境バリエーション** | `gh` 未導入 / origin が GitHub 以外 → push まで自動、PR はスキップ | gh は任意 |
| | origin なし → ローカル完結 | state `done_local` |
| **失敗時** | 修復不能な test/CI 失敗 → run 失敗終了、ログで人間が原因特定 | fix ≤2 回 / CI ≤2 周 |
| | 実装 agent の失敗 → transcript を確認しタスク文を改善して再投下 | `minion log` |
| **設定・ルール** | 言語別に lint/test を自動検出して雛形生成 | `minion init` (pyproject / package.json / Cargo.toml / go.mod / Makefile) |
| | 段階的導入 — lint/test 未設定ならそのノードをスキップ | `.minion.yaml` 未設定時の挙動 |
| | エージェントへのツール供給を最小化 / 拡張 | `goose_args` (小さい箱化) / `goose configure` (MCP) |
| | サブディレクトリ規約を実装プロンプトに注入 | サブ `AGENTS.md` / `.cursorrules` → hydrate 収集 |
| | マルチツール間で規約を共有 | `CLAUDE.md` symlink |
| **管理・保守** | 依存・provider の診断 | `minion doctor` |
| | 完了/失敗 run の worktree 掃除 | `minion clean` |

対象外 (アンチユースケース): 対話しながらのペアプロ、git 操作の代理人 (agent の commit/push は禁止し、オーケストレータが決定的に実行)。

## 参考

- [Minions: Stripe's one-shot, end-to-end coding agents — Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Part 2 (Blueprint, Devbox, Toolshed, CI 2周ポリシー)](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- [goose (Block)](https://github.com/block/goose) — Stripe もフォーク元として使用
