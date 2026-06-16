"""__NAME__ 展開と吹き出し演出の E2E（Issue #57）。

名前の差し込みと吹き出し（オノマトペ/語りかけ）が正しく出ることを保証する。
``__NAME__`` が生のまま残らないことはプライバシーの要なので全ブックで固定する。

- Contract: seed（``baby.example.js`` の既定名「あかちゃん」）が **タイトル / 語りかけ /
  ボタン** に反映される。
- Contract: ``baby.js`` が無い場合も既定名「あかちゃん」へフォールバックする
  （``window.BABY`` 未定義時の ``shared/ehon.js`` 既定）。
- Contract: ``__NAME__`` プレースホルダが画面（本棚・各ブック）に生のまま残らない。
- Contract: 中央タップで **オノマトペバブル**（``.sfx-bubble``）が、遷移時/一定間隔で
  **語りかけ吹き出し**（``.talk-bubble``）が出る。

テストは実名を使わず seed の既定名「あかちゃん」だけを前提にする（``e2e/README.md`` の方針）。
"""

from __future__ import annotations

import pytest

from pages import (
    AUTO_TALK_MS,
    BOOK_SLUGS,
    advance_by_next_button,
    open_book,
)

#: seed（baby.example.js）の既定名。実名は使わない。
SEED_NAME = "あかちゃん"


# ─────────────────────────────────────────────────────────────
# 名前展開（タイトル / 本文 / ボタン）と __NAME__ 残留なし
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("slug", BOOK_SLUGS)
def test_name_expanded_and_no_raw_placeholder(page, base_url, slug):
    """各ブックでタイトルに seed 名が反映され、画面に生の __NAME__ が残らない。"""
    open_book(page, base_url, slug)
    body = page.inner_text("body")
    # プライバシーの要: プレースホルダが生のまま見えてはいけない。
    assert "__NAME__" not in body, f"{slug}: __NAME__ が本文に残留している"
    # seed 名がタイトル（全ブックが「__NAME__の …」形）に展開されている。
    assert "__NAME__" not in page.title()
    assert SEED_NAME in page.title(), f"{slug}: タイトルに seed 名が出ていない"


def test_name_expanded_in_button(page, base_url):
    """カメラ起動ボタン（aria-label / ラベル）に seed 名が反映され __NAME__ が残らない。

    ボタンへの差し込みは ehon.js が aria-label とテキストノードの両方を展開する契約。
    挙動は共通エンジン由来なので代表 1 冊で十分。
    """
    open_book(page, base_url, BOOK_SLUGS[0])
    toggle = page.locator("#cam-toggle")
    aria = toggle.get_attribute("aria-label") or ""
    assert "__NAME__" not in aria
    assert SEED_NAME in aria
    label = toggle.inner_text()
    assert "__NAME__" not in label
    assert SEED_NAME in label


def test_default_name_when_baby_js_missing(page, base_url):
    """``shared/baby.js`` が取得できない場合も既定名「あかちゃん」へフォールバックする。

    seed を 404 で潰して ``window.BABY`` 未定義の状態を作り、ehon.js の既定が効くことを見る
    （既定値も「あかちゃん」なので、生の __NAME__ が残らず既定名で表示されることを契約とする）。
    """
    page.route("**/shared/baby.js", lambda route: route.fulfill(status=404, body=""))
    open_book(page, base_url, BOOK_SLUGS[0])
    assert "__NAME__" not in page.inner_text("body")
    assert "__NAME__" not in page.title()
    assert SEED_NAME in page.title()


# ─────────────────────────────────────────────────────────────
# 吹き出し（オノマトペ / 語りかけ）
# ─────────────────────────────────────────────────────────────
def test_tap_emits_onomatopoeia_bubble(page, base_url):
    """画面中央タップで オノマトペバブル（.sfx-bubble）が出る。

    onTap（pointerdown）が emitSfxAt を呼び ``#fx-layer`` にバブルを生成する契約。
    """
    open_book(page, base_url, BOOK_SLUGS[0])
    size = page.viewport_size or {"width": 1280, "height": 720}
    page.mouse.click(size["width"] // 2, size["height"] // 2)
    # バブルは synchronous に生成され ~1200ms で消える。生サンプリングだと CI で
    # 取りこぼす余地があるため、auto-retry のある wait_for_selector で「出たこと」を捉える。
    bubble = page.wait_for_selector("#fx-layer .sfx-bubble", timeout=2000)
    assert (bubble.inner_text() or "").strip() != ""


def test_transition_emits_talk_bubble(page, base_url):
    """ページ遷移で 語りかけ吹き出し（.talk-bubble）が出て __NAME__ が残らない。

    goTo は遷移 700ms 後に emitTalk を呼ぶ（初期シーンに talks があるブックで成立）。
    """
    open_book(page, base_url, BOOK_SLUGS[0])
    advance_by_next_button(page)
    # emitTalk は遷移 700ms 後。headless の timer clamping（背景タブで setTimeout が
    # ≥1000ms に丸められる）も吸収できるよう余裕を持たせる（吹き出しは ~2600ms 表示）。
    page.wait_for_selector("#fx-layer .talk-bubble", timeout=3000)
    talk = page.locator("#fx-layer .talk-bubble").first
    text = talk.inner_text() or ""
    assert "__NAME__" not in text
    assert text.strip() != ""


def test_auto_talk_bubble_appears_over_time(page, base_url):
    """放置（一定間隔）でも 語りかけ吹き出しが出る。

    talkTimer（``AUTO_TALK_MS``）の発火を clock 早送りで再現する。実時間待ちを避ける。
    """
    page.clock.install()
    open_book(page, base_url, BOOK_SLUGS[0])
    assert page.locator("#fx-layer .talk-bubble").count() == 0
    # talkTimer 満期まで早送り（自動進行 12s には届かないので遷移はしない）。
    page.clock.fast_forward(AUTO_TALK_MS)
    talks = page.locator("#fx-layer .talk-bubble")
    assert talks.count() >= 1
    assert "__NAME__" not in (talks.first.inner_text() or "")
