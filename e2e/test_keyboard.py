"""キーボード乱打リアクションの E2E（Issue #58）。

1 歳児の乱打に対する派手なリアクション（言葉/絵文字バブル + きらきら + 画面フラッシュ）が
出ること、←→ は従来どおりページ送りに使われること、連打しても要素が残り続けないことを保証する。

- Contract: ←→ 以外のキーで ``.key-bubble`` + ``.spark`` が ``#fx-layer`` に出て、
  ``body`` に ``flash`` クラスが付く（``shared/ehon.js`` の ``emitKeyReaction``）。
- Contract: ←→ はページ送り（``goTo``）に使われ、リアクション（``.key-bubble``）を出さない。
- Contract: 連打しても各 fx 要素は寿命（key-bubble ~1400ms / spark ~900ms）後に除去され、
  残留しない（リーク無し）。

実名は使わず、バブルに ``__NAME__`` が生のまま出ないことも併せて確認する。
"""

from __future__ import annotations

from pages import (
    BOOK_SLUGS,
    active_index,
    open_book,
)

#: 乱打に使う非矢印キー（普通の文字キー）。
_MASH_KEYS = list("qwertyuiopasdfghjkl")


def test_non_arrow_key_triggers_reaction(page, base_url):
    """←→ 以外のキーで バブル + きらきら + 画面フラッシュ が出る。"""
    open_book(page, base_url, BOOK_SLUGS[0])
    page.keyboard.press("a")

    # バブル・きらきらは keydown で synchronous 生成。auto-retry で「出たこと」を捉える。
    bubble = page.wait_for_selector("#fx-layer .key-bubble", timeout=2000)
    text = bubble.inner_text() or ""
    # 絵文字のこともあるので非空のみ要求。名前入りの語でも __NAME__ が生で残らないこと。
    assert text.strip() != ""
    assert "__NAME__" not in text

    assert page.locator("#fx-layer .spark").count() >= 1
    body_class = page.locator("body").get_attribute("class") or ""
    assert "flash" in body_class


def test_arrow_keys_paginate_without_reaction(page, base_url):
    """←→ はページ送りに使われ、乱打リアクション（.key-bubble）を出さない。"""
    open_book(page, base_url, BOOK_SLUGS[0])

    start = active_index(page)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(150)
    assert active_index(page) == start + 1, "ArrowRight でページが進んでいない"
    # 送りに使われたキーはリアクションを奪わない（key-bubble は出ない）。
    assert page.locator("#fx-layer .key-bubble").count() == 0

    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(150)
    assert active_index(page) == start, "ArrowLeft で戻れていない"
    assert page.locator("#fx-layer .key-bubble").count() == 0


def test_mashing_does_not_leak_elements(page, base_url):
    """連打しても各 fx 要素は寿命後に除去され、残留しない（リーク無し）。"""
    open_book(page, base_url, BOOK_SLUGS[0])

    for key in _MASH_KEYS:
        page.keyboard.press(key)

    # 連打中はバブルが複数生成される（リアクションが発火している証跡）。
    assert page.locator("#fx-layer .key-bubble").count() >= 1

    # key-bubble（~1400ms）と spark（~900ms）が寿命後に 0 へ戻ることを待つ。
    # spark は自動 SFX（3500ms 間隔）でも一時的に湧くため、ここでは「key-bubble と spark が
    # 同時に 0 になる瞬間」を待つ（自動 SFX の谷で必ず成立する）。これで乱打由来の要素が
    # 残留しない（リーク無し）ことを race なく確認できる。timeout は 1 周期分に余裕を持たせる。
    page.wait_for_function(
        """() =>
            document.querySelectorAll('#fx-layer .key-bubble').length === 0 &&
            document.querySelectorAll('#fx-layer .spark').length === 0
        """,
        timeout=6000,
    )
