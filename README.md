# __NAME__くんの ほんだな (baby-ehon)

1歳の__NAME__くん向けの、ブラウザで動く絵本シリーズ。HTML/CSS/JS だけで作っており、ビルド不要。

## ラインナップ

| ブック | パス | シーン |
|--------|------|--------|
| 🛩️ __NAME__くんの ひこうき | [`hikouki/`](hikouki/) | りりく → くものなか → うみのうえ → よぞら → ちゃくりく |
| 🚄 __NAME__くんの でんしゃ | [`densha/`](densha/) | はっしゃ → まち → てっきょう → よるのまち → しゅうちゃくえき |
| 🚗 __NAME__くんの くるま | [`kuruma/`](kuruma/) | しゅっぱつ → まち → やまみち → よる → ゴール |
| ☀️ __NAME__くんの おてんき | [`otenki/`](otenki/) | はれ → くもり → あめ → かみなり → にじ |
| 🌙 __NAME__くんの よる の そら | [`yorunosora/`](yorunosora/) | ゆうやけ → おつきさま → ほし → ながれぼし → あさやけ |

トップの [`index.html`](index.html) は本棚（ランディング）。タップで各ブックに飛ぶ。

## 機能

すべてのブックに以下が入る:

- **ページ遷移**: タップ／スワイプ／矢印キー／自動進行（12秒）
- **オノマトペバブル**: タップで派手にポップ、シーン別に複数バリエーション
- **__NAME__くんへの語りかけ**: ページ切替時・5秒ごとに白い吹き出しで「__NAME__くん、〜」
- **Mac カメラ ミラー窓**: 右下の円窓に自分たちの顔を表示（鏡像反転）。ページ切替で「ぴょこっ」と弾むリアクション
- **キーボード乱打リアクション**（1歳向け）: ←→ 以外のキーを押すと、ランダムな言葉/絵文字バブル＋大量のきらきら＋画面フラッシュ＋音程変化
- **音**: WebAudio API でシーン別の音階を生成
- **チャイルドロック** 🔒: 右上の鍵ボタンで施錠。施錠中はナビ（戻る／進む／ホーム）が無効化＋自動で全画面化され、__NAME__くんが触ってもページ離脱しない。解除は鍵ボタンを **1.5秒長押し**

## 動かしかた

ブラウザの `getUserMedia` はファイルプロトコルでは動かないため、ローカルサーバー経由で開く必要がある。

```bash
cd ~/baby-ehon
python3 -m http.server 8000
```

ブラウザで `http://localhost:8000/` を開く → 本棚から好きな乗り物／そらを選ぶ。

カメラを使うときは右下の「__NAME__くんを タップ！」をタップしてカメラを許可。大人がカメラを止めたいときは円窓をダブルクリック。

## 構成

```
baby-ehon/
├── index.html        # 本棚（ランディング）
├── shelf.css         # 本棚スタイル
├── README.md
├── shared/
│   ├── ehon.css      # 共通スタイル（カメラ窓・SFX・吹き出し・ロック・ナビ等）
│   └── ehon.js       # 共通エンジン（BOOK_CONFIG を読んで動く / チャイルドロック制御）
├── hikouki/
│   ├── index.html
│   ├── theme.css     # 空・雲・飛行機などの絵
│   └── config.js     # シーン別 sfx / talks / colors / notes
├── densha/
│   ├── index.html
│   ├── theme.css
│   └── config.js
├── kuruma/
│   ├── index.html
│   ├── theme.css
│   └── config.js
├── otenki/
│   ├── index.html
│   ├── theme.css
│   └── config.js
└── yorunosora/
    ├── index.html
    ├── theme.css
    └── config.js
```

## 新しいブックを追加するには

1. `<name>/` ディレクトリを作る
2. `config.js` でシーンごとのオノマトペ・語りかけ・色・音階を定義
3. `theme.css` で背景や乗り物の見た目を定義
4. `index.html` で5つの `<section class="page" data-scene="<key>">` を並べる
   - 共通の `id="fx-layer"` `id="cam-window"` `class="parent-nav"`（`lock-btn` を含む）を含める
   - `<script src="config.js"></script>` → `<script src="../shared/ehon.js"></script>` の順で読み込む
5. ルートの `index.html` 本棚にカードを追加
6. **README.md のラインナップ表とディレクトリ構成も更新する**

## 開発メモ

- 編集時には `.claude/settings.json` の PostToolUse hook が走り、コード変更時に **README 更新の要否をリマインド** してくれる（Claude Code 経由で編集している場合のみ）
- ブラウザ確認時は Chrome で `http://localhost:8000/` を開いて、本棚 → 各ブックの順で全シーンが切り替わるか確認する

## ライセンス

個人用。
