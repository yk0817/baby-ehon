"""作成者 — Weekly Implementer（最高スコア Issue の実装・Draft PR 化）。

approved ラベル付き Issue のうち claude-score 最上位を 1 件選び、コード生成して Draft PR を出し、
対象 Issue に stage:implemented を付与してこどもレビュワーを連鎖起動する役。実装は #19。

設計: docs/automation/agent-pipeline.md §6
"""
