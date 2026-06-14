"""E2E 基盤のスモークテスト（実ブラウザで green になることを担保する）。

- 本棚に 5 冊ぶんのカードがある
- 1 冊を開くと初期シーンが表示される
- ``__NAME__`` が生のまま画面に残らない（seed の「あかちゃん」に展開される）
- getUserMedia / AudioContext モックが効いていてハングしない
- 静的配信が ``.github`` / ``docs`` / ``.git`` を 403 で拒否する
"""

from __future__ import annotations

import urllib.request

import pytest

from pages import (
    BOOK_SLUGS,
    advance_by_arrow,
    book_cards,
    current_scene,
    is_locked,
    lock,
    open_book,
    open_shelf,
    unlock_long_press,
)


def test_shelf_lists_five_books(page, base_url):
    open_shelf(page, base_url)
    assert book_cards(page).count() == len(BOOK_SLUGS)
    hrefs = [
        book_cards(page).nth(i).get_attribute("href")
        for i in range(book_cards(page).count())
    ]
    for slug in BOOK_SLUGS:
        assert f"{slug}/" in hrefs


def test_shelf_has_no_raw_placeholder(page, base_url):
    open_shelf(page, base_url)
    body = page.inner_text("body")
    assert "__NAME__" not in body
    # seed（baby.example.js）の既定名が展開されている
    assert "あかちゃん" in body
    assert "あかちゃん" in page.title()


def test_open_first_book_shows_initial_scene(page, base_url):
    open_book(page, base_url, BOOK_SLUGS[0])
    # 初期シーンが表示されている（hikouki の最初のシーンは takeoff）
    assert page.locator("section.page.is-active").count() == 1
    assert current_scene(page) == "takeoff"


def test_book_has_five_pages(page, base_url):
    open_book(page, base_url, BOOK_SLUGS[0])
    assert page.locator("section.page").count() == 5


def test_book_has_no_raw_placeholder(page, base_url):
    open_book(page, base_url, BOOK_SLUGS[0])
    body = page.inner_text("body")
    assert "__NAME__" not in body
    assert "あかちゃん" in page.title()


def test_arrow_advances_page(page, base_url):
    open_book(page, base_url, BOOK_SLUGS[0])
    first = current_scene(page)
    advance_by_arrow(page)
    assert current_scene(page) != first


def test_camera_mock_does_not_hang(page, base_url):
    """カメラトグルを押しても getUserMedia モックでハングせず、呼び出しが記録される。"""
    open_book(page, base_url, BOOK_SLUGS[0])
    page.locator("#cam-toggle").dispatch_event("click")
    page.wait_for_timeout(300)
    calls = page.evaluate("() => window.__camera && window.__camera.calls")
    assert calls and calls >= 1
    # カメラウィンドウが表示状態（cam-window--off が外れる）になる
    cls = page.locator("#cam-window").get_attribute("class") or ""
    assert "cam-window--off" not in cls


def test_audio_context_stubbed(page, base_url):
    """初回ポインタ操作で AudioContext が生成され、スタブが効いている。"""
    open_book(page, base_url, BOOK_SLUGS[0])
    page.mouse.click(200, 400)
    page.wait_for_timeout(200)
    contexts = page.evaluate("() => window.__audio && window.__audio.contexts")
    assert contexts and contexts >= 1


def test_child_lock_toggle(page, base_url):
    open_book(page, base_url, BOOK_SLUGS[0])
    assert is_locked(page) is False
    lock(page)
    assert is_locked(page) is True
    unlock_long_press(page)
    assert is_locked(page) is False


@pytest.mark.parametrize("denied", ["/.github/", "/docs/", "/.git/"])
def test_static_server_denies_sensitive_paths(base_url, denied):
    req = urllib.request.Request(f"{base_url}{denied}", method="GET")
    try:
        urllib.request.urlopen(req, timeout=5)
        raised = None
    except urllib.error.HTTPError as exc:
        raised = exc.code
    assert raised == 403
