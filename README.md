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
| 🐾 どうぶつ | [`animals/`](animals/) | どうぶつの なきごえ |

トップの [`index.html`](index.html) は本棚（ランディング）。タップで各ブックに飛ぶ。

## 構成

```
baby-ehon/
├── index.html
├── shelf.css
├── README.md
├── CLAUDE.md
├── .gitignore
├── shared/
│   ├── ehon.css
│   ├── ehon.js
│   ├── baby.example.js
│   └── baby.js
├── animals/
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   ├── config.js
│   ├── images/
│   └── sounds/
├── hikouki/
├── densha/
├── kuruma/
├── otenki/
└── yorunosora/
```