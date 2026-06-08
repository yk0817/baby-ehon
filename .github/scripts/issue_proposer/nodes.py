"""Proposer の純粋ノード関数群（langgraph 非依存・テスト可能）。

各ノードは ``ProposerState`` の断片（更新差分）を返す純関数に保つ。LLM 呼び出し・
GitHub 起票などの I/O は引数注入（``llm`` / ``io`` / ``today``）で差し替えられるように
し、ネットワークや実 LLM・langgraph 無しで単体テストできるようにする。
``graph.py`` だけが langgraph を import し、ここはノードの中身と分岐ヘルパに徹する。

ゲートの判定境界（設計に対応）:

- backlog_gate: 未対応 ``claude-proposed`` が N 件以上で skip（§5.4）
- novelty_gate: 既存 open / 直近 closed タイトルと重複なら再生成、最大 2 回で skip（§5.4）
- self_score_gate: 共通ルーブリック合計 60 未満 or HTML/CSS/JS 非完結で破棄（§4.4 / §5.3）

設計: docs/automation/agent-pipeline.md §5.1 / §5.3 / §5.4 / §4.4 / §5.5 / §8
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any, TypedDict

from common import privacy

# --- 定数（マジックナンバーを排除） -------------------------------------------

DEFAULT_BACKLOG_MAX = 3  # 未対応 claude-proposed の上限（§5.4）
DEFAULT_NOVELTY_MAX_ATTEMPTS = 2  # 重複時の再生成上限（§5.4）
DEFAULT_SCORE_THRESHOLD = 60  # 自己採点の合格ライン（§5.3）
PROPOSED_LABELS = ("enhancement", "research-based", "claude-proposed")  # §5.5
PROPOSED_MARKER = "claude-proposed"  # 本文先頭マーカーのキー（§5.4）

# kind → Issue 本文での表示名（§5.5）
_KIND_LABEL = {"new_book": "新しい絵本", "feature": "既存絵本への機能追加"}


# --- State スキーマ（§5.2 を素直に TypedDict 化） ------------------------------


class ProposerState(TypedDict, total=False):
    """Proposer グラフの共有状態（§5.2）。

    ``total=False`` にして、ノードが必要なキーだけを段階的に埋められるようにする。
    """

    lineup: list[str]
    existing_open_titles: list[str]
    recent_closed_titles: list[str]
    pending_proposed_count: int
    idea: dict[str, Any]
    self_score: dict[str, Any]
    issue_title: str
    issue_body: str
    created_issue_url: str | None
    errors: list[str]
    # --- 内部フラグ（分岐ヘルパが参照） ---
    skip: bool
    is_duplicate: bool
    novelty_attempts: int
    html_css_js_only: bool
    accepted: bool
    privacy_ok: bool


# 注入する LLM 呼び出しの型: (system, user) -> 応答テキスト。
LLMFn = Callable[[str, str], str]


# --- 補助: 文字列正規化 / JSON 抽出 -------------------------------------------


def normalize_title(title: str) -> str:
    """タイトルを比較用に正規化する（小文字化・空白除去・NFKC）。

    全半角・大小・空白のゆらぎを吸収し、素直な包含 / 一致で重複判定できるようにする。
    """
    normalized = unicodedata.normalize("NFKC", title or "")
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _extract_json(text: str) -> dict[str, Any]:
    """LLM 応答テキストから最初の JSON オブジェクトを抽出してパースする。

    コードフェンス（```json ... ```）や前後の地の文を許容する。パースできなければ
    ``json.JSONDecodeError`` を送出する（呼び出し側が errors に記録する）。
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("JSON オブジェクトが見つかりません", candidate, 0)
    return json.loads(candidate[start : end + 1])


# --- backlog_gate（§5.4） -----------------------------------------------------


def backlog_gate(
    state: ProposerState, *, backlog_max: int = DEFAULT_BACKLOG_MAX
) -> ProposerState:
    """未対応 ``claude-proposed`` が上限以上なら skip フラグを立てる（§5.4）。"""
    pending = int(state.get("pending_proposed_count", 0))
    skip = pending >= backlog_max
    errors = list(state.get("errors", []))
    if skip:
        errors.append(
            f"backlog_gate: 未対応 claude-proposed が {pending} 件"
            f"（上限 {backlog_max}）のため起票をスキップ"
        )
    return {"skip": skip, "errors": errors}


def route_backlog(state: ProposerState) -> str:
    """backlog_gate の分岐: skip なら ``"skip"``、余裕ありなら ``"continue"``。"""
    return "skip" if state.get("skip") else "continue"


# --- ideate（§5.3、LLM 注入） -------------------------------------------------


def ideate(state: ProposerState, *, llm: LLMFn) -> ProposerState:
    """LLM に発案させ、案 dict を state に格納する（§5.3）。

    重複時の再生成でも同じノードを通るので、``novelty_attempts`` を 1 増やす。
    JSON パースに失敗した場合は ``idea`` を空にして errors を記録する（落とさない）。
    """
    attempts = int(state.get("novelty_attempts", 0)) + 1
    errors = list(state.get("errors", []))

    system = _ideate_system()
    user = _ideate_user(state)
    raw = llm(system, user)

    try:
        idea = _extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        errors.append("ideate: LLM 応答を JSON として解釈できませんでした")
        return {"idea": {}, "novelty_attempts": attempts, "errors": errors}

    html_only = bool(idea.get("html_css_js_only", True))
    return {
        "idea": idea,
        "html_css_js_only": html_only,
        "novelty_attempts": attempts,
        "errors": errors,
    }


def _ideate_system() -> str:
    """ideate の system プロンプト末尾に付ける出力フォーマット指示。

    文言の本体（役割・制約）は prompts.py 経由で外部 Markdown から渡す。ここは
    JSON スキーマの機械的な指示だけを足す（パース可能にするため）。
    """
    return (
        "出力は次のキーを持つ JSON オブジェクト 1 個のみ:\n"
        '{"kind": "new_book"|"feature", "title": str, "summary": str, '
        '"research_basis": [str], "target_files": [str], '
        '"html_css_js_only": bool}'
    )


def _ideate_user(state: ProposerState) -> str:
    """ideate の user メッセージ（既存ラインナップ / 既存タイトルを文脈に渡す）。"""
    lineup = "、".join(state.get("lineup", [])) or "（なし）"
    open_titles = "\n".join(f"- {t}" for t in state.get("existing_open_titles", []))
    closed_titles = "\n".join(f"- {t}" for t in state.get("recent_closed_titles", []))
    return (
        f"既存ラインナップ: {lineup}\n\n"
        f"Open Issue タイトル:\n{open_titles or '（なし）'}\n\n"
        f"直近クローズ済みタイトル:\n{closed_titles or '（なし）'}\n\n"
        "これらと重複しない新案を 1 件、上記 JSON 形式で出してください。"
    )


# --- novelty_gate（§5.4） -----------------------------------------------------


def _is_duplicate(idea_title: str, known_titles: Sequence[str]) -> bool:
    """正規化したタイトル同士の包含で重複を判定する（素直な近似）。"""
    target = normalize_title(idea_title)
    if not target:
        return True  # 空タイトルは新規性なしとみなす
    for known in known_titles:
        other = normalize_title(known)
        if not other:
            continue
        if target == other or target in other or other in target:
            return True
    return False


def novelty_gate(state: ProposerState) -> ProposerState:
    """生成案が既存 open / 直近 closed と重複するか判定する（§5.4）。"""
    idea = state.get("idea", {}) or {}
    title = idea.get("title", "")
    known = [
        *state.get("existing_open_titles", []),
        *state.get("recent_closed_titles", []),
    ]
    dup = _is_duplicate(title, known)
    return {"is_duplicate": dup}


def route_novelty(
    state: ProposerState, *, max_attempts: int = DEFAULT_NOVELTY_MAX_ATTEMPTS
) -> str:
    """novelty_gate の分岐。

    - 新規 → ``"continue"``
    - 重複 & 再生成余地あり → ``"retry"``
    - 重複 & 上限到達 → ``"skip"``
    """
    if not state.get("is_duplicate"):
        return "continue"
    if int(state.get("novelty_attempts", 0)) >= max_attempts:
        return "skip"
    return "retry"


# --- self_score（LLM 注入）/ self_score_gate（§4.4 / §5.3） -------------------


def self_score(state: ProposerState, *, llm: LLMFn) -> ProposerState:
    """LLM に共通ルーブリックで自己採点させ、内訳と合計を state に入れる（§4.4）。"""
    errors = list(state.get("errors", []))
    system = _self_score_system()
    user = _self_score_user(state)
    raw = llm(system, user)

    try:
        score = _extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        errors.append("self_score: LLM 応答を JSON として解釈できませんでした")
        return {"self_score": {}, "errors": errors}

    return {"self_score": score, "errors": errors}


def _self_score_system() -> str:
    return (
        "次の共通ルーブリックで案を採点し、JSON 1 個のみを出力:\n"
        "発達価値/40, 実装容易性/25, 横展開性/20, アクセシビリティ・安全性/15。\n"
        '{"dev_value": int, "feasibility": int, "reusability": int, '
        '"a11y_safety": int, "total": int}'
    )


def _self_score_user(state: ProposerState) -> str:
    idea = state.get("idea", {}) or {}
    return (
        f"タイトル: {idea.get('title', '')}\n"
        f"種別: {idea.get('kind', '')}\n"
        f"概要: {idea.get('summary', '')}\n"
        f"研究根拠: {idea.get('research_basis', [])}\n"
        f"想定影響ファイル: {idea.get('target_files', [])}"
    )


def self_score_gate(
    state: ProposerState, *, threshold: int = DEFAULT_SCORE_THRESHOLD
) -> ProposerState:
    """合計が閾値以上かつ HTML/CSS/JS 完結なら accept、さもなくば drop（§5.3）。"""
    score = state.get("self_score", {}) or {}
    total = int(score.get("total", 0))
    html_only = bool(state.get("html_css_js_only", True))
    accepted = total >= threshold and html_only

    errors = list(state.get("errors", []))
    if not accepted:
        reason = (
            "HTML/CSS/JS で完結しない"
            if not html_only
            else f"自己採点 {total} 点が合格ライン {threshold} 未満"
        )
        errors.append(f"self_score_gate: 破棄（{reason}）")
    return {"accepted": accepted, "errors": errors}


def route_self_score(state: ProposerState) -> str:
    """self_score_gate の分岐: ``"accept"`` / ``"drop"``。"""
    return "accept" if state.get("accepted") else "drop"


# --- draft_issue（§5.5） ------------------------------------------------------


def draft_issue(state: ProposerState, *, today: str) -> ProposerState:
    """採用された案から起票用のタイトル・本文を組み立てる（§5.5）。

    ``today`` は JST の ``YYYY-MM-DD``（run.py から JST 現在日を渡す）。
    """
    idea = state.get("idea", {}) or {}
    title = idea.get("title", "（無題）")
    kind = idea.get("kind", "feature")
    summary = idea.get("summary", "")
    research = idea.get("research_basis", []) or []
    files = idea.get("target_files", []) or []

    kind_label = _KIND_LABEL.get(kind, kind)
    research_lines = "\n".join(f"- {r}" for r in research) or "- （根拠未記載）"
    file_lines = "\n".join(f"- `{f}`" for f in files) or "- （未特定）"

    issue_title = f"提案: {title}"
    issue_body = _ISSUE_BODY_TEMPLATE.format(
        marker=today,
        title=title,
        kind_label=kind_label,
        research_lines=research_lines,
        summary=summary,
        file_lines=file_lines,
        labels=" ".join(f"`{label}`" for label in PROPOSED_LABELS),
    )
    return {"issue_title": issue_title, "issue_body": issue_body}


_ISSUE_BODY_TEMPLATE = """<!-- claude-proposed: {marker} -->

## 提案: {title}

**種別**: {kind_label}

### 背景・ねらい（発達研究）
{research_lines}

### 提案内容
{summary}

### 想定影響ファイル
{file_lines}

### 受け入れ条件（人間が後で詰める叩き）
- [ ] 対象冊で挙動を確認
- [ ] `__NAME__` プレースホルダ以外に人名が入らない
- [ ] README ラインナップ / 構成の更新要否を判断

---
この Issue は Claude（リサーチャー Proposer）が自動起票しました。\
**内容は人間が精査してから着手してください。**
ラベル: {labels}
"""


# --- privacy_check（§8） ------------------------------------------------------


def privacy_check(
    state: ProposerState, *, denylist: Sequence[str] = ()
) -> ProposerState:
    """起票直前にタイトル + 本文をプライバシーガードに通す（§8）。

    違反があれば ``privacy_ok=False``。errors には ``Violation.message``（実値を
    含まない）だけを積み、検出した秘匿値は決して露出しない。
    """
    text = f"{state.get('issue_title', '')}\n{state.get('issue_body', '')}"
    violations = privacy.check(text, denylist=denylist)
    errors = list(state.get("errors", []))
    if violations:
        for v in violations:
            errors.append(f"privacy_check: {v.kind} — {v.message}")
        return {"privacy_ok": False, "errors": errors}
    return {"privacy_ok": True, "errors": errors}


def route_privacy(state: ProposerState) -> str:
    """privacy_check の分岐: ``"ok"`` / ``"abort"``。"""
    return "ok" if state.get("privacy_ok") else "abort"


# --- create_issue（§5.1） -----------------------------------------------------


def create_issue(state: ProposerState, *, io: Any, dry_run: bool) -> ProposerState:
    """``claude-proposed`` ラベル付きで Issue を起票する（§5.1）。

    ``dry_run`` のときは起票せず、タイトル・本文・ラベルを stdout に出すだけにする。
    ``io`` は ``common.github_io.GitHubIO`` 互換（``create_issue`` を持つ）。
    """
    title = state.get("issue_title", "")
    body = state.get("issue_body", "")

    if dry_run:
        print("=== [DRY_RUN] create_issue（起票しません） ===")
        print(f"title : {title}")
        print(f"labels: {', '.join(PROPOSED_LABELS)}")
        print("body  :")
        print(body)
        return {"created_issue_url": None}

    created = io.create_issue(title=title, body=body, labels=list(PROPOSED_LABELS))
    url = getattr(created, "html_url", None)
    return {"created_issue_url": url}
