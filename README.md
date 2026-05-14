# いちかくんの ほんだな (baby-ehon)

1歳のいちかくん向けの、ブラウザで動く絵本シリーズ。HTML/CSS/JS だけで作っており、ビルド不要。

## ラインナップ

| ブック | パス | シーン |
|--------|------|--------|
| 🛩️ いちかくんの ひこうき | [`hikouki/`](hikouki/) | りりく → くものなか → うみのうえ → よぞら → ちゃくりく |
| 🚄 いちかくんの でんしゃ | [`densha/`](densha/) | はっしゃ → まち → てっきょう → よるのまち → しゅうちゃくえき |
| 🚗 いちかくんの くるま | [`kuruma/`](kuruma/) | しゅっぱつ → まち → やまみち → よる → ゴール |

トップの [`index.html`](index.html) は本棚（ランディング）。タップで各ブックに飛ぶ。

## 機能

すべてのブックに以下が入る:

- **ページ遷移**: タップ／スワイプ／矢印キー／自動進行（12秒）
- **オノマトペバブル**: タップで派手にポップ、シーン別に複数バリエーション
- **いちかくんへの語りかけ**: ページ切替時・5秒ごとに白い吹き出しで「いちかくん、〜」
- **Mac カメラ ミラー窓**: 右下の円窓に自分たちの顔を表示（鏡像反転）。ページ切替で「ぴょこっ」と弾むリアクション
- **キーボード乱打リアクション**（1歳向け）: ←→ 以外のキーを押すと、ランダムな言葉/絵文字バブル＋大量のきらきら＋画面フラッシュ＋音程変化
- **音**: WebAudio API でシーン別の音階を生成

## 動かしかた

ブラウザの `getUserMedia` はファイルプロトコルでは動かないため、ローカルサーバー経由で開く必要がある。

```bash
cd ~/baby-ehon
python3 -m http.server 8000
```

ブラウザで `http://localhost:8000/` を開く → 本棚から好きな乗り物を選ぶ。

カメラを使うときは右下の「いちかくんを タップ！」をタップしてカメラを許可。大人がカメラを止めたいときは円窓をダブルクリック。

## 構成

```
baby-ehon/
├── index.html        # 本棚（ランディング）
├── shelf.css         # 本棚スタイル
├── README.md
├── shared/
│   ├── ehon.css      # 共通スタイル（カメラ窓・SFX・吹き出し・ナビ等）
│   └── ehon.js       # 共通エンジン（BOOK_CONFIG を読んで動く）
├── hikouki/
│   ├── index.html
│   ├── theme.css     # 空・雲・飛行機などの絵
│   └── config.js     # シーン別 sfx / talks / colors / notes
├── densha/
│   ├── index.html
│   ├── theme.css
│   └── config.js
└── kuruma/
    ├── index.html
    ├── theme.css
    └── config.js
```

## 新しいブックを追加するには

1. `<name>/` ディレクトリを作る
2. `config.js` でシーンごとのオノマトペ・語りかけ・色・音階を定義
3. `theme.css` で背景や乗り物の見た目を定義
4. `index.html` で5つの `<section class="page" data-scene="<key>">` を並べる
   - 共通の `id="fx-layer"` `id="cam-window"` `class="parent-nav"` を含める
   - `<script src="config.js"></script>` → `<script src="../shared/ehon.js"></script>` の順で読み込む
5. ルートの `index.html` 本棚にカードを追加

## ライセンス

個人用。
