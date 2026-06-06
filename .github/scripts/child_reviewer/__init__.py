"""こども — Child Reviewer（Draft PR を実ブラウザで触って所見）。

対象児（1 歳）の代弁役。Playwright で絵本を実際に開いてスクリーンショットを撮り、コード差分と合わせて
発達視点の所見を PR にコメントする（Approve はしない）。対象 Issue に stage:child-reviewed を付与。実装は #21。

設計: docs/automation/agent-pipeline.md §7
"""
