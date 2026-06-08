"""Child Reviewer の LangGraph 配線（langgraph を import する唯一のファイル）。

ノードの中身は ``nodes.py`` の純関数に閉じ込めてあり、ここはそれらを ``StateGraph``
に登録してエッジを張るだけにする（§7.1 のフロー）。判定（Vision judge）・GitHubIO・
スクショ撮影などの依存は ``build_graph`` の引数で受け、ノードに束ねて渡す。

I/O を伴う前段（checkout_pr / seed_baby_js / serve_static / detect_changed_books /
capture / read_code_diff）は ``run.py`` 側で実行して初期 state を組み立てる。グラフは
**judge から post_pr_comment まで** を担い、純粋ノード中心で完結させる（テスト容易性）。

フロー（§7.1 後半）::

    judge → score_rubric → format_review → privacy_check ─abort→ END
                                                  │ok
                                                  ▼
                                          post_pr_comment → END

設計: docs/automation/agent-pipeline.md §7.1
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, StateGraph

from . import nodes
from .nodes import ChildReviewState, JudgeFn


def build_graph(
    *,
    judge_fn: JudgeFn,
    io: Any,
    system: str = "",
    score_fn: Any = None,
    denylist: Sequence[str] = (),
    dry_run: bool = False,
) -> Any:
    """Child Reviewer のコンパイル済みグラフを返す。

    依存（Vision judge / IO / system プロンプト / denylist）を束ねてノードに渡す。
    初期 state（pr_number / branch / changed_books / screenshots / code_excerpts /
    pr_body）は呼び出し側が組み立てて渡す。
    """
    graph: StateGraph = StateGraph(ChildReviewState)

    graph.add_node("judge", lambda s: nodes.judge(s, judge_fn=judge_fn, system=system))
    graph.add_node("score_rubric", lambda s: nodes.score_rubric(s, score_fn=score_fn))
    graph.add_node("format_review", nodes.format_review)
    graph.add_node("privacy_check", lambda s: nodes.privacy_check(s, denylist=denylist))
    graph.add_node(
        "post_pr_comment", lambda s: nodes.post_pr_comment(s, io=io, dry_run=dry_run)
    )

    graph.set_entry_point("judge")
    graph.add_edge("judge", "score_rubric")
    graph.add_edge("score_rubric", "format_review")
    graph.add_edge("format_review", "privacy_check")
    graph.add_conditional_edges(
        "privacy_check",
        nodes.route_privacy,
        {"ok": "post_pr_comment", "abort": END},
    )
    graph.add_edge("post_pr_comment", END)

    return graph.compile()
