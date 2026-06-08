"""コメント本文に埋め込まれた機械可読マーカーを抽出する。

スコアは Issue / PR コメントの先頭に HTML コメントとして埋め込み永続化する
（DB を持たず、GitHub 上のコメントだけで状態を運ぶ設計）。本モジュールはその
逆方向（コメント文字列 → 構造化値）の抽出を担う。

マーカー仕様（設計 §4.3 / §7.5）:

- ``<!-- claude-score: 87 -->``                                    → int
- ``<!-- claude-run: 2026-05-25 -->``                              → 日付文字列
- ``<!-- child-review-score: fun=4 clarity=3 safety=5 consistency=4 -->`` → dict[str, int]
- ``<!-- child-review-run: 2026-05-25 -->``                        → 日付文字列

設計方針:

- 空白ゆらぎ（``<!--claude-score:87-->`` 等）を許容する。
- 不正値（数値でない等）は **例外にせず None / スキップ** にする
  （壊れたコメント 1 件でパイプライン全体を止めないため）。
- 「複数コメントから最新を選ぶ」ヘルパは、本文 + 作成時刻のタプル列を引数注入で
  受け取り、I/O から切り離してテスト可能にする。

設計: docs/automation/agent-pipeline.md §4.3 / §7.5
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TypeVar

# 単一マーカー（int 値）: <!-- claude-score: 87 -->
_CLAUDE_SCORE_RE = re.compile(r"<!--\s*claude-score\s*:\s*(-?\d+)\s*-->")
# 単一マーカー（日付文字列）: <!-- claude-run: 2026-05-25 -->
_CLAUDE_RUN_RE = re.compile(r"<!--\s*claude-run\s*:\s*([^\s][^>]*?)\s*-->")
# 複合マーカー（key=value ペア群）: <!-- child-review-score: fun=4 ... -->
_CHILD_REVIEW_SCORE_RE = re.compile(
    r"<!--\s*child-review-score\s*:\s*(.*?)\s*-->", re.DOTALL
)
_CHILD_REVIEW_RUN_RE = re.compile(r"<!--\s*child-review-run\s*:\s*([^\s][^>]*?)\s*-->")
# child-review-score 内の key=value ペア（value は整数のみ採用）
_PAIR_RE = re.compile(r"(\w+)\s*=\s*(-?\d+)")

# created_at の型は比較可能でありさえすればよい（str / datetime など）。
_Sortable = TypeVar("_Sortable")


def parse_claude_score(body: str) -> int | None:
    """``<!-- claude-score: N -->`` から int を抽出する。無ければ / 不正なら None。

    複数あるときは **先頭** を採る（1 コメント内で重複は想定しないが安全側）。
    """
    match = _CLAUDE_SCORE_RE.search(body)
    if match is None:
        return None
    return int(match.group(1))


def parse_claude_run(body: str) -> str | None:
    """``<!-- claude-run: 2026-05-25 -->`` から日付文字列を抽出する。"""
    match = _CLAUDE_RUN_RE.search(body)
    return match.group(1).strip() if match else None


def parse_child_review_score(body: str) -> dict[str, int] | None:
    """``<!-- child-review-score: fun=4 ... -->`` から dict[str, int] を抽出する。

    整数として読めない値のペアは黙って除外する。有効ペアが 0 件なら None。
    """
    match = _CHILD_REVIEW_SCORE_RE.search(body)
    if match is None:
        return None
    pairs = {key: int(value) for key, value in _PAIR_RE.findall(match.group(1))}
    return pairs or None


def parse_child_review_run(body: str) -> str | None:
    """``<!-- child-review-run: 2026-05-25 -->`` から日付文字列を抽出する。"""
    match = _CHILD_REVIEW_RUN_RE.search(body)
    return match.group(1).strip() if match else None


def _latest(
    comments: Sequence[tuple[str, _Sortable]],
    extractor,
):
    """created_at 降順で最初にマーカーが取れたコメントの抽出値を返す。

    ``extractor`` はコメント本文を受け、抽出値 or None を返す関数。
    """
    for body, _created_at in sorted(comments, key=lambda item: item[1], reverse=True):
        value = extractor(body)
        if value is not None:
            return value
    return None


def latest_claude_score(
    comments: Sequence[tuple[str, _Sortable]],
) -> int | None:
    """複数コメントのうち、最新（created_at 最大）の claude-score を返す。"""
    return _latest(comments, parse_claude_score)


def latest_child_review_score(
    comments: Sequence[tuple[str, _Sortable]],
) -> dict[str, int] | None:
    """複数コメントのうち、最新の child-review-score を返す。"""
    return _latest(comments, parse_child_review_score)
