"""チャイルドロックの E2E（Issue #56）。

誤操作で絵本から抜けないチャイルドロック（安全要件）が効くことを保証する。

- Contract: 鍵ボタンで施錠すると ``.parent-nav.is-locked`` になり、ナビ（ホーム/前/次）は
  ``pointer-events: none`` で無効化される（実ポインタ操作では反応しない）。
- Contract: 施錠で自動全画面化を**試みる**（``requestFullscreen`` 呼び出し）。
  headless では実全画面化はできないため「相当の挙動」= 呼び出しの発生を契約とする。
- Contract: 解除は鍵ボタンの **1.5 秒長押し**。短押しでは解除されない。
- Contract: 施錠中はナビ経由でページ離脱しない（ホームに遷移しない）。

ロック中のナビ無効は CSS の ``pointer-events: none`` で実現されるため、検証は
``dispatch_event`` ではなく**実座標クリック**（``page.mouse.click``）で行う。dispatch は
CSS のヒットテストを無視してハンドラを直接叩くので、ロックの実効を確かめられない。
"""

from __future__ import annotations

from pages import (
    BOOK_SLUGS,
    active_index,
    is_locked,
    lock,
    unlock_long_press,
)

#: 施錠時に documentElement.requestFullscreen 呼び出しを記録する init script。
#: headless では実全画面化できないため「呼ばれたか」だけを観測する。
_FULLSCREEN_RECORDER = """
(() => {
  window.__fullscreen = { calls: 0 };
  Element.prototype.requestFullscreen = function () {
    window.__fullscreen.calls += 1;
    return Promise.resolve();
  };
})();
"""


def _click_center_of(page, selector):
    """要素の中央を実座標でクリックする（pointer-events を尊重したヒットテスト）。"""
    box = page.locator(selector).bounding_box()
    assert box is not None, f"{selector} のレイアウトが取得できない"
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def test_lock_engages_and_shows_unlock_icon(page, base_url):
    """鍵ボタンで施錠すると is-locked になり、アイコンが解錠（🔓）表示に変わる。"""
    page.goto(f"{base_url}/{BOOK_SLUGS[0]}/")
    page.wait_for_selector("section.page.is-active")
    assert is_locked(page) is False

    lock(page)
    assert is_locked(page) is True
    # 施錠中は「解錠できる」状態を示す 🔓 を表示する（ehon.js setLocked）。
    assert (page.locator(".lock-btn").inner_text() or "").strip() == "🔓"


def test_locked_nav_buttons_do_not_navigate(page, base_url):
    """施錠中はナビ（次へ／ホーム）を実クリックしてもページが動かない・離脱しない。"""
    page.goto(f"{base_url}/{BOOK_SLUGS[0]}/")
    page.wait_for_selector("section.page.is-active")
    lock(page)

    start = active_index(page)
    # 「次へ」を実座標クリック: pointer-events:none で背面に抜け、goTo は呼ばれない。
    _click_center_of(page, ".nav-btn--next")
    page.wait_for_timeout(200)
    assert active_index(page) == start, "施錠中なのに次へで進んでしまった"

    # ホーム（<a href="../">）も無効。本のページに留まり、本棚へ離脱しない。
    _click_center_of(page, ".home-btn")
    page.wait_for_timeout(200)
    assert f"/{BOOK_SLUGS[0]}/" in page.url, "施錠中なのにホームへ離脱した"
    assert is_locked(page) is True


def test_lock_attempts_fullscreen(page, base_url):
    """施錠で自動全画面化を試みる（requestFullscreen 呼び出しが発生する）。"""
    page.add_init_script(_FULLSCREEN_RECORDER)
    page.goto(f"{base_url}/{BOOK_SLUGS[0]}/")
    page.wait_for_selector("section.page.is-active")
    assert page.evaluate("() => window.__fullscreen.calls") == 0

    lock(page)
    assert page.evaluate("() => window.__fullscreen.calls") >= 1


def test_short_press_does_not_unlock(page, base_url):
    """施錠中の短押し（1.5 秒未満）では解除されない。"""
    page.goto(f"{base_url}/{BOOK_SLUGS[0]}/")
    page.wait_for_selector("section.page.is-active")
    lock(page)
    assert is_locked(page) is True

    btn = page.locator(".lock-btn")
    btn.dispatch_event("pointerdown")
    page.wait_for_timeout(200)  # 1500ms 未満で離す
    btn.dispatch_event("pointerup")
    page.wait_for_timeout(100)
    assert is_locked(page) is True, "短押しで解除されてしまった"


def test_long_press_unlocks(page, base_url):
    """施錠中の 1.5 秒長押しで解除される。"""
    page.goto(f"{base_url}/{BOOK_SLUGS[0]}/")
    page.wait_for_selector("section.page.is-active")
    lock(page)
    assert is_locked(page) is True

    unlock_long_press(page)
    assert is_locked(page) is False
    assert (page.locator(".lock-btn").inner_text() or "").strip() == "🔒"
