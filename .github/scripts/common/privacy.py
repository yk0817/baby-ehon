"""baby-ehon 自動化の単一プライバシーガード。

公開リポジトリのため、生成テキスト（コメント / コード / PR 本文 / コミットメッセージ）に
本名・連絡先・住所などを残さない。全役は GitHub への書き込み直前にここを通す。

防御は 3 本立て:

1. hard-banned regex  — メール / 電話 / 住所っぽい文字列（コード組込）
2. configurable denylist — env ``BABY_EHON_NAME_DENYLIST``（カンマ区切り。値はコードに書かない）
3. __NAME__ positive assert — ``*/config.js`` の talks 呼びかけが ``__NAME__`` でなければエラー

重要: 違反を表す ``Violation.message`` には **検出した実値を入れない**
（ログ / Issue / PR に流れても秘匿が漏れないようにするため。設計 §8.6）。

設計: docs/automation/agent-pipeline.md §8.2 / §8.3 / §8.6
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DENYLIST_ENV = "BABY_EHON_NAME_DENYLIST"
PLACEHOLDER = "__NAME__"
MASK = "***"

# --- hard-banned パターン（コード組込） ---------------------------------------

# メールアドレス
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 日本の電話番号（先頭 0 or +81 を要求して誤検知を抑える）。
# 例: 090-1234-5678 / 03-1234-5678 / 09012345678 / +81-90-1234-5678
_PHONE_RE = re.compile(
    r"(?<![\d-])"
    r"(?:\+81[-\s]?\d{1,4}|0\d{1,4})"
    r"[-\s]?\d{1,4}[-\s]?\d{3,4}"
    r"(?![\d-])"
)

# 住所っぽい字面（丁目 / 番地 / 号 の数字付きマーカー）
_ADDRESS_RE = re.compile(r"\d+\s*丁目|\d+\s*番地|\d+\s*番\s*\d+\s*号")

# talks の「呼びかけ改行」: <head>、\n（JS ソース中では読点 + バックスラッシュ n）。
# 主語＋読点（例: 'でんしゃ、はしる'）は \n を伴わないので誤検知しない。
_VOCATIVE_RE = re.compile(r"(?P<head>[^'\"`,、\n]{1,24})、\\n")


@dataclass(frozen=True)
class Violation:
    """プライバシー違反 1 件。``message`` に実値は含めない。"""

    kind: str  # "email" | "phone" | "address" | "denylist" | "name_placeholder"
    message: str


def load_denylist(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """env から個人名 denylist を読む。カンマ区切り・strip・重複排除・ソート。"""
    source = os.environ if env is None else env
    raw = source.get(DENYLIST_ENV, "")
    names = {name.strip() for name in raw.split(",") if name.strip()}
    return tuple(sorted(names))


# 名前トークン判定で「直後がこれらの敬称なら名前」とみなす（平仮名でも許容）。
_HONORIFICS = ("ちゃん", "ちゃま", "ちゃ", "くん", "きゅん", "さん", "さま")


def _is_hiragana(ch: str) -> bool:
    # 平仮名ブロック U+3040–U+309F
    return bool(ch) and "぀" <= ch <= "ゟ"


def _name_appears_as_token(text: str, name: str) -> bool:
    """denylist 名が「名前トークン」として現れるか（部分文字列の過検出を抑える）。

    denylist の値は LLM に渡していない（Secret）ため、生成テキストに出る一致は
    多くが偶然の部分文字列（例: ``はな`` が ``はなび``＝花火 に、``やま`` が
    ``やまみち``＝山道 に一致）。そこで **直後が平仮名で語が連続する場合は名前と
    みなさない**。ただし直後が敬称（ちゃん / くん / さん 等）なら名前とみなす。
    直前方向は制限しない（``わたしはたろう`` のような取りこぼしを避けるため）。
    """
    low_text = text.lower()
    low_name = name.lower()
    if not low_name:
        return False
    start = 0
    while True:
        idx = low_text.find(low_name, start)
        if idx == -1:
            return False
        end = idx + len(low_name)
        after = low_text[end] if end < len(low_text) else ""
        following = low_text[end : end + 4]
        if not _is_hiragana(after) or any(following.startswith(h) for h in _HONORIFICS):
            return True
        start = idx + 1


def scan_text(text: str, denylist: Sequence[str] = ()) -> list[Violation]:
    """テキストから hard-banned パターンと denylist 名を検出する。"""
    violations: list[Violation] = []

    if _EMAIL_RE.search(text):
        violations.append(Violation("email", "メールアドレスらしき文字列を検出"))
    if _PHONE_RE.search(text):
        violations.append(Violation("phone", "電話番号らしき文字列を検出"))
    if _ADDRESS_RE.search(text):
        violations.append(Violation("address", "住所らしき文字列を検出"))

    if any(_name_appears_as_token(text, name) for name in denylist if name):
        violations.append(
            Violation("denylist", "denylist の個人名を検出（値はマスク）")
        )

    return violations


def assert_name_placeholder(config_js: str) -> list[Violation]:
    """``*/config.js`` の呼びかけが ``__NAME__`` を使っているか検査する。

    呼びかけ改行 ``<head>、\\n`` の ``head`` が ``__NAME__`` でなければ違反とする。
    （実名がハードコードされていないかの backstop。denylist が空でも効く。）
    """
    violations: list[Violation] = []
    for match in _VOCATIVE_RE.finditer(config_js):
        if match.group("head").strip() != PLACEHOLDER:
            offset = match.start()
            violations.append(
                Violation(
                    "name_placeholder",
                    f"talks の呼びかけが {PLACEHOLDER} ではありません"
                    f"（位置 {offset}、要確認・実名はマスク）",
                )
            )
    return violations


def redact(text: str, denylist: Sequence[str] = ()) -> str:
    """ログ出力前に機密（メール / 電話 / 住所 / denylist 名）をマスクする。"""
    out = _EMAIL_RE.sub(MASK, text)
    out = _PHONE_RE.sub(MASK, out)
    out = _ADDRESS_RE.sub(MASK, out)
    for name in denylist:
        if name:
            out = re.sub(re.escape(name), MASK, out, flags=re.IGNORECASE)
    return out


def check(
    text: str,
    *,
    denylist: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Violation]:
    """テキストを検査する便利関数。``denylist`` 未指定なら env から読む。"""
    names = load_denylist(env) if denylist is None else denylist
    return scan_text(text, names)
