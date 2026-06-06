# baby-ehon 自動化パイプライン — オペレータ向け README

このディレクトリ（`.github/scripts/`）は、絵本リポジトリの **research-based な改善を自動で回すパイプライン**の実装を置く場所です。役割・全体設計は [`docs/automation/agent-pipeline.md`](../../docs/automation/agent-pipeline.md) を正とします。

> ⚠️ ここは **CI 専用の Python コード**です。絵本本体（`hikouki/` などの HTML/CSS/JS）とは無関係で、絵本の配信には一切影響しません。

## 役の構成

| 役 | パッケージ | 役割 | 起動 |
|---|---|---|---|
| リサーチャー① | `daily_investigator/` | 既存 Issue を 2 日に 1 回 調査・採点 | cron 隔日 / dispatch |
| リサーチャー② | `issue_proposer/` | 週次で新しい絵本/機能を発案・起票 | cron 金曜 / dispatch |
| 作成者 | `weekly_implementer/` | `approved` 付き最高スコア Issue を実装・Draft PR | cron 月曜 / dispatch |
| こども | `child_reviewer/` | Draft PR を実ブラウザで触って所見 | PR 連鎖 / dispatch |
| 共通基盤 | `common/` | privacy / llm / prompts / IO | — |
| プロンプト | `prompts/<role>/` | system / persona / rubric（外部化） | — |

各役は独立した GitHub Actions ワークフローで、受け渡しは Issue / PR / コメントマーカーで行います（共有 DB なし）。

## 前提

- **uv**（Python パッケージマネージャ）。導入は [astral.sh/uv](https://docs.astral.sh/uv/)
- リポジトリ Secrets（**人間が登録**。Claude は触れません）
  - `OPENAI_API_KEY` — LLM 呼び出し用の API キー
  - `OPENAI_BASE_URL` —（任意）OpenAI 互換でないエンドポイントを使う場合の base_url（§3.1）
  - `BABY_EHON_NAME_DENYLIST` — 検査で弾く個人名のカンマ区切り（**値はコード・ログに残さない**）
- ラベル: `approved` / `stage:researched` / `stage:implemented` / `stage:child-reviewed` / `claude-proposed` / `needs-child-review` / `automation:skip` / `score-lock`

## セットアップ（ローカル）

```bash
cd .github/scripts

# 実行時 + 開発（pytest 等）依存をまとめて入れる
uv venv
uv pip install -r requirements-dev.txt

# こどもレビュワーをローカルで動かす場合のみ（ブラウザ取得）
uv run playwright install --with-deps chromium
```

## ローカル dry-run（API 書き込みなし）

各役は `DRY_RUN=true` で「生成は行うが GitHub への投稿はしない」モードになります（実装は各 Phase で追加）。

```bash
# リサーチャー①（Issue #1 だけ・投稿なし）
DRY_RUN=true ONLY_ISSUE=1 uv run python -m daily_investigator.run

# リサーチャー②（起票なし・ゲート判定を確認）
DRY_RUN=true uv run python -m issue_proposer.run

# こども（既存 PR に対して投稿なしでスクショ+所見）
DRY_RUN=true PR_NUMBER=<既存PR番号> uv run python -m child_reviewer.run
```

## テスト

```bash
cd .github/scripts
uv run pytest -q                       # 全テスト
uv run pytest --cov=common --cov-report=term-missing
```

## プライバシー（最重要）

公開リポジトリです。詳細はリポジトリ直下の [`CLAUDE.md`](../../CLAUDE.md) と設計書 §8。

- 生成テキストに **本名・愛称・住所・電話・メール・保育園名**を残さない。呼びかけは `__NAME__`
- 全役は GitHub への書き込み直前に `common/privacy.py`（#11）を通す（denylist + `__NAME__` assert）
- denylist 値は Secret 管理。ログには `::add-mask::` でマスク
- こどもレビュワーは実 `shared/baby.js` を CI に持ち込まず、`baby.example.js` の既定名（`あかちゃん`）で配信する

## 実装ロードマップ

Phase 1（共通基盤）→ 2（Daily）→ 3（Proposer）→ 4（Weekly）→ 5（こども）→ 6（統合・cron 有効化）。
各 Phase の Issue は milestone「Phase 1〜6」と `automation` ラベルで管理（#10〜#24）。
