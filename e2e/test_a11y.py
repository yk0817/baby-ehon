"""アクセシビリティ自動チェック（axe-core）の E2E（Issue #59）。

視覚発達期の子ども向けとして、コントラスト・操作対象の明確さ・ARIA の妥当性を自動で担保する。

- Contract: 本棚と各ブックの初期表示に axe-core を当て、**許容例外（allowlist）以外の違反が無い**。
  コントラスト比違反（axe の color-contrast, serious）もこの網に含まれる。
- Contract: 主要操作対象（鍵・ナビ・ホーム・カメラ）に **aria-label** が付き、**フォーカス可能**。
  フォーカス可視化は ``shared/ehon.css`` の ``:focus-visible`` で担保する。

許容例外は **黙って無視せず明示**する（``_ALLOWLIST``）。axe は ``axe-playwright-python``
同梱の axe-core を使い、CDN 非依存でオフライン実行する。
"""

from __future__ import annotations

import pytest
from axe_playwright_python.sync_playwright import Axe

from pages import BOOK_SLUGS, open_book, open_shelf

#: 既知の許容例外（rule id → 理由）。黙って無視せず、ここに理由付きで明示する。
_ALLOWLIST: dict[str, str] = {
    # 1 歳児の誤操作・誤拡大を防ぐため viewport に user-scalable=no を意図的に設定。
    # 拡大縮小を使う場面が無い対象児向けなので、この moderate 違反は許容する。
    "meta-viewport": "user-scalable=no は誤操作防止の意図的設計（対象児に拡大縮小は不要）",
}

#: 検査する axe ルール集合。WCAG 2.0/2.1 の A・AA に絞る。
#: best-practice 系の非 WCAG ルール（環境差・axe バージョン差で揺れやすい）を除外しつつ、
#: color-contrast 等の重大ルールは WCAG タグに含まれるので網羅できる。新ルール追加による
#: CI のフレークも抑えられる。
_WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

#: 主要操作対象（aria-label とフォーカス可能性を保証する）。
_MAIN_CONTROLS = (
    ".home-btn",
    ".nav-btn--prev",
    ".nav-btn--next",
    ".lock-btn",
    "#cam-toggle",
)


def _violations_outside_allowlist(page) -> list[dict]:
    """WCAG A/AA に絞って axe を実行し、allowlist に載っていない違反だけを返す。"""
    results = Axe().run(
        page, options={"runOnly": {"type": "tag", "values": _WCAG_TAGS}}
    )
    return [
        v
        for v in results.response.get("violations", [])
        if v.get("id") not in _ALLOWLIST
    ]


def _format(violations: list[dict]) -> str:
    return "\n".join(
        f"  [{v.get('impact')}] {v.get('id')}: {v.get('help')} "
        f"(nodes={len(v.get('nodes', []))})"
        for v in violations
    )


def test_shelf_has_no_unallowlisted_a11y_violations(page, base_url):
    """本棚の初期表示に allowlist 外の a11y 違反が無い。"""
    open_shelf(page, base_url)
    bad = _violations_outside_allowlist(page)
    assert not bad, "本棚に未許容の a11y 違反:\n" + _format(bad)


@pytest.mark.parametrize("slug", BOOK_SLUGS)
def test_book_has_no_unallowlisted_a11y_violations(page, base_url, slug):
    """各ブックの初期表示に allowlist 外の a11y 違反が無い（コントラスト違反含む）。"""
    open_book(page, base_url, slug)
    bad = _violations_outside_allowlist(page)
    assert not bad, f"{slug} に未許容の a11y 違反:\n" + _format(bad)


@pytest.mark.parametrize("selector", _MAIN_CONTROLS)
def test_main_control_has_aria_label_and_is_focusable(page, base_url, selector):
    """主要操作対象に aria-label が付き、フォーカスできる（キーボード操作の前提）。"""
    open_book(page, base_url, BOOK_SLUGS[0])
    el = page.locator(selector)
    aria = el.get_attribute("aria-label") or ""
    assert aria.strip() != "", f"{selector} に aria-label が無い"
    assert "__NAME__" not in aria, f"{selector} の aria-label に __NAME__ が残留"

    el.focus()
    focused = page.evaluate(
        "(sel) => document.activeElement === document.querySelector(sel)", selector
    )
    assert focused, f"{selector} にフォーカスできない"
