"""Daily Investigator の LangGraph 配線（langgraph はこのファイルだけが import）。

``nodes.py`` の純関数を State 上のノードとして繋ぐ。テストは ``nodes.py`` を直接
対象にするため、本モジュールは langgraph・実 LLM・実 IO を前提とした実運用経路。

State は §4.2 の ``DailyState``。dedupe_gate の ``skip`` と privacy_check の ``abort``
で早期終了する（条件分岐エッジ）。

設計: docs/automation/agent-pipeline.md §4.1 / §4.2
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from daily_investigator import nodes


class DailyState(TypedDict, total=False):
    """Daily Investigator の状態スキーマ（§4.2）。"""

    issue_number: int
    issue_title: str
    issue_body: str
    labels: list[str]
    existing_comments_today: bool
    research_notes: str
    difficulty: dict
    feature_proposal: str
    score: int
    score_rationale: str
    score_breakdown: dict
    rendered_comment: str
    posted_comment_url: str | None
    errors: list[str]
    # 制御フラグ（グラフ内分岐用）
    skip: bool
    abort: bool


def build_graph(
    *,
    chat: Callable[..., str] | None = None,
    client: Any = None,
    io: Any = None,
    denylist: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Any:
    """ノードを配線したコンパイル済みグラフを返す。

    依存（chat / client / io / denylist / env / フラグ）はクロージャで各ノードに束ねる。
    load_issue は IO を要するため、グラフ外（run.py）で実行して初期 state を渡す前提
    とし、本グラフは dedupe_gate から開始する。
    """

    def _dedupe(state: DailyState) -> dict[str, Any]:
        return nodes.dedupe_gate(state, now=now, force=force)

    def _research(state: DailyState) -> dict[str, Any]:
        return nodes.research_notes(state, chat=chat, client=client, env=env)

    def _difficulty(state: DailyState) -> dict[str, Any]:
        return nodes.difficulty_estimate(state, chat=chat, client=client, env=env)

    def _feature(state: DailyState) -> dict[str, Any]:
        return nodes.feature_proposal(state, chat=chat, client=client, env=env)

    def _score(state: DailyState) -> dict[str, Any]:
        return nodes.score_priority(state, chat=chat, client=client, env=env)

    def _format(state: DailyState) -> dict[str, Any]:
        return nodes.format_comment(state, now=now)

    def _privacy(state: DailyState) -> dict[str, Any]:
        return nodes.privacy_check(state, denylist=denylist, env=env)

    def _post(state: DailyState) -> dict[str, Any]:
        return nodes.post_comment(state, io=io, dry_run=dry_run)

    graph = StateGraph(DailyState)
    graph.add_node("dedupe_gate", _dedupe)
    graph.add_node("research_notes", _research)
    graph.add_node("difficulty_estimate", _difficulty)
    graph.add_node("feature_proposal", _feature)
    graph.add_node("score_priority", _score)
    graph.add_node("format_comment", _format)
    graph.add_node("privacy_check", _privacy)
    graph.add_node("post_comment", _post)

    graph.add_edge(START, "dedupe_gate")
    graph.add_conditional_edges(
        "dedupe_gate",
        lambda state: END if state.get("skip") else "research_notes",
        {END: END, "research_notes": "research_notes"},
    )
    graph.add_edge("research_notes", "difficulty_estimate")
    graph.add_edge("difficulty_estimate", "feature_proposal")
    graph.add_edge("feature_proposal", "score_priority")
    graph.add_edge("score_priority", "format_comment")
    graph.add_edge("format_comment", "privacy_check")
    graph.add_conditional_edges(
        "privacy_check",
        lambda state: END if state.get("abort") else "post_comment",
        {END: END, "post_comment": "post_comment"},
    )
    graph.add_edge("post_comment", END)

    return graph.compile()
