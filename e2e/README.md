# e2e — 絵本本体の E2E UI テスト

絵本（`hikouki/` などの HTML/CSS/JS）を**実ブラウザ（Chromium）で操作して**動作を確認する E2E テスト。
ランナーは **pytest-playwright**（Python）。絵本本体は「ビルドツール・npm を入れない」方針なので、
テストも npm を使わず Python + Playwright で揃えている（こどもレビュワーと同じスタック）。

> ⚠️ ここはテスト専用。絵本の配信・動作には一切影響しない。

## 前提

- **uv**（Python パッケージマネージャ）。未導入なら [astral.sh/uv](https://docs.astral.sh/uv/)
- 初回のみ Chromium 本体のダウンロードが要る（下記セットアップ）

## セットアップ（初回だけ）

```bash
cd e2e

# 依存（pytest / pytest-playwright）を venv に入れる
uv venv
uv pip install -r requirements.txt

# Chromium 本体を取得（初回のみ・約150MB）
uv run playwright install chromium
```

## 実行

```bash
cd e2e

# 全テスト（ヘッドレス）
uv run python -m pytest -q

# 特定ファイル / 特定テストだけ
uv run python -m pytest test_smoke.py -q
uv run python -m pytest test_smoke.py::test_shelf_lists_five_books -q
```

### ブラウザを見ながら確認したいとき（おすすめ）

```bash
cd e2e

# 実ブラウザを表示して動きを目で見る
uv run python -m pytest --headed -q

# ゆっくり動かす（ミリ秒）。操作が速すぎて追えないときに
uv run python -m pytest --headed --slowmo 500 -q

# Playwright Inspector でステップ実行（デバッグ）
PWDEBUG=1 uv run python -m pytest test_smoke.py -k shelf
```

### 失敗を調べる

```bash
# 失敗時のスクショ/動画/trace を残す（CI と同じ挙動）
uv run python -m pytest --screenshot=only-on-failure --video=retain-on-failure --tracing=retain-on-failure -q

# trace を見る
uv run playwright show-trace test-results/<...>/trace.zip
```

## 仕組み（`conftest.py` の fixture）

| fixture | 役割 |
|---|---|
| **静的配信** | 空きポートで `http.server` 相当を起動し `base_url` を渡す。`/.github` `/docs` `/.git` は **403 で配信しない**（テスト中だけ localhost に出す範囲を絞る） |
| **baby.js seed** | テスト前に既存 `shared/baby.js` を退避し、`shared/baby.example.js`（既定名 `あかちゃん`）を `shared/baby.js` に置く。**テスト後に必ず復元**（無ければ削除）。あなたのローカルの実 `baby.js` は壊れない |
| **ブラウザ API モック** | `getUserMedia`（カメラ）と `AudioContext`（音）をモック。カメラ権限でハングせず、音も鳴らさずに「呼ばれたか」を検証できる |

ページ操作のヘルパは `pages.py`（本棚を開く / ブックを開く / タップ・矢印・スワイプで送る / 施錠・長押し解除 など）。
後続の E2E（各ジャーニー）はこの土台の上に追加していく。

## 注意

- **実名を使わない**。テストは seed の既定名 `あかちゃん` だけを前提にする
- `shared/baby.js` は seed で一時的に上書きされるが、テスト後に元へ戻す。テストを中断（Ctrl-C 等）した場合に
  万一 `あかちゃん` のまま残っていたら、自分の `shared/baby.js` を書き直すか削除すれば既定に戻る
- ポートは自動で空きを取るので競合しない

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `Executable doesn't exist ... chromium` | `uv run playwright install chromium`（セットアップ未実施） |
| カメラ許可ダイアログで止まる | モックが効いていない。`--headed` を外す／`conftest.py` の init script を確認 |
| 文字化け・名前が出ない | seed が動いているか（`shared/baby.example.js` の存在）を確認 |
