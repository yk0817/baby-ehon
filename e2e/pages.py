"""baby-ehon の Page Object / ヘルパ。

後続 issue のテストが使う土台。セレクタは現物の HTML/JS に合わせてある:

- 本棚 ``index.html``: 各絵本は ``a.book-card``（``href="hikouki/"`` 等）。タイトルは
  ``.book-name``。
- 各絵本 ``<book>/index.html``: ページは ``section.page``（``data-scene`` 付き）。表示中は
  ``.page.is-active``。ナビは ``.nav-btn--prev`` / ``.nav-btn--next`` / ``.lock-btn``、
  ドットは ``#dots .dot``。
- ページ送りは: 次へボタン / スワイプ（touchstart→touchend で 80px 超） / ``ArrowRight`` /
  自動進行（``AUTO_ADVANCE_MS`` = 12000ms。実時間待ちを避けるため ``advance_by_auto`` は
  Playwright の ``clock`` で早送りする）。
- ``scene_order`` で全ページの ``data-scene`` を DOM 順に取得できる。
- ロックは ``.lock-btn`` を 1 回押すとロック、ロック中は長押し（``LOCK_UNLOCK_MS`` = 1500ms）
  で解除（``shared/ehon.js`` 参照）。
"""

from __future__ import annotations

from typing import Any

#: 本棚に並ぶ絵本のディレクトリ名（href）。README のラインナップと一致。
BOOK_SLUGS: tuple[str, ...] = (
    "hikouki",
    "densha",
    "kuruma",
    "otenki",
    "yorunosora",
    "doubutsu",
    "iro",
)

#: ロック解除に必要な長押し時間（ehon.js の LOCK_UNLOCK_MS）。余裕を持って待つ。
_LOCK_UNLOCK_MS = 1500
_LOCK_HOLD_MS = _LOCK_UNLOCK_MS + 300

#: 自動進行の間隔（ehon.js の AUTO_ADVANCE_MS）。実時間で待つと遅いので clock で送る。
AUTO_ADVANCE_MS = 12000

#: 語りかけ吹き出しの自動発火間隔（ehon.js の AUTO_TALK_MS）。clock 早送りで再現する。
AUTO_TALK_MS = 5200


def open_shelf(page: Any, base_url: str) -> Any:
    """本棚（ルート index.html）を開く。"""
    page.goto(f"{base_url}/")
    page.wait_for_selector("a.book-card")
    return page


def open_book(page: Any, base_url: str, name: str) -> Any:
    """絵本ディレクトリ ``name``（例: 'hikouki'）を開き、初期シーンの表示を待つ。"""
    page.goto(f"{base_url}/{name}/")
    page.wait_for_selector("section.page.is-active")
    return page


def book_cards(page: Any) -> Any:
    """本棚の絵本カード（``a.book-card``）の Locator を返す。"""
    return page.locator("a.book-card")


def current_scene(page: Any) -> str | None:
    """現在表示中のページ（``.page.is-active``）の ``data-scene`` を返す。"""
    active = page.locator("section.page.is-active").first
    return active.get_attribute("data-scene")


def active_index(page: Any) -> int:
    """現在アクティブなページの 0 始まりインデックス（``.dot.is-active`` の位置）を返す。"""
    dots = page.locator("#dots .dot")
    count = dots.count()
    for i in range(count):
        cls = dots.nth(i).get_attribute("class") or ""
        if "is-active" in cls:
            return i
    return -1


def advance_by_tap(page: Any) -> None:
    """画面中央タップ相当。SFX を出すだけでページは送らない（タップ操作の土台）。"""
    size = page.viewport_size or {"width": 375, "height": 800}
    page.mouse.click(size["width"] // 2, size["height"] // 2)
    page.wait_for_timeout(200)


def advance_by_arrow(page: Any) -> None:
    """``ArrowRight`` で次ページへ送る。"""
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(200)


def advance_by_next_button(page: Any) -> None:
    """次へボタン（``.nav-btn--next``）で次ページへ送る。"""
    page.locator(".nav-btn--next").click()
    page.wait_for_timeout(200)


def advance_by_swipe(page: Any) -> None:
    """左スワイプ（touchstart→touchend で 80px 超）で次ページへ送る。

    タッチイベントを直接 dispatch する（Playwright の touchscreen はページ送りの
    touchstart/touchend ハンドラと噛み合わせやすいよう JS で発火する）。
    """
    page.evaluate("""() => {
          const fire = (type, x) => {
            // Chromium は changedTouches に本物の Touch インスタンスを要求する
            // （plain object だと TouchEvent 構築時に TypeError）。
            const t = new Touch({
              identifier: 0, target: document.body, clientX: x, clientY: 400,
            });
            const ev = new TouchEvent(type, {
              bubbles: true, cancelable: true,
              changedTouches: [t], touches: type === 'touchend' ? [] : [t],
            });
            document.dispatchEvent(ev);
          };
          fire('touchstart', 300);
          fire('touchend', 100);
        }""")
    page.wait_for_timeout(200)


def scene_order(page: Any) -> list[str]:
    """ブック内の全ページ（``section.page``）の ``data-scene`` を DOM 順で返す。"""
    return page.eval_on_selector_all(
        "section.page", "els => els.map(e => e.dataset.scene)"
    )


def advance_by_auto(page: Any) -> None:
    """自動進行（``AUTO_ADVANCE_MS``）を 1 回ぶん進める。

    実時間で 12 秒待つ代わりに Playwright の ``clock`` を早送りする。呼び出し前に
    ``page.clock.install()`` を済ませ、その後に ``open_book`` していること。

    ``fast_forward`` は仮想時刻を進めつつ満期の ``setInterval`` を同期的に発火させ、
    ``ehon.js`` の ``goTo``（``is-active`` クラスの付け替え）も同期完了してから戻る。
    そのため戻り後すぐに DOM を読んでよい（追加の待機は不要）。
    """
    page.clock.fast_forward(AUTO_ADVANCE_MS)


def is_locked(page: Any) -> bool:
    """チャイルドロック中か（``.parent-nav.is-locked``）。"""
    nav = page.locator(".parent-nav").first
    cls = nav.get_attribute("class") or ""
    return "is-locked" in cls


def lock(page: Any) -> None:
    """``.lock-btn`` を 1 回押してロックする。"""
    page.locator(".lock-btn").dispatch_event("pointerdown")
    page.wait_for_timeout(100)


def unlock_long_press(page: Any) -> None:
    """``.lock-btn`` を長押し（pointerdown → 待機 → pointerup）してロック解除する。

    未施錠で呼ぶと pointerdown が施錠扱い（``setLocked(true)``）になり、結果的に
    「解除したつもりが施錠される」状態反転を招く。誤用を早期に弾くため施錠前提を確認する。
    """
    assert is_locked(page), "unlock_long_press は施錠中に呼ぶこと（未施錠だと逆に施錠される）"
    btn = page.locator(".lock-btn")
    btn.dispatch_event("pointerdown")
    page.wait_for_timeout(_LOCK_HOLD_MS)
    btn.dispatch_event("pointerup")
    page.wait_for_timeout(100)
