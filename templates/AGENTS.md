# Minions — Project Rules for AI Agents

このファイルは **全エージェント共通のルールファイル** です。
goose / Claude Code (CLAUDE.md 経由) / Cursor などが読み込みます。

## プロジェクト概要

(ここにプロジェクトの目的・アーキテクチャ・主要モジュールを1〜3行で)

## コーディング規約

- (例) Python 3.12+ / type hints 必須
- (例) コミットメッセージは Conventional Commits (`feat:`, `fix:` ...)
- (例) 公開APIにはdocstringを付ける

## よく使うコマンド

- テスト: `(自動検出されたコマンド)`
- リント/整形: `(自動検出されたコマンド)`

## 注意事項

- 破壊的変更は事前にREADMEに記載する
- 秘密情報 (APIキー等) をコミットしない

---

### サブディレクトリスコープのルール (推奨)

大規模リポジトリでは、ルートに無条件で読まれる巨大なルールを置くのではなく、
対象ディレクトリ直下に `AGENTS.md` を置くと、その配下を触るときだけ
コンテキストに読み込まれます (Stripe Minions の教訓: ルールは「条件付きで適用」)。

例:
```
services/api/AGENTS.md    # APIまわりの規約
packages/ui/AGENTS.md     # UIまわりの規約
```
