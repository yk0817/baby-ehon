"""中核の閲覧フロー E2E（Issue #55）。

本棚 → 各ブック遷移と、4 つの送り手段（次へボタン=タップ / スワイプ / ←→キー /
自動進行）で全 5 シーンを巡れることを 5 冊すべてで保証する。

- Contract: 本棚の各カードは対応ブックを開き、初期シーンを表示する。
- Contract: 各送り手段でシーンが 1 つずつ進み、末尾の次は先頭へ**ループ**する
  （``shared/ehon.js`` の ``goTo`` が ``% pages.length`` で巻き戻すため）。
- 画面中央タップは SFX 専用でページを送らない（送りの「タップ」は次へボタン）。
"""

from __future__ import annotations

import pytest

from pages import (
    BOOK_SLUGS,
    active_index,
    advance_by_arrow,
    advance_by_auto,
    advance_by_next_button,
    advance_by_swipe,
    advance_by_tap,
    current_scene,
    open_book,
    open_shelf,
    scene_order,
)

#: 各ブックの初期シーン（DOM 先頭ページの data-scene）。閲覧開始点の契約を固定する。
EXPECTED_FIRST_SCENE: dict[str, str] = {
    "hikouki": "takeoff",
    "densha": "hassha",
    "kuruma": "shuppatsu",
    "otenki": "sunny",
    "yorunosora": "dusk",
    "doubutsu": "inu",
    "iro": "aka",
}

#: 1 冊あたりのシーン数（全ブック共通の契約）。
SCENE_COUNT = 5


# ─────────────────────────────────────────────────────────────
# 本棚 → 各ブック遷移
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", BOOK_SLUGS)
def test_shelf_card_opens_book(page, base_url, slug):
    """本棚のカードをタップすると対応ブックへ遷移し、初期シーンが出る。"""
    open_shelf(page, base_url)
    # slug に対応するカード（href に "<slug>/" を含む）をクリックする。
    target = page.locator(f'a.book-card[href*="{slug}/"]')
    assert target.count() == 1
    target.click()
    page.wait_for_url(f"**/{slug}/**")
    page.wait_for_selector("section.page.is-active")
    assert current_scene(page) == EXPECTED_FIRST_SCENE[slug]


@pytest.mark.parametrize("slug", BOOK_SLUGS)
def test_book_initial_scene_and_count(page, base_url, slug):
    """各ブックは初期シーンを表示し、5 シーンを持ち、最初のドットがアクティブ。"""
    open_book(page, base_url, slug)
    assert page.locator("section.page").count() == SCENE_COUNT
    assert active_index(page) == 0
    assert current_scene(page) == EXPECTED_FIRST_SCENE[slug]


# ─────────────────────────────────────────────────────────────
# 手動の送り手段（次へボタン / スワイプ / 矢印）で全シーンを巡る
# ─────────────────────────────────────────────────────────────
MANUAL_ADVANCERS = {
    "next_button": advance_by_next_button,
    "swipe": advance_by_swipe,
    "arrow": advance_by_arrow,
}


@pytest.mark.parametrize("slug", BOOK_SLUGS)
@pytest.mark.parametrize("method", list(MANUAL_ADVANCERS))
def test_advance_through_all_scenes(page, base_url, slug, method):
    """各送り手段でシーンが 1 つずつ進み、末尾の次は先頭へループする。"""
    advance = MANUAL_ADVANCERS[method]
    open_book(page, base_url, slug)
    order = scene_order(page)
    assert len(order) == SCENE_COUNT

    # 0 → 1 → ... → 4 と進み、各ステップで index/scene が期待どおりか確認。
    for i in range(1, SCENE_COUNT):
        advance(page)
        assert active_index(page) == i, f"{slug}/{method}: index {i} に進めていない"
        assert current_scene(page) == order[i]

    # 末尾（index 4）からもう一度送ると先頭（index 0）へループ。
    advance(page)
    assert active_index(page) == 0
    assert current_scene(page) == order[0]


# ─────────────────────────────────────────────────────────────
# 自動進行（12 秒）— clock で早送りして全シーンを巡る
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", BOOK_SLUGS)
def test_auto_advance_cycles_scenes(page, base_url, slug):
    """自動進行が一定間隔でシーンを送り、末尾の次は先頭へループする。"""
    # clock は goto より前に install する必要がある。
    page.clock.install()
    open_book(page, base_url, slug)
    order = scene_order(page)
    assert active_index(page) == 0

    # Contract: 12 秒ぶんの早送り 1 回でちょうど 1 シーン進む。goTo 後の restartTimers で
    # autoTimer は再設定されるが、次の早送りもまた 12 秒進めるので毎回 1 ティックだけ発火する。
    for i in range(1, SCENE_COUNT):
        advance_by_auto(page)
        assert active_index(page) == i, f"{slug}: 自動進行で index {i} に進めていない"
        assert current_scene(page) == order[i]

    advance_by_auto(page)
    assert active_index(page) == 0
    assert current_scene(page) == order[0]


def test_center_tap_does_not_advance(page, base_url):
    """画面中央タップは SFX 専用でページを送らない（送りはボタン/スワイプ/矢印/自動）。

    この挙動はブック設定によらず ehon.js の onTap ハンドラ共通なので代表 1 冊で十分。
    """
    open_book(page, base_url, BOOK_SLUGS[0])
    before = active_index(page)
    advance_by_tap(page)  # 中央タップ（送らないことの確認なので名前に反して index は不変）
    assert active_index(page) == before
