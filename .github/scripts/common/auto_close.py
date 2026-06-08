"""3 役完了による Issue 自動クローズの純判定。

3 つのエージェント役（リサーチャー / 作成者 / こども）が処理を終えると、対象 Issue に
それぞれのステージラベルを 1 つ貼る。3 役ぶんのラベルが揃った Issue は自動でクローズする
（§2.1）。ここはその「揃ったか / 閉じてよいか」を判定する純関数だけを置く。

実際にクローズする動作は label-triggered workflow
``.github/workflows/auto-close-staged-issues.yml`` が actions/github-script で行う
（冪等・既存の役パッケージを改変しない）。本モジュールは役からも workflow からも参照できる
意味の単一情報源（STAGE_LABELS / SKIP_LABEL / CLOSE_MARKER）を提供する。

判定方針（§2.1 / §2.2）:

- 3 ステージラベルが全て揃い、かつ ``automation:skip`` が無ければクローズ可。
- ``approved`` は **入口ゲート**（人間の作成承認）であり、クローズ条件には含めない（§2.2）。
- 人間が PR を merge して ``Closes #N`` で閉じるケースとも二重に作用して冪等
  （既に closed なら何もしない＝workflow 側で担保）。

設計: docs/automation/agent-pipeline.md §2.1 / §2.2
"""

from __future__ import annotations

from collections.abc import Iterable

# 3 役それぞれが処理完了時に貼るステージラベル（§2.1）。
STAGE_LABELS: tuple[str, ...] = (
    "stage:researched",
    "stage:implemented",
    "stage:child-reviewed",
)

# このラベルが付いた Issue は自動処理（クローズ含む）の対象外（§2.1）。
SKIP_LABEL = "automation:skip"

# 自動クローズコメントに埋める機械可読マーカー。
# workflow はこのマーカーの有無で「既に自動クローズ済みか」を判定でき、冪等性を担保する。
CLOSE_MARKER = "<!-- auto-closed: 3-stage-complete -->"


def should_close(labels: Iterable[str]) -> bool:
    """3 ステージラベルが全て揃い、かつ ``automation:skip`` が無ければ True を返す。

    ``labels`` は順不同・重複・無関係ラベル混在でよい（set 化して判定する）。
    ``approved`` の有無はクローズ判定に影響しない（§2.2）。
    """
    label_set = set(labels)
    if SKIP_LABEL in label_set:
        return False
    return all(stage in label_set for stage in STAGE_LABELS)
