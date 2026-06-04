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

## 参考

- 個人設定テンプレ: [`shared/baby.example.js`](shared/baby.example.js)
- 共通エンジンの `__NAME__` 展開ロジック: [`shared/ehon.js`](shared/ehon.js)
