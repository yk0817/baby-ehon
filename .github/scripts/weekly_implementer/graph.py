"""Weekly Implementer の LangGraph 配線（langgraph を import する唯一のファイル）。

ノードの中身は ``nodes.py`` の純関数に閉じ込めてあり、ここはそれらを ``StateGraph``
に登録して条件分岐エッジを張るだけにする（§6.1 のフロー）。LLM / reader / writer /
git / pr_runner / workflow_runner / io / 各種パラメータは ``build_graph`` の引数で
受け、ノードに束ねて渡す。

フロー（§6.1）::

    list_open_issues → collect_scores → select_top ─skip→ END
                                            │continue
                                            ▼
                                       gather_context → plan_change → generate_patch
                                            → privacy_check ─violation→ record_failure → END
                                                  │ok
                                                  ▼
                                              apply_patches → git_commit_push
                                              → open_draft_pr → label_pr_and_issue
                                              → trigger_child_review → END

注: list_open_issues / collect_scores は GitHub I/O を伴うため run.py 側で state を
組み立て、ここでは select_top を実質の開始点にする（state は呼び出し側が初期化済み）。

設計: docs/automation/agent-pipeline.md §6.1
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END, StateGraph

from . import nodes
from .nodes import WeeklyState

LLMFn = Callable[[str, str], str]


def build_graph(
    *,
    plan_llm: LLMFn,
    generate_llm: LLMFn,
    reader: Callable[..., dict[str, str]],
    repo_root: Any,
    writer: Callable[[str, str], None],
    git: Any,
    pr_runner: Callable[..., dict[str, Any]],
    workflow_runner: Callable[[str, dict[str, str]], Any],
    io: Any,
    denylist: Sequence[str] = (),
    base: str = "main",
    dry_run: bool = False,
) -> Any:
    """Weekly Implementer のコンパイル済みグラフを返す。

    依存（LLM 2 種 / reader / writer / git / pr_runner / workflow_runner / io）を
    束ねてノードに渡す。開始点は ``select_top``（list/collect は run.py が事前に state
    へ流し込む）。
    """
    graph: StateGraph = StateGraph(WeeklyState)

    graph.add_node("select_top", nodes.select_top)
    graph.add_node(
        "gather_context",
        lambda s: nodes.gather_context(s, reader=reader, repo_root=repo_root),
    )
    graph.add_node("plan_change", lambda s: nodes.plan_change(s, llm=plan_llm))
    graph.add_node(
        "generate_patch", lambda s: nodes.generate_patch(s, llm=generate_llm)
    )
    graph.add_node("privacy_check", lambda s: nodes.privacy_check(s, denylist=denylist))
    graph.add_node(
        "record_failure_comment",
        lambda s: nodes.record_failure_comment(s, io=io, dry_run=dry_run),
    )
    graph.add_node(
        "apply_patches",
        lambda s: nodes.apply_patches(s, writer=writer, dry_run=dry_run),
    )
    graph.add_node(
        "git_commit_push",
        lambda s: nodes.git_commit_push(s, git=git, dry_run=dry_run),
    )
    graph.add_node(
        "open_draft_pr",
        lambda s: nodes.open_draft_pr(
            s, pr_runner=pr_runner, base=base, dry_run=dry_run
        ),
    )
    graph.add_node(
        "label_pr_and_issue",
        lambda s: nodes.label_pr_and_issue(s, io=io, dry_run=dry_run),
    )
    graph.add_node(
        "trigger_child_review",
        lambda s: nodes.trigger_child_review(
            s, workflow_runner=workflow_runner, dry_run=dry_run
        ),
    )

    graph.set_entry_point("select_top")

    graph.add_conditional_edges(
        "select_top",
        nodes.route_selected,
        {"skip": END, "continue": "gather_context"},
    )
    graph.add_edge("gather_context", "plan_change")
    graph.add_edge("plan_change", "generate_patch")
    graph.add_edge("generate_patch", "privacy_check")
    graph.add_conditional_edges(
        "privacy_check",
        nodes.route_privacy,
        {"violation": "record_failure_comment", "ok": "apply_patches"},
    )
    graph.add_edge("record_failure_comment", END)
    graph.add_edge("apply_patches", "git_commit_push")
    graph.add_edge("git_commit_push", "open_draft_pr")
    graph.add_edge("open_draft_pr", "label_pr_and_issue")
    graph.add_edge("label_pr_and_issue", "trigger_child_review")
    graph.add_edge("trigger_child_review", END)

    return graph.compile()
