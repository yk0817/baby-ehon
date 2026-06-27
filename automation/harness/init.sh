#!/usr/bin/env bash
# init.sh — 足場の ⑤Session Lifecycle（初期化 / 始末の「始」）
#
# 何をするか:
#   1. shared/baby.js を shared/baby.example.js（既定名「あかちゃん」）から **冪等に seed**
#      （既存があれば壊さない。実 baby.js を CI/loop に持ち込まない＝既存 e2e/conftest と同方針）
#   2. 依存（python3 / pytest、任意で playwright）が揃っているか確認して報告する
# なぜ必要か:
#   maker を動かす前に「土台が整っている」ことを保証する。土台が壊れたまま実装させると
#   原因の切り分けが難しくなる（実装の赤か、足場の赤か区別できない）。
#
# 使い方:   bash automation/harness/init.sh
# 終了コード: 0 = 初期化 OK / 非0 = 必須依存の欠落（python3 / pytest / example 不在）
#
# 環境変数:
#   BABY_EHON_ROOT  リポジトリルート（既定: このスクリプトから2つ上）。テストで差し替える seam
#   VERIFY_PYTHON   使う python（既定: python3）。verify.sh と同じ変数名で揃える
set -uo pipefail

ROOT="${BABY_EHON_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON="${VERIFY_PYTHON:-python3}"

SHARED="$ROOT/shared"
EXAMPLE="$SHARED/baby.example.js"
BABY_JS="$SHARED/baby.js"

# ── 1. baby.js を example から seed（冪等） ───────────────────────────────────
echo "▶ baby.js seed"
if [ ! -f "$EXAMPLE" ]; then
  echo "✗ ${EXAMPLE} がありません（seed 元のテンプレが必要）" >&2
  exit 1
fi
if [ -f "$BABY_JS" ]; then
  echo "  既存の baby.js を保持（上書きしない）"
else
  cp "$EXAMPLE" "$BABY_JS"
  echo "  baby.example.js から baby.js を seed（既定名）"
fi

# ── 2. 依存チェック ─────────────────────────────────────────────────────────
echo "▶ 依存チェック"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "✗ python が見つかりません: ${PYTHON}" >&2
  exit 1
fi
echo "  python: $("$PYTHON" --version 2>&1 | head -1)"

if ! "$PYTHON" -m pytest --version >/dev/null 2>&1; then
  echo "✗ pytest がありません（'$PYTHON -m pip install pytest pytest-cov' を実行）" >&2
  exit 1
fi
echo "  pytest: $("$PYTHON" -m pytest --version 2>&1 | head -1)"

# playwright は e2e（ゲート①）に必要。mock 運用では不要なので欠落は警告に留める。
if "$PYTHON" -m playwright --version >/dev/null 2>&1; then
  echo "  playwright: $("$PYTHON" -m playwright --version 2>&1 | head -1)"
else
  echo "  playwright: 見つかりません（e2e を回すなら '$PYTHON -m playwright install chromium'）"
fi

echo "✓ 初期化完了"
