"""Daily Investigator の LangGraph ノード（純関数・langgraph 非依存）。

各ノードは ``state``（dict）を受け取り **更新分の dict** を返す純関数。langgraph は
``graph.py`` だけが import し、本モジュールは import しない。これにより langgraph /
実 LLM / ネットワーク無しでノードを単体テストできる（``chat`` はフェイク注入）。

ノードの流れ（§4.1）::

    load_issue → dedupe_gate → research_notes → difficulty_estimate
    → feature_proposal → score_priority → format_comment → privacy_check → post_comment

LLM ノード（research/difficulty/feature/score）は ``common.llm.chat`` 互換の ``chat``
を引数注入で受ける（既定は本物の ``llm.chat``）。format_comment は純 Python、
privacy_check は ``common.privacy`` を使う。post_comment のみ GitHub 書き込み。

JST 固定: dedupe / コメント日付は JST（``timezone(timedelta(hours=9))``）で判定する。

設計: docs/automation/agent-pipeline.md §4.1 / §4.2 / §4.3 / §4.4 / §2.1 / §8.6
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from common import llm, privacy
from common.prompts_loader import RolePrompts

#: JST（dedupe 判定とコメント先頭の claude-run 日付に使う、§4.3）
JST = timezone(timedelta(hours=9))

#: 採点の上下限（§4.4 のルーブリック合計）
SCORE_MIN = 0
SCORE_MAX = 100

#: stage:researched ラベル（処理成功後に対象 Issue へ付与、§2.1）
STAGE_LABEL = "stage:researched"

#: research_notes 内の日付マーカー検出（dedupe 用、score_parser と同仕様）
_RUN_MARKER_RE = re.compile(r"<!--\s*claude-run\s*:\s*(\d{4}-\d{2}-\d{2})\s*-->")

#: LLM 応答から総合スコア（0-100 の整数）を拾う緩いパターン
_SCORE_RE = re.compile(r"(-?\d{1,3})")


# --- 補助関数 ----------------------------------------------------------------


def today_jst(now: datetime | None = None) -> str:
    """JST での当日日付文字列（``YYYY-MM-DD``）を返す。"""
    moment = datetime.now(JST) if now is None else now
    return moment.astimezone(JST).strftime("%Y-%m-%d")


def has_today_marker(
    comment_bodies: Sequence[str], *, now: datetime | None = None
) -> bool:
    """コメント群に当日（JST）の ``<!-- claude-run: YYYY-MM-DD -->`` があるか。"""
    today = today_jst(now)
    for body in comment_bodies:
        for marker_date in _RUN_MARKER_RE.findall(body or ""):
            if marker_date == today:
                return True
    return False


def _clamp_score(value: int) -> int:
    """スコアを [SCORE_MIN, SCORE_MAX] にクランプする。"""
    return max(SCORE_MIN, min(SCORE_MAX, value))


def _resolve_prompts(prompts: RolePrompts | None) -> RolePrompts:
    """prompts 未注入なら daily 役を遅延ロードする（循環 import を避けるため遅延）。"""
    if prompts is not None:
        return prompts
    from daily_investigator import prompts as daily_prompts

    return daily_prompts.load()


# --- ノード本体 --------------------------------------------------------------


def load_issue(
    state: Mapping[str, Any],
    *,
    issue: Any,
    comment_bodies: Sequence[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Issue 本体と当日コメント有無を state に載せる（I/O は呼び出し側で実施）。

    ``issue`` は ``number`` / ``title`` / ``body`` / ``labels`` を持つオブジェクト
    （PyGithub Issue 互換）。``comment_bodies`` は当該 Issue のコメント本文列。
    """
    labels = [getattr(label, "name", str(label)) for label in (issue.labels or [])]
    return {
        "issue_number": issue.number,
        "issue_title": issue.title or "",
        "issue_body": issue.body or "",
        "labels": labels,
        "existing_comments_today": has_today_marker(comment_bodies, now=now),
        "errors": list(state.get("errors", [])),
    }


def dedupe_gate(
    state: Mapping[str, Any],
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """当日マーカーがあり ``force`` でなければスキップする（§4.3）。"""
    already = bool(state.get("existing_comments_today"))
    skip = already and not force
    return {"skip": skip}


def _llm_node(
    state: Mapping[str, Any],
    *,
    chat: Callable[..., str] | None,
    client: Any,
    env: Mapping[str, str] | None,
    prompts: RolePrompts | None,
    user: str,
    max_tokens: int = 1024,
) -> str:
    """LLM ノード共通: prompts.system + user で 1 回 chat する。"""
    chat_fn = llm.chat if chat is None else chat
    role_prompts = _resolve_prompts(prompts)
    return chat_fn(
        client,
        role="daily",
        system=role_prompts.system,
        user=user,
        max_tokens=max_tokens,
        env=env,
    )


def research_notes(
    state: Mapping[str, Any],
    *,
    chat: Callable[..., str] | None = None,
    client: Any = None,
    env: Mapping[str, str] | None = None,
    prompts: RolePrompts | None = None,
) -> dict[str, Any]:
    """先行研究・既存手法を簡潔に列挙させる（§4.1）。"""
    user = (
        "次の Issue について、関連する先行研究・既存の表現手法を簡潔に列挙してください。\n"
        f"タイトル: {state.get('issue_title', '')}\n"
        f"本文:\n{state.get('issue_body', '')}"
    )
    notes = _llm_node(
        state, chat=chat, client=client, env=env, prompts=prompts, user=user
    )
    return {"research_notes": notes}


def difficulty_estimate(
    state: Mapping[str, Any],
    *,
    chat: Callable[..., str] | None = None,
    client: Any = None,
    env: Mapping[str, str] | None = None,
    prompts: RolePrompts | None = None,
) -> dict[str, Any]:
    """実装難易度（low/med/high）と HTML/CSS/JS 完結性・影響ファイルを推定（§4.1）。"""
    user = (
        "次の Issue を HTML/CSS/JS のみのブラウザ絵本として実装する難易度を、"
        "低/中/高 のいずれかと、HTML/CSS/JS で完結可能か、影響しそうなファイルを添えて"
        "短く述べてください。\n"
        f"タイトル: {state.get('issue_title', '')}\n"
        f"本文:\n{state.get('issue_body', '')}"
    )
    raw = _llm_node(
        state, chat=chat, client=client, env=env, prompts=prompts, user=user
    )
    return {
        "difficulty": {
            "level": _extract_level(raw),
            "html_css_js_feasible": _extract_feasible(raw),
            "notes": raw,
        }
    }


def feature_proposal(
    state: Mapping[str, Any],
    *,
    chat: Callable[..., str] | None = None,
    client: Any = None,
    env: Mapping[str, str] | None = None,
    prompts: RolePrompts | None = None,
) -> dict[str, Any]:
    """5 冊への追加・横展開案を出させる（§4.1）。"""
    user = (
        "次の Issue を踏まえ、絵本ラインナップ（5 冊）への具体的な追加・横展開案を"
        "1〜3 個、触るファイル名を添えて提案してください。\n"
        f"タイトル: {state.get('issue_title', '')}\n"
        f"調査メモ:\n{state.get('research_notes', '')}"
    )
    proposal = _llm_node(
        state, chat=chat, client=client, env=env, prompts=prompts, user=user
    )
    return {"feature_proposal": proposal}


def score_priority(
    state: Mapping[str, Any],
    *,
    chat: Callable[..., str] | None = None,
    client: Any = None,
    env: Mapping[str, str] | None = None,
    prompts: RolePrompts | None = None,
) -> dict[str, Any]:
    """優先度スコア（0-100）と根拠を出させ、範囲にクランプする（§4.4）。"""
    user = (
        "次の Issue を、発達価値/40・実装容易性/25・横展開性/20・"
        "アクセシビリティ安全性/15（合計100）のルーブリックで採点し、"
        "総合スコアと内訳・根拠を述べてください。\n"
        f"タイトル: {state.get('issue_title', '')}\n"
        f"調査メモ:\n{state.get('research_notes', '')}"
    )
    raw = _llm_node(
        state, chat=chat, client=client, env=env, prompts=prompts, user=user
    )
    match = _SCORE_RE.search(raw or "")
    score = _clamp_score(int(match.group(1))) if match else SCORE_MIN
    return {"score": score, "score_rationale": (raw or "").strip()}


def format_comment(
    state: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """採点結果を §4.3 のフォーマットで Markdown コメントに整形する（純 Python）。

    先頭 2 行に必ず ``<!-- claude-score: N -->`` と ``<!-- claude-run: YYYY-MM-DD -->``
    （JST）を置く。スコア内訳は §4.4 のルーブリック軸で出す。
    """
    score = _clamp_score(int(state.get("score", 0)))
    run_date = today_jst(now)
    difficulty = state.get("difficulty") or {}
    breakdown = state.get("score_breakdown") or {}

    lines: list[str] = [
        f"<!-- claude-score: {score} -->",
        f"<!-- claude-run: {run_date} -->",
        "",
        f"## 📊 Claude 自動調査（{run_date}）",
        "",
        "### 研究根拠の補足",
        (state.get("research_notes") or "").strip() or "（調査メモなし）",
        "",
        "### 実装難易度",
        f"- レベル: **{difficulty.get('level', '不明')}**",
        f"- HTML/CSS/JS で完結: {'はい' if difficulty.get('html_css_js_feasible') else '要確認'}",
        (difficulty.get("notes") or "").strip(),
        "",
        f"### 優先度スコア: **{score} / 100**",
    ]

    if breakdown:
        lines.extend(_format_breakdown(breakdown))
    else:
        rationale = (state.get("score_rationale") or "").strip()
        if rationale:
            lines.append(rationale)

    lines.extend(
        [
            "",
            "### ラインナップへの追加提案",
            (state.get("feature_proposal") or "").strip() or "（提案なし）",
        ]
    )

    return {"rendered_comment": "\n".join(lines)}


def _format_breakdown(breakdown: Mapping[str, int]) -> list[str]:
    """採点内訳を §4.4 の日本語ラベル + 配点で行に展開する。"""
    labels = (
        ("developmental", "発達価値", 40),
        ("feasibility", "実装容易性", 25),
        ("reusability", "横展開性", 20),
        ("accessibility", "アクセシビリティ安全性", 15),
    )
    out: list[str] = []
    for key, label, full in labels:
        if key in breakdown:
            out.append(f"- {label}: {breakdown[key]}/{full}")
    return out


def privacy_check(
    state: Mapping[str, Any],
    *,
    denylist: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """整形済みコメントをプライバシーガードに通す（§8.6）。

    違反があれば ``abort=True`` にし errors に記録する（**実値はメッセージに入れない**）。
    投稿前の最終関門。
    """
    body = state.get("rendered_comment", "")
    violations = privacy.check(body, denylist=denylist, env=env)
    errors = list(state.get("errors", []))
    if violations:
        for v in violations:
            errors.append(f"privacy violation [{v.kind}]: {v.message}")
        return {"abort": True, "errors": errors}
    return {"abort": False, "errors": errors}


def post_comment(
    state: Mapping[str, Any],
    *,
    io: Any,
    dry_run: bool = False,
) -> dict[str, Any]:
    """コメントを投稿し、成功後に stage:researched を付与する（§2.1）。

    ``dry_run`` のときは GitHub への書き込みを行わず、posted_comment_url を None にする。
    ``io`` は ``common.github_io.GitHubIO`` 互換。
    """
    number = int(state["issue_number"])
    body = state["rendered_comment"]
    if dry_run:
        return {"posted_comment_url": None}

    comment = io.create_issue_comment(number, body)
    io.add_labels(number, STAGE_LABEL)
    return {"posted_comment_url": getattr(comment, "html_url", None)}


# --- LLM 応答の緩いパース ----------------------------------------------------


def _extract_level(text: str) -> str:
    """難易度応答から 低/中/高（low/med/high）を拾う。見つからなければ '中'。"""
    lowered = (text or "").lower()
    if "高" in text or "high" in lowered:
        return "高"
    if "低" in text or "low" in lowered:
        return "低"
    return "中"


def _extract_feasible(text: str) -> bool:
    """HTML/CSS/JS で完結可能と読めるか緩く判定する。"""
    if not text:
        return True
    if "不可" in text or "できない" in text or "infeasible" in text.lower():
        return False
    return True
