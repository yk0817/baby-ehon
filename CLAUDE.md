# baby-ehon — Claude Code 運用ルール

このリポジトリは **公開リポジトリ** （`yk0817/baby-ehon`）。Claude Code はこのプロジェクトで編集を行う際、以下のルールを厳守すること。

## プライバシー方針（最重要）

### コミット禁止情報

以下の情報は **絶対にリポジトリへコミットしない**（README、コード、コミットメッセージ、Issue/PR 本文、ファイル名すべて含む）:

- **家族の本名・愛称・あだ名**（例: 子どもの名前、配偶者の名前など）
- **顔写真・自宅住所・電話番号・メールアドレス**
- **保育園／学校名・通園経路・生活パターン**
- **GPS 座標を含む画像メタデータ**
- **その他、個人を特定しうる情報全般**

### 個人名は `__NAME__` プレースホルダで扱う

絵本中の呼びかけ文・タイトル・ボタンラベルなど、お子さんの名前が入る箇所は **必ず `__NAME__`** で書く。

- `index.html` / 各 `<book>/index.html` の静的テキスト → `__NAME__、おはよう` のように書く
- 各 `<book>/config.js` の `talks` 配列 → `'__NAME__、\nしゅっぱつ だよ！'` のように書く
- 実行時に `shared/ehon.js`（および本棚 `index.html` の inline スクリプト）が `window.BABY.name + window.BABY.honorific` に置換する

### 個人名は `shared/baby.js` から読む（gitignore 対象）

実際の名前は `shared/baby.js` に書く。**このファイルは `.gitignore` で除外済み**で、リポジトリには含めない。

```js
// shared/baby.js（ローカル限定、コミット禁止）
window.BABY = {
  name: 'はな',
  honorific: 'ちゃん',
};
```

テンプレ `shared/baby.example.js` はコミット済み。デフォルト値は `あかちゃん`。

### Claude 自身への徹底事項

- **新しい呼びかけ文を書くとき**: ハードコードで具体名を入れない。必ず `__NAME__` を使う
- **README / CHANGELOG / コミットメッセージ / PR 本文を書くとき**: 子どもの個人名・愛称を一切登場させない。一般名詞（「お子さん」「対象児」「ユーザー」）で書く
- **既存ファイルに個人名が混入しているのを見つけたら**: 即座にユーザーに報告し、`__NAME__` への置換と `shared/baby.js` への移設を提案する
- **コミット前に確認**: `git diff` を見て、人名（過去登場したものを含む）が紛れ込んでいないか必ずチェック
- **画像や音声ファイルを追加する場合**: 顔・声・自宅環境が映り込んでいないか確認し、不安があればコミットしない

### 検査用クイックコマンド

コミット直前に走らせる:

検査対象の個人名は **このファイルにハードコードしない**（公開リポジトリに実名を残さないため）。gitignore 済みのローカルソースから組み立てる:

- `shared/baby.js` の `name`（gitignore 済み）
- 任意で `.privacy-denylist`（1 行 1 パターン、gitignore 済み。配偶者名・あだ名などを追記）

```bash
# 個人名パターンをローカル限定ファイルから組み立てる（リポジトリには残さない）
NAMES=$(
  { sed -n "s/.*name: *'\([^']*\)'.*/\1/p" shared/baby.js 2>/dev/null
    cat .privacy-denylist 2>/dev/null
  } | grep -v '^$' | sort -u | paste -sd '|' -
)

if [ -z "$NAMES" ]; then
  echo "WARN: ローカル個人名 denylist が空（shared/baby.js を用意すると検査が有効化）"
else
  # ステージ済み差分に個人名らしき文字列が混じっていないか
  git diff --cached | grep -E "$NAMES" && echo "STOP: 個人名検出" || echo "OK"
  # トラッキング対象ファイル全体（履歴ではなく現在の状態）に個人名がないか
  git ls-files | xargs grep -lE "$NAMES" 2>/dev/null
fi
```

ヒットが出たら **コミットせず**、`__NAME__` プレースホルダ＋ `shared/baby.js` への移設に書き換える。

## 編集スタイル

- HTML/CSS/JS のみ。ビルドツール・パッケージマネージャは導入しない
- ファイル構成は README の「構成」セクションを正とする
- 新規ブック追加時は README のラインナップ表とディレクトリ構成も更新する
- `.claude/settings.json` の PostToolUse hook が、コード編集時に README 更新の要否をリマインドする

## コミットメッセージ

- 日本語、Conventional Commits 形式（`feat:`, `fix:`, `refactor:`, `docs:`, `chore:` など）
- 個人名は書かない

## Git 操作

- `git push` 前には必ずユーザーの許可を求める（グローバルルールと同じ）
- 公開リポジトリなので、push は事実上の世界公開と同義。**特に慎重に**
- `main` はブランチ保護下（PR 必須・直 push 不可・force push/削除禁止・enforce_admins）。変更は必ず **ブランチ → PR → 人間が merge**。承認は実質オーナー1人

## 自動化パイプライン（Issue → PR → 人間 merge）

設計の正は [`docs/automation/agent-pipeline.md`](docs/automation/agent-pipeline.md)。3 エージェント役（リサーチャー / 作成者 / こども）＋人間ゲートで回す。**人間ゲートは二段**: 入口（Issue に `approved`）と出口（PR を merge）。

ラベル運用（Issue を扱うときに必ず意識する）:

| ラベル | 誰が | 意味 |
|---|---|---|
| `approved` | **人間** | 実装してよいの承認。**作成者は `approved` 付きだけ実装**（入口ゲート） |
| `stage:researched` | リサーチャー① | 調査・採点済み（`claude-score` 付与） |
| `stage:implemented` | 作成者 | Draft PR 化済み |
| `stage:child-reviewed` | こども | 所見済み（Approve はしない） |
| `claude-proposed` | Proposer | 自動起票 Issue |
| `automation:skip` | 人間 | 自動処理の対象外にする |

- **3 つの `stage:*` が揃うと Issue は自動クローズ**（§2.1）。人間 merge の `Closes #N` とも冪等に共存
- 実装タスクは milestone「Phase 1〜6」と `automation` ラベルで管理（#10〜#24）
- **Issue 本文を書くときも `__NAME__` 以外に人名を入れない**。テンプレ `.github/ISSUE_TEMPLATE/` に注意書きあり

## Issue 着手ルール（厳守・例外なし）

このリポジトリの Issue を **Claude が実装するとき**は、着手前に必ず次を満たす。パイプラインの作成者と同じ入口ゲートを Claude 自身にも適用する。

1. **approved 必須（入口ゲート）**: 対象 Issue に **`approved` ラベルが付いているかを着手前に確認する**（`gh issue view <N> --json labels`）。
   - 付いていなければ **実装に着手しない・ブランチも切らない**。人間に「`approved` を付けてほしい」と依頼して**停止**する
   - 自分で `approved` を貼らない（承認は人間の専権）
2. **1 Issue = 1 ブランチ = 1 PR**: 複数 Issue を 1 つのブランチ／PR に**束ねない**。ブランチ名は `claude/issue-<N>`
3. **PR 本文に `Closes #N`** を必ず入れ、その Issue だけを閉じる
4. **PR の作成・マージは人間が行う**（`gh pr create` / `gh pr merge` は deny）。Claude はブランチ push までで止め、PR 作成を人間に依頼する
5. 着手前に対象言語のルール（`~/.claude/docs/lang-rules/<lang>/`）を Read し、TDD（テスト先行）で進める

## 参考

- 個人設定テンプレ: [`shared/baby.example.js`](shared/baby.example.js)
- 共通エンジンの `__NAME__` 展開ロジック: [`shared/ehon.js`](shared/ehon.js)
