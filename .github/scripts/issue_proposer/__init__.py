"""リサーチャー② — Proposer（新しい絵本／機能の発案・Issue 自動起票）。

週次で発達研究ベースの新案を 1 件生成し、novelty / backlog / self_score ゲートを通過したものだけを
claude-proposed Issue として自動起票する役。実装は #17。

設計: docs/automation/agent-pipeline.md §5
"""
