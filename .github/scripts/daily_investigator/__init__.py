"""リサーチャー① — Daily Investigator（既存 Issue の調査・採点）。

2 日に 1 回、オープン中の全 Issue を調査して claude-score マーカー付きコメントを投稿し、
対象 Issue に stage:researched ラベルを付与する役。実装は #15。

設計: docs/automation/agent-pipeline.md §4
"""
