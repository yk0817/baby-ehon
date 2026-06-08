"""Proposer の LangGraph 配線（langgraph を import する唯一のファイル）。

ノードの中身は ``nodes.py`` の純関数に閉じ込めてあり、ここはそれらを
``StateGraph`` に登録して条件分岐エッジを張るだけにする（§5.1 のフロー）。
LLM / GitHubIO / 各種パラメータは ``build_graph`` の引数で受け、ノードに束ねて渡す。

フロー（§5.1）::

    load_context → backlog_gate ─skip→ END
                       │continue
                       ▼
                    ideate → novelty_gate ─retry→ ideate
                       ▲                  ├skip → END
                       │                  └continue
                       │                      ▼
                       │              self_score → self_score_gate ─drop→ END
                       │                                  │accept
                       │                                  ▼
                       │                              draft_issue → privacy_check ─abort→ END
                       │                                                  │ok
                       │                                                  ▼
                       │                                              create_issue → END

設計: docs/automation/agent-pipeline.md §5.1
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from . import nodes
from .nodes import (
    DEFAULT_BACKLOG_MAX,
    DEFAULT_NOVELTY_MAX_ATTEMPTS,
    DEFAULT_SCORE_THRESHOLD,
    ProposerState,
)

LLMFn = Callable[[str, str], str]


def build_graph(
    *,
    llm: LLMFn,
    io: Any,
    today: str,
    denylist: tuple[str, ...] = (),
    dry_run: bool = False,
    backlog_max: int = DEFAULT_BACKLOG_MAX,
    novelty_max_attempts: int = DEFAULT_NOVELTY_MAX_ATTEMPTS,
    score_threshold: int = DEFAULT_SCORE_THRESHOLD,
) -> Any:
    """Proposer のコンパイル済みグラフを返す。

    依存（LLM / IO / 日付 / denylist / 各閾値）を束ねてノードに渡す。
    ``load_context`` は run.py 側で state を組み立てるため、ここでは backlog_gate を
    開始ノードにする（state は呼び出し側が初期化済みで渡す）。
    """
    graph: StateGraph = StateGraph(ProposerState)

    graph.add_node(
        "backlog_gate", lambda s: nodes.backlog_gate(s, backlog_max=backlog_max)
    )
    graph.add_node("ideate", lambda s: nodes.ideate(s, llm=llm))
    graph.add_node("novelty_gate", nodes.novelty_gate)
    graph.add_node("self_score", lambda s: nodes.self_score(s, llm=llm))
    graph.add_node(
        "self_score_gate",
        lambda s: nodes.self_score_gate(s, threshold=score_threshold),
    )
    graph.add_node("draft_issue", lambda s: nodes.draft_issue(s, today=today))
    graph.add_node("privacy_check", lambda s: nodes.privacy_check(s, denylist=denylist))
    graph.add_node(
        "create_issue", lambda s: nodes.create_issue(s, io=io, dry_run=dry_run)
    )

    graph.set_entry_point("backlog_gate")

    graph.add_conditional_edges(
        "backlog_gate",
        nodes.route_backlog,
        {"skip": END, "continue": "ideate"},
    )
    graph.add_edge("ideate", "novelty_gate")
    graph.add_conditional_edges(
        "novelty_gate",
        lambda s: nodes.route_novelty(s, max_attempts=novelty_max_attempts),
        {"retry": "ideate", "skip": END, "continue": "self_score"},
    )
    graph.add_edge("self_score", "self_score_gate")
    graph.add_conditional_edges(
        "self_score_gate",
        nodes.route_self_score,
        {"accept": "draft_issue", "drop": END},
    )
    graph.add_edge("draft_issue", "privacy_check")
    graph.add_conditional_edges(
        "privacy_check",
        nodes.route_privacy,
        {"ok": "create_issue", "abort": END},
    )
    graph.add_edge("create_issue", END)

    return graph.compile()
