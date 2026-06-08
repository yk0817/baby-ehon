"""Child Reviewer の純粋ノード関数群（langgraph / Playwright 非依存）。

各ノードは ``ChildReviewState`` の断片（更新差分）を返す純関数に保つ。ブラウザ操作
（Playwright での起動・スクショ・静的配信）は ``browser.py`` に隔離し、ここからは
**関数注入** で受ける。これにより、Playwright / chromium / langgraph / 実 LLM・ネット
ワーク無しで本モジュールを単体テストできる。``graph.py`` だけが langgraph を import し、
``browser.py`` だけが Playwright を遅延 import する。

ノードの流れ（§7.1）::

    checkout_pr → seed_baby_js → serve_static → detect_changed_books → capture
    → read_code_diff → judge(Vision) → score_rubric → format_review → privacy_check
    →(違反 abort) upload_artifacts → post_pr_comment

設計方針:

- LLM（Vision judge）・GitHub I/O・ブラウザ操作・ファイル系副作用は引数注入で差し替え可能。
- ルーブリック（fun/clarity/safety/consistency）は各 0-5 にクランプする。
- privacy_check は ``common.privacy`` に委譲し、違反時は **実値を露出しない**（§8.6）。
- post_pr_comment は **comment のみ**（Approve / Request changes の review state は付けない、§8.4）。
- 二重起動防止: PR コメントに当日 ``child-review-run`` マーカーがあれば skip（§7.6）。

設計: docs/automation/agent-pipeline.md §7 / §8.4 / §8.5 / §2.1
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from common import privacy, score_parser

# --- 定数（マジックナンバー / 文字列を排除） ----------------------------------

#: JST（コメント先頭の child-review-run 日付・dedupe 判定に使う、§7.5 / §7.6）
JST = timezone(timedelta(hours=9))

#: ルーブリック各軸の上下限（§7.4）
RUBRIC_MIN = 0
RUBRIC_MAX = 5

#: ルーブリックの軸（キー → 日本語ラベル、§7.4）。表示順もこの順で固定。
RUBRIC_AXES: tuple[tuple[str, str], ...] = (
    ("fun", "楽しさ"),
    ("clarity", "わかりやすさ"),
    ("safety", "安全性"),
    ("consistency", "一貫性"),
)

#: stage:child-reviewed ラベル（所見投稿成功後に対象 Issue へ付与、§2.1）
STAGE_LABEL = "stage:child-reviewed"

#: 配信・読込で対象にしないトップレベルディレクトリ（§7.7）。
EXCLUDED_TOP_DIRS = (".github", "docs", ".git")

#: PR 本文の ``Closes #N`` 記法（GitHub の close キーワードを緩く拾う）。
_CLOSES_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*#(\d+)",
    re.IGNORECASE,
)


class ChildReviewState(TypedDict, total=False):
    """Child Reviewer グラフの共有状態（§7.2）。

    ``total=False`` にして、ノードが必要なキーだけを段階的に埋められるようにする。
    """

    pr_number: int
    branch: str
    pr_body: str
    changed_books: list[str]  # ["hikouki", ...]
    screenshots: list[dict]  # [{book, viewport, phase, path}]
    code_excerpts: dict[str, str]  # path -> diff/contents
    raw_review: str  # judge が返した所見の生テキスト
    findings: list[dict]  # [{aspect, observation, severity}]
    rubric: dict  # {fun, clarity, safety, consistency} 各0-5
    rendered_review: str
    artifact_url: str | None
    posted_comment_url: str | None
    errors: list[str]
    # --- 内部フラグ（分岐ヘルパが参照） ---
    skip: bool
    abort: bool


# 注入する Vision LLM 呼び出しの型: (system, user, image_urls) -> 応答テキスト。
JudgeFn = Callable[[str, str, Sequence[str]], str]


# --- 補助関数 ----------------------------------------------------------------


def today_jst(now: datetime | None = None) -> str:
    """JST の現在日を ``YYYY-MM-DD`` で返す（マーカー用、§7.5）。"""
    moment = datetime.now(JST) if now is None else now
    return moment.astimezone(JST).strftime("%Y-%m-%d")


def _clamp_rubric(value: Any) -> int:
    """ルーブリック値を [RUBRIC_MIN, RUBRIC_MAX] の int にクランプする。

    数値でない / None は最小値に倒す（壊れた LLM 応答でパイプラインを止めない）。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return RUBRIC_MIN
    return max(RUBRIC_MIN, min(RUBRIC_MAX, number))


def extract_closes_issue(pr_body: str) -> int | None:
    """PR 本文の ``Closes #N`` 記法から対象 Issue 番号を 1 つ拾う（§2.1）。

    複数あれば最初の 1 件。見つからなければ None。
    """
    match = _CLOSES_RE.search(pr_body or "")
    return int(match.group(1)) if match else None


def has_today_review_marker(
    comment_bodies: Sequence[str], *, now: datetime | None = None
) -> bool:
    """コメント群に当日（JST）の ``child-review-run`` マーカーがあるか（§7.6）。

    抽出は ``common.score_parser.parse_child_review_run`` に委譲する。
    """
    today = today_jst(now)
    for body in comment_bodies:
        if score_parser.parse_child_review_run(body or "") == today:
            return True
    return False


# --- detect_changed_books（§7.1 / §7.7） --------------------------------------


def detect_changed_books(
    diff_text: str, *, known_books: Sequence[str] = ()
) -> list[str]:
    """git diff テキストから変更された絵本ディレクトリ名を特定する（純関数）。

    - ``diff --git a/<dir>/... b/<dir>/...`` 行や ``+++ b/<dir>/...`` 行から
      トップレベルディレクトリを拾う。
    - ``.github`` / ``docs`` / ``.git`` は対象外（§7.7）。``shared`` も冊ではないので除外。
    - ``known_books`` を渡すと、その集合に含まれるものだけに絞る（誤検出抑制）。
    - 1 件も該当しなければ空リスト（呼び出し側が本棚 index.html にフォールバック）。
    結果はソート済み・重複排除で決定的にする。
    """
    found: set[str] = set()
    for raw in diff_text.splitlines():
        line = raw.strip()
        for token in re.findall(r"[ab]/([^/\s]+)/", line):
            if token in EXCLUDED_TOP_DIRS or token == "shared":
                continue
            if known_books and token not in known_books:
                continue
            found.add(token)
    return sorted(found)


# --- judge（Vision LLM 注入、§7.3 / §7.4） ------------------------------------


def judge(
    state: Mapping[str, Any],
    *,
    judge_fn: JudgeFn,
    system: str = "",
) -> dict[str, Any]:
    """スクショ画像群とコード差分を Vision LLM に渡し、所見テキストを得る（§7.3）。

    ``judge_fn`` は ``(system, user, image_urls) -> str``。画像 URL は
    ``state['screenshots']`` の各 ``path`` を ``file://`` URL 化して渡す。
    所見の生テキストを ``raw_review`` に格納する（score_rubric / format_review が使う）。
    """
    errors = list(state.get("errors", []))
    screenshots = state.get("screenshots", []) or []
    image_urls = _screenshot_urls(screenshots)
    user = _judge_user(state)

    try:
        review = judge_fn(system, user, image_urls)
    except Exception as exc:  # noqa: BLE001  judge 失敗で全体を止めない
        errors.append(f"judge: Vision LLM 呼び出しに失敗（{type(exc).__name__}）")
        return {"raw_review": "", "errors": errors}

    return {"raw_review": review or "", "errors": errors}


def _screenshot_urls(screenshots: Sequence[Mapping[str, Any]]) -> list[str]:
    """スクショ dict 列から ``file://`` 画像 URL 列を作る（path を持つものだけ）。"""
    urls: list[str] = []
    for shot in screenshots:
        path = shot.get("path")
        if path:
            urls.append(f"file://{path}")
    return urls


def _judge_user(state: Mapping[str, Any]) -> str:
    """judge の user メッセージ（対象冊・スクショ一覧・コード差分を文脈に渡す）。"""
    books = "、".join(state.get("changed_books", [])) or "（本棚 index.html）"
    shots = state.get("screenshots", []) or []
    shot_lines = "\n".join(
        f"- {s.get('book', '?')} / {s.get('viewport', '?')} / {s.get('phase', '?')}"
        for s in shots
    )
    excerpts = state.get("code_excerpts", {}) or {}
    code_lines = "\n\n".join(
        f"### {path}\n```\n{content}\n```" for path, content in excerpts.items()
    )
    return (
        f"対象の絵本: {books}\n\n"
        "添付スクリーンショット（320 / 768 / 1024、各 初期/タップ後/送り後）:\n"
        f"{shot_lines or '（なし）'}\n\n"
        "1 歳児の発達視点（楽しさ / わかりやすさ / 安全性 / 一貫性）で所見を述べてください。\n"
        "良かった点と気になった点を分け、やさしい言葉で書いてください。\n\n"
        f"変更されたコード:\n{code_lines or '（差分なし）'}"
    )


# --- score_rubric（§7.4） -----------------------------------------------------


def score_rubric(
    state: Mapping[str, Any],
    *,
    score_fn: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """所見テキストからルーブリック（各 0-5）を組み立て、クランプする（§7.4）。

    ``score_fn`` を渡すと所見テキストから生スコア dict を抽出させ（LLM 由来でも可）、
    未指定なら ``raw_review`` に埋め込まれた ``fun=N`` 形式のペアを緩く拾う。
    いずれの経路でも最終値は [0, 5] にクランプして 4 軸すべてを必ず埋める。
    """
    raw_review = str(state.get("raw_review", ""))
    if score_fn is not None:
        raw_scores = dict(score_fn(raw_review) or {})
    else:
        raw_scores = _parse_inline_scores(raw_review)

    rubric = {key: _clamp_rubric(raw_scores.get(key)) for key, _label in RUBRIC_AXES}
    return {"rubric": rubric}


def _parse_inline_scores(text: str) -> dict[str, int]:
    """所見本文に ``fun=4`` のような軸スコアが書かれていれば拾う（緩い抽出）。"""
    scores: dict[str, int] = {}
    for key, _label in RUBRIC_AXES:
        match = re.search(rf"{key}\s*[=:＝：]\s*(-?\d+)", text, re.IGNORECASE)
        if match:
            scores[key] = int(match.group(1))
    return scores


# --- format_review（§7.5） ----------------------------------------------------

_REVIEW_TEMPLATE = """<!-- child-review-score: {score_marker} -->
<!-- child-review-run: {run_date} -->

## 👶 こどもレビュワーの所見（自動・所見のみ / 承認ではありません）

対象: {target}（320 / 768 / 1024 で確認）
スクリーンショット: {artifact}

{observations}

### ルーブリック
| {label_row} |
|{sep_row}|
| {score_row} |

---
これは Claude（こどもレビュワー）が 1 歳児視点で生成した**所見**です。\
Approve ではありません。最終判断は人間が行ってください。
"""


def format_review(
    state: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """所見 + ルーブリックを §7.5 のフォーマットで Markdown に整形する（純 Python）。

    先頭 2 行に必ず ``<!-- child-review-score: ... -->`` と
    ``<!-- child-review-run: YYYY-MM-DD -->``（JST）を置く。**所見のみ・Approve しない**旨と
    artifact リンクを必ず含める。
    """
    run_date = today_jst(now)
    rubric = state.get("rubric", {}) or {}
    normalized = {key: _clamp_rubric(rubric.get(key)) for key, _label in RUBRIC_AXES}

    score_marker = " ".join(f"{key}={normalized[key]}" for key, _label in RUBRIC_AXES)
    label_row = " | ".join(label for _key, label in RUBRIC_AXES)
    sep_row = "|".join("---" for _ in RUBRIC_AXES)
    score_row = " | ".join(f"{normalized[key]}/5" for key, _label in RUBRIC_AXES)

    books = state.get("changed_books", []) or []
    target = "、".join(f"`{b}`" for b in books) if books else "本棚 `index.html`"

    artifact_url = state.get("artifact_url")
    artifact = (
        f"[Actions artifact]({artifact_url})"
        if artifact_url
        else "（このランの Actions artifact を参照）"
    )

    observations = (str(state.get("raw_review", "")).strip()) or "（所見なし）"

    rendered = _REVIEW_TEMPLATE.format(
        score_marker=score_marker,
        run_date=run_date,
        target=target,
        artifact=artifact,
        observations=observations,
        label_row=label_row,
        sep_row=sep_row,
        score_row=score_row,
    )
    return {"rendered_review": rendered}


# --- privacy_check（§8.6） ----------------------------------------------------


def privacy_check(
    state: Mapping[str, Any],
    *,
    denylist: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """整形済み所見をプライバシーガードに通す（§8.6）。

    違反があれば ``abort=True`` にし errors に記録する（**実値はメッセージに入れない**）。
    投稿前の最終関門。
    """
    body = state.get("rendered_review", "")
    violations = privacy.check(body, denylist=denylist, env=env)
    errors = list(state.get("errors", []))
    if violations:
        for v in violations:
            errors.append(f"privacy violation [{v.kind}]: {v.message}")
        return {"abort": True, "errors": errors}
    return {"abort": False, "errors": errors}


def route_privacy(state: Mapping[str, Any]) -> str:
    """privacy_check の分岐: ``"ok"`` / ``"abort"``。"""
    return "abort" if state.get("abort") else "ok"


# --- post_pr_comment（§7.5 / §2.1 / §8.4） ------------------------------------


def post_pr_comment(
    state: Mapping[str, Any],
    *,
    io: Any,
    dry_run: bool = False,
) -> dict[str, Any]:
    """所見を PR にコメント投稿し、対象 Issue に stage:child-reviewed を付与する。

    - PR は issue コメント API で投稿できるため ``create_issue_comment(pr_number, ...)``。
    - **review state（Approve / Request changes）は付けない**（§8.4）。comment のみ。
    - 投稿後、PR 本文の ``Closes #N`` から対象 Issue を辿り stage:child-reviewed 付与（§2.1）。
    - ``dry_run`` のときは GitHub への書き込みを一切行わない。
    ``io`` は ``common.github_io.GitHubIO`` 互換。
    """
    pr_number = int(state["pr_number"])
    body = state["rendered_review"]
    if dry_run:
        return {"posted_comment_url": None}

    comment = io.create_issue_comment(pr_number, body)

    target_issue = extract_closes_issue(state.get("pr_body", ""))
    if target_issue is not None:
        io.add_labels(target_issue, STAGE_LABEL)

    return {"posted_comment_url": getattr(comment, "html_url", None)}
