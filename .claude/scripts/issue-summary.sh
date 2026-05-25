#!/usr/bin/env bash
# baby-ehon: セッション開始時に GitHub のオープン Issue を一覧する。
# Claude Code の SessionStart hook から呼ばれる想定。stdout が会話冒頭に注入される。

set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT" 2>/dev/null || exit 0

if ! command -v gh >/dev/null 2>&1; then
  echo "[baby-ehon] gh CLI が見つかりません。issue 一覧は省略します。"
  exit 0
fi

echo "## baby-ehon — 現在オープンの Issue"
echo
if ! gh issue list --state open --limit 30 \
  --json number,title,labels \
  --template '{{range .}}- #{{.number}} {{.title}}{{range .labels}} `{{.name}}`{{end}}
{{end}}' 2>/dev/null; then
  echo "(gh で issue を取得できませんでした。認証 / ネットワークを確認)"
  exit 0
fi

echo
echo "詳細: \`gh issue view <番号>\` / 全件: https://github.com/yk0817/baby-ehon/issues"
