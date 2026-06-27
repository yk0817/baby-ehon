#!/usr/bin/env bash
# verify.sh — 足場の ③Verification（検証） / 単一の合否ゲート
#
# 何をするか:
#   §3.5 の4ゲートを順に走らせ、終了コードで「成果物が緑か」を返す。
#     ① e2e         絵本本体のシナリオ網羅（pytest-playwright）
#     ② 単体+cov    ループ/足場ロジックの pytest と coverage 床（--cov-fail-under）
#     ③ privacy     config.js の __NAME__ positive assert ＋ 実名混入0（privacy_gate.py）
#     ④ 契約の不可侵 受け入れ e2e（automation/specs/*/acceptance/）の改変0（git diff）
#   1つでも欠ければ赤（exit≠0）、全て満たせば緑（exit 0）。全ゲートを走り切って
#   サマリを出す（どれが赤かを人間が即把握できるように）。
# なぜ必要か:
#   完了は「エージェントがそう言った」ではなく「verify が緑」で決める（証拠ベース）。
#   人間・loop・CI が **同じ1コマンド** で同じ判定を出せることが要件（自己採点の排除）。
#
# 使い方:   bash automation/harness/verify.sh
# 終了コード: 0 = 全ゲート緑 / 非0 = 1つ以上が赤
#
# 環境変数（既定は本物のコマンド。各ゲートは差し替え可能＝テスト用 seam）:
#   BABY_EHON_ROOT        リポジトリルート（既定: このスクリプトから2つ上）
#   VERIFY_PYTHON         使う python（既定: python3）
#   VERIFY_MIN_COV        coverage の床%（既定: 80）。config.py の min_coverage と揃える
#   VERIFY_E2E_CMD        ①ゲートのコマンド
#   VERIFY_UNIT_CMD       ②ゲートのコマンド
#   VERIFY_PRIVACY_CMD    ③ゲートのコマンド
#   VERIFY_ACCEPTANCE_CMD ④ゲートのコマンド
set -uo pipefail

ROOT="${BABY_EHON_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON="${VERIFY_PYTHON:-python3}"
MIN_COV="${VERIFY_MIN_COV:-80}"

# ── 各ゲートの既定コマンド（env で上書き可） ─────────────────────────────────
# 既定は eval される文字列。python・パスとも単引用符で包み、空白を含んでも1語に保つ。
_DEFAULT_E2E="'$PYTHON' -m pytest '$ROOT/e2e' -q"
_DEFAULT_UNIT="'$PYTHON' -m pytest '$ROOT/automation/tests' -q --cov=automation --cov-report=term-missing --cov-fail-under=$MIN_COV"
_DEFAULT_PRIVACY="'$PYTHON' '$ROOT/automation/harness/privacy_gate.py'"

E2E_CMD="${VERIFY_E2E_CMD:-$_DEFAULT_E2E}"
UNIT_CMD="${VERIFY_UNIT_CMD:-$_DEFAULT_UNIT}"
PRIVACY_CMD="${VERIFY_PRIVACY_CMD:-$_DEFAULT_PRIVACY}"
# ④は既定で下の関数を呼ぶ（env で任意コマンドに差し替え可能）。
ACCEPTANCE_CMD="${VERIFY_ACCEPTANCE_CMD:-_check_acceptance_unchanged}"

# ④契約の不可侵: automation/specs/*/acceptance/ が working tree / index で改変されていないこと。
# git リポジトリでない場合は契約も無いとみなして緑（PR-2 時点では specs 未作成）。
_check_acceptance_unchanged() {
  if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  （git 管理外のため契約チェックはスキップ＝緑）"
    return 0
  fi
  local pathspec=":(glob)automation/specs/*/acceptance/**"
  if git -C "$ROOT" diff --quiet -- "$pathspec" \
     && git -C "$ROOT" diff --cached --quiet -- "$pathspec"; then
    return 0
  fi
  echo "  受け入れ e2e（契約）が改変されています（maker は契約を書き換え禁止）" >&2
  return 1
}

# ── ゲート実行ヘルパ（全ゲートを走らせ、落ちても止めずに集計） ───────────────
# eval を使うのは、env で渡されたコマンド文字列（既定は本物のコマンド／関数名）を
# 1つのコマンドとして解釈するため。値は足場側（人間/CI）が与え maker は与えない
# （信頼境界の内側）。
FAILED=()

run_gate_cmd() {
  local name="$1"
  local cmd="$2"
  echo "▶ gate: ${name}"
  if eval "$cmd"; then
    echo "  ✓ ${name}: PASS"
  else
    echo "  ✗ ${name}: FAIL" >&2
    FAILED+=("$name")
  fi
}

cd "$ROOT" || { echo "✗ cd 失敗: ${ROOT}" >&2; exit 1; }
run_gate_cmd "e2e" "$E2E_CMD"
run_gate_cmd "unit" "$UNIT_CMD"
run_gate_cmd "privacy" "$PRIVACY_CMD"
run_gate_cmd "acceptance" "$ACCEPTANCE_CMD"

# ── 総合判定 ────────────────────────────────────────────────────────────────
echo "────────────────────────────────────────"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "✓ verify: 全ゲート緑"
  exit 0
fi
echo "✗ verify: 赤（FAIL: ${FAILED[*]}）"
exit 1
