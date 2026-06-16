# baby-ehon

1歳前後のお子さん向けに作った、ブラウザで動く絵本シリーズ。HTML/CSS/JS だけで作っており、ビルド不要。

## ラインナップ

| ブック | パス | シーン |
|--------|------|--------|
| 🛩️ ひこうき | [`hikouki/`](hikouki/) | りりく → くものなか → うみのうえ → よぞら → ちゃくりく |
| 🚄 でんしゃ | [`densha/`](densha/) | はっしゃ → まち → てっきょう → よるのまち → しゅうちゃくえき |
| 🚗 くるま | [`kuruma/`](kuruma/) | しゅっぱつ → まち → やまみち → よる → ゴール |
| ☀️ おてんき | [`otenki/`](otenki/) | はれ → くもり → あめ → かみなり → にじ |
| 🌙 よる の そら | [`yorunosora/`](yorunosora/) | ゆうやけ → おつきさま → ほし → ながれぼし → あさやけ |
| 🐶 どうぶつパーティー | [`doubutsu/`](doubutsu/) | いぬ → ねこ → ぶた → ぞう → みんなでパーティー |

トップの [`index.html`](index.html) は本棚（ランディング）。タップで各ブックに飛ぶ。

## 機能

すべてのブックに以下が入る:

- **ページ遷移**: タップ／スワイプ／矢印キー／自動進行（12秒）
- **オノマトペバブル**: タップで派手にポップ、シーン別に複数バリエーション
- **語りかけ吹き出し**: ページ切替時・5秒ごとに白い吹き出しで「〜〜」と呼びかけ
- **Mac カメラ ミラー窓**: 右下の円窓に自分たちの顔を表示（鏡像反転）。ページ切替で「ぴょこっ」と弾むリアクション
- **キーボード乱打リアクション**（1歳向け）: ←→ 以外のキーを押すと、ランダムな言葉/絵文字バブル＋大量のきらきら＋画面フラッシュ＋音程変化
- **音**: WebAudio API でシーン別の音階を生成
- **チャイルドロック** 🔒: 右上の鍵ボタンで施錠。施錠中はナビ（戻る／進む／ホーム）が無効化＋自動で全画面化され、お子さんが触ってもページ離脱しない。解除は鍵ボタンを **1.5秒長押し**

## セットアップ（お子さんの名前を入れる）

絵本中の呼びかけ文（吹き出し・タイトル・ボタン）はテンプレ `__NAME__` で書かれていて、ローカルの個人設定ファイルから読み込んで展開する。**この個人設定ファイル `shared/baby.js` は `.gitignore` 対象で、リポジトリには含めない**。

```bash
cp shared/baby.example.js shared/baby.js
# shared/baby.js を開いて name / honorific を編集
```

`shared/baby.js`:

```js
window.BABY = {
  name: 'はな',       // お子さんのニックネーム
  honorific: 'ちゃん', // 呼び方（'くん' / 'さん' / '' なども可）
};
```

`shared/baby.js` が存在しない場合は `あかちゃん` がデフォルトで使われる。

## 動かしかた

ブラウザの `getUserMedia` はファイルプロトコルでは動かないため、ローカルサーバー経由で開く必要がある。

```bash
python3 -m http.server 8000
```

ブラウザで `http://localhost:8000/` を開く → 本棚から好きな絵本を選ぶ。

カメラを使うときは右下の「[名前]を タップ！」ボタンをタップしてカメラを許可。大人がカメラを止めたいときは円窓をダブルクリック。

## 構成

```
baby-ehon/
├── index.html             # 本棚（ランディング）
├── shelf.css              # 本棚スタイル
├── README.md
├── CLAUDE.md              # Claude Code への運用ルール（プライバシー方針含む）
├── .gitignore             # shared/baby.js を除外
├── shared/
│   ├── ehon.css           # 共通スタイル（カメラ窓・SFX・吹き出し・ロック・ナビ等）
│   ├── ehon.js            # 共通エンジン（BOOK_CONFIG / __NAME__ 展開 / チャイルドロック）
│   ├── baby.example.js    # 個人設定のテンプレ（コミットされる）
│   └── baby.js            # 個人設定（.gitignore 対象、各自で作成）
├── hikouki/
│   ├── index.html
│   ├── theme.css          # 背景・乗り物などのテーマ
│   └── config.js          # シーン別 sfx / talks / colors / notes
├── densha/  ├── kuruma/  ├── otenki/  ├── yorunosora/  └── doubutsu/   ← それぞれ同構成
```

## 新しいブックを追加するには

1. `<name>/` ディレクトリを作る
2. `config.js` でシーンごとのオノマトペ・語りかけ・色・音階を定義（呼びかけ語は `__NAME__、〜` の形で書く）
3. `theme.css` で背景や乗り物の見た目を定義
4. `index.html` で5つの `<section class="page" data-scene="<key>">` を並べる
   - 共通の `id="fx-layer"` `id="cam-window"` `class="parent-nav"`（`lock-btn` を含む）を含める
   - スクリプト読込順: `../shared/baby.js` → `config.js` → `../shared/ehon.js`
   - 静的テキスト中の呼びかけも `__NAME__` を使う
5. ルートの `index.html` 本棚にカードを追加
6. **E2E テストに新ブックを登録する**（追加漏れ防止のため必須）
   - `e2e/pages.py` の `BOOK_SLUGS` に新ブックのディレクトリ名を追加する（本棚カード数・各ブック遷移のパラメータ化テストが自動で新ブックを対象に含める）
   - `e2e/test_navigation.py` の `EXPECTED_FIRST_SCENE` に `"<name>": "<初期シーンの data-scene>"` を追加する
   - 下記の最低限スモークが green になることを必須化する（`cd e2e && uv run python -m pytest -q`）:
     - **本棚に出る**: カードが `BOOK_SLUGS` の数だけ並び、新ブックの href がある
     - **初期表示**: 開くと初期シーンが表示され、最初のドットがアクティブ
     - **全シーン遷移**: 次へ／スワイプ／←→／自動進行で 5 シーンを巡り、末尾の次は先頭へループ
   - 詳しい実行手順は [`e2e/README.md`](e2e/README.md) を参照
7. **README.md のラインナップ表とディレクトリ構成も更新する**

## プライバシー方針

このリポジトリは公開リポジトリ。**個人名・顔写真・住所等を含む情報はリポジトリにコミットしない**。詳細は [`CLAUDE.md`](CLAUDE.md) を参照。

## 自動改善パイプライン（実験的）

絵本の改善を **AI エージェントが調査・発案 → 実装 → 1 歳児視点でレビュー**し、最後は人間が PR を merge する仕組みを GitHub Actions で回しています（公開リポなので生成物に個人情報は残しません）。

```
リサーチ（調査・発案）→ 作成（Draft PR）→ こども（所見）→ 人間が承認・merge
```

| 役 | すること |
|---|---|
| リサーチャー① Daily | 既存 Issue を調査・採点（`claude-score` 付与） |
| リサーチャー② Proposer | 新しい絵本・機能を発案して Issue 自動起票 |
| 作成者 Weekly | `approved` 付き最上位 Issue を実装して **Draft PR** |
| こども Reviewer | Draft PR を実ブラウザで触り発達視点で所見（**承認はしない**） |

人間ゲートは二段（入口＝Issue に `approved`／出口＝PR を merge）。設計の詳細は [`docs/automation/agent-pipeline.md`](docs/automation/agent-pipeline.md)、運用手順は [`.github/scripts/README.md`](.github/scripts/README.md) を参照。

## 開発メモ

- 編集時には `.claude/settings.json` の PostToolUse hook が走り、コード変更時に **README 更新の要否を Claude にリマインド** してくれる
- ブラウザ確認時は Chrome で `http://localhost:8000/` を開いて、本棚 → 各ブックの順で全シーンが切り替わるか確認する

## ライセンス

個人用。
