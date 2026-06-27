"""AGENTS.md（足場① Instructions）の必須項目テスト。

Contract: maker が毎回読む指示書に、baby-ehon 固有の不可欠ルールが必ず含まれること。
ドキュメントは自由文だが、**抜けると事故になる方針**（プライバシー・契約不可侵・スコープ・
緑まで・素の Web 限定）はキーワードで存在を固定する。CLAUDE.md と重複させず参照する方針も含む。

なぜこの挙動が必要か: maker はまっさらで起動するため、指示書から方針が落ちると
実名混入や契約改変など取り返しのつかない出力に繋がる。回帰として固定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_AGENTS_MD = Path(__file__).resolve().parents[1] / "harness" / "AGENTS.md"


@pytest.fixture(scope="module")
def text() -> str:
    return _AGENTS_MD.read_text(encoding="utf-8")


def test_exists() -> None:
    assert _AGENTS_MD.is_file()


@pytest.mark.parametrize(
    ("needle", "why"),
    [
        ("__NAME__", "実名禁止・プレースホルダ必須"),
        ("契約", "受け入れ e2e は契約"),
        ("書き換え", "契約テストの改変禁止"),
        ("HTML", "素の Web（HTML/CSS/JS）限定"),
        ("verify", "緑は verify で判定（自己採点しない）"),
        ("CLAUDE.md", "プライバシー方針は重複させず参照する"),
    ],
)
def test_contains_required_policy(text: str, needle: str, why: str) -> None:
    assert needle in text, f"AGENTS.md に『{needle}』が無い（{why}）"


@pytest.mark.parametrize(
    ("needle", "why"),
    [
        ("本棚掲載", "ゲート① 必須シナリオ: book-card に出る"),
        ("ページ送り4経路", "ゲート① 必須シナリオ: 次へ/スワイプ/ArrowRight/自動進行"),
        ("チャイルドロック", "ゲート① 必須シナリオ: 施錠→長押し解錠"),
        ("a11y", "ゲート① 必須シナリオ: コントラスト等"),
    ],
)
def test_lists_required_e2e_scenarios(text: str, needle: str, why: str) -> None:
    # Contract: maker が新ブックで満たすべき必須シナリオ網羅（§3.5 ①）を明示する
    assert needle in text, f"AGENTS.md にシナリオ『{needle}』が無い（{why}）"


def test_includes_flow_diagram(text: str) -> None:
    # Contract: 理解を助けるため maker の作業フローを Mermaid 図で示す
    assert "```mermaid" in text


def test_no_contact_info_leak(text: str) -> None:
    # 指示書自身も公開物。メール/電話/住所らしき字面を含めない
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".github" / "scripts"))
    from common import privacy

    assert privacy.scan_text(text, denylist=()) == []
