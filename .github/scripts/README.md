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
- リポジトリ Secrets / Variables（**人間が登録**。Claude は触れません。詳細は下表）
  - Secrets: `OPENAI_API_KEY` / `BABY_EHON_NAME_DENYLIST`
  - Variables: `LLM_MODEL_DAILY/PROPOSER/CREATOR/CHILD`（**必須**・既定なし）, `OPENAI_BASE_URL`（実質必須）, `PROPOSED_BACKLOG_MAX`（任意）
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

## Secrets / Variables の登録（人間が行う）

公開リポジトリなので、**個人名や API キーは必ず Secret に入れ、値はコミットしない**（§8 / CLAUDE.md）。
GitHub の **Settings → Secrets and variables → Actions** で登録します。Claude は触れません。

### Secrets（暗号化・ログに出ない）

| 名前 | 必須 | 内容 |
|---|---|---|
| `OPENAI_API_KEY` | 必須 | LLM 呼び出し用 API キー。利用する OpenAI（互換）提供元から発行 |
| `BABY_EHON_NAME_DENYLIST` | 必須 | 検査で弾く家族名のカンマ区切り。**公開リポなので必ず Secret**。値はコード・ログに残さない（ワークフローが起動時に `::add-mask::` でログマスク、§8.3） |

### Variables（平文・機密ではない設定）

役ごとのモデルは `common/llm.py` が **env から必須解決**します（コードに既定モデル名を持ちません＝未設定だと実行時エラー）。そのため `LLM_MODEL_*` は実運用では**必須**です。

| 名前 | 必須 | 内容 |
|---|---|---|
| `LLM_MODEL_DAILY` | **必須** | Daily（調査・採点）のモデル。例 `gpt-4o-mini`（軽量ティア、§4.5） |
| `LLM_MODEL_PROPOSER` | **必須** | Proposer（発案）のモデル。例 `gpt-4o-mini` |
| `LLM_MODEL_CREATOR` | **必須** | Weekly（コード生成）のモデル。例 `gpt-5`（コードは上位ティア推奨。`gpt-5.x-codex` 系も可） |
| `LLM_MODEL_CHILD` | **必須** | こども（**Vision 必須**）のモデル。例 `gpt-4o-mini` |
| `OPENAI_BASE_URL` | 実質必須 | OpenAI SDK の base_url。実 OpenAI なら `https://api.openai.com/v1`。**未設定（空文字）だと SDK が空 URL を読んで `UnsupportedProtocol` で失敗するため、必ず設定する** |
| `PROPOSED_BACKLOG_MAX` | 任意 | 未対応 `claude-proposed` の上限。未設定なら既定 `3` |

> モデル名は使うエンドポイント次第です（実 OpenAI なら `gpt-4o-mini` / `gpt-5` 等、Anthropic 互換プロキシなら `claude-haiku-4-5` / `claude-sonnet-4-6` 等を `OPENAI_BASE_URL` とセットで指定）。

### `gh secret` / `gh variable` での登録例

```bash
# Secrets（値は対話入力で貼る。履歴に残さない。op から取るなら `op read ... | gh secret set NAME`）
gh secret set OPENAI_API_KEY --repo yk0817/baby-ehon
gh secret set BABY_EHON_NAME_DENYLIST --repo yk0817/baby-ehon   # 家族名をカンマ区切りで対話入力

# Variables（モデル名・base_url は機密でないので値ごと指定でよい）
gh variable set OPENAI_BASE_URL    --repo yk0817/baby-ehon --body 'https://api.openai.com/v1'
gh variable set LLM_MODEL_DAILY    --repo yk0817/baby-ehon --body 'gpt-4o-mini'
gh variable set LLM_MODEL_PROPOSER --repo yk0817/baby-ehon --body 'gpt-4o-mini'
gh variable set LLM_MODEL_CREATOR  --repo yk0817/baby-ehon --body 'gpt-5'
gh variable set LLM_MODEL_CHILD    --repo yk0817/baby-ehon --body 'gpt-4o-mini'
```

> `BABY_EHON_NAME_DENYLIST` は `gh secret set <名前>` を引数なしで実行すると値を対話入力でき、シェル履歴に残りません（公開リポジトリには値を一切コミットしない）。

## ラベル初期化（冪等）

パイプラインが使うラベル一式（`approved` / `stage:researched` / `stage:implemented` / `stage:child-reviewed` / `claude-proposed` / `needs-child-review` / `automation:skip` / `score-lock`）を、リポジトリに過不足なく揃えます。既存ラベルは色・説明を更新し、未作成なら作成します（**二重作成しません**）。初回セットアップで 1 回流せば十分です。

```bash
cd .github/scripts

# 何もせず、対象ラベル一覧を表示するだけ（GITHUB 系未設定でも落ちません）
DRY_RUN=true python setup_labels.py

# 実際に作成 / 更新する（gh ログイン済みのリポジトリに対して）
GITHUB_REPOSITORY=yk0817/baby-ehon python setup_labels.py
```

`gh label create --force` を使うため、何度実行しても安全です（無ければ作成・有れば更新）。出力はラベル名・色・説明のみで、個人名やトークン値は出しません。

## コミット / 起票の名義

- **Weekly が作る差分コミット**は、ワークフローの git identity 設定によりオーナー（`yk0817` + GitHub noreply メール）名義になります。contribution graph にも本人として乗ります
- **Issue 起票・PR/Issue コメント・PR 作成者**は `GITHUB_TOKEN` 経由のため `github-actions[bot]` 名義です。これらも本人名義にしたい場合は、`yk0817` の **PAT** を Secret 登録し各ワークフローで使う必要があります（既定では未使用）

## Daily ワークフローの回し方（dispatch）

Daily は `.github/workflows/daily-issue-investigation.yml` で動きます。現フェーズ（P2）は
`workflow_dispatch` のみ有効で、cron はコメントアウト済み（P6 で有効化）。

```bash
# 投稿なしの dry-run（推奨。Issue #1 だけを対象にする例）
gh workflow run daily-issue-investigation.yml \
  --repo yk0817/baby-ehon \
  -f dry_run=true \
  -f only_issue=1
```

GitHub UI からは Actions → "Daily Issue Investigation (リサーチャー①)" → Run workflow で、
`dry_run` / `only_issue` を指定して起動できます。実投稿は `dry_run=false` にしますが、
**まず dry-run と下記ローカル再現で内容を確認**してから行ってください。

### ローカルでの再現（§11 step1）

CI と同じことを手元で確認できます（投稿なし）。

```bash
cd .github/scripts
DRY_RUN=true ONLY_ISSUE=1 uv run python -m daily_investigator.run
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
