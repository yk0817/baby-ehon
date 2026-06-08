"""ブラウザ操作と静的配信を隔離するモジュール（Playwright を遅延 import）。

``nodes.py`` のテストを Playwright / chromium 無しで回せるよう、ブラウザ依存は
ここに閉じ込める。**Playwright の import は関数内で遅延** し、本モジュールを import
しただけでは依存を要求しない（``serve_static`` / ``capture`` を実際に呼ぶときだけ）。

配信ポリシー（§7.7）:

- ``python -m http.server`` でリポジトリルートを配信するが、配信ルートは
  **絵本ディレクトリ + ``shared/``** に限定する考え方を採る。実装としては、
  ``.github`` / ``docs`` / ``.git`` を含むパスへのリクエストを拒否する薄い
  ハンドラを噛ませる（トップレベルの除外）。
- スクショは 320 / 768 / 1024 の 3 ビューポート × 「初期 / 主要タップ後 / ページ送り後」
  の 3 フェーズで撮る。

設計: docs/automation/agent-pipeline.md §7.3 / §7.7
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: スクショを撮るビューポート幅（§7.3）。高さは縦長で固定。
VIEWPORTS: tuple[int, ...] = (320, 768, 1024)
VIEWPORT_HEIGHT = 800

#: 各ビューポートで撮るフェーズ（§7.3）。
PHASES: tuple[str, ...] = ("initial", "after_tap", "after_page")

#: 配信時に拒否するトップレベルパス（§7.7）。
_DENIED_TOP = ("/.github", "/docs", "/.git")


@dataclass(frozen=True)
class StaticServer:
    """起動済みの静的配信サーバ（ハンドル）。

    ``base_url`` で配信 URL を、``stop()`` で停止できる。
    """

    base_url: str
    _httpd: Any
    _thread: Any

    def stop(self) -> None:
        """配信を止める。"""
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _make_handler(root: Path) -> type[http.server.SimpleHTTPRequestHandler]:
    """root を配信しつつ、除外トップレベルへのアクセスを 403 で弾くハンドラを作る。"""

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def _is_denied(self) -> bool:
            normalized = self.path.split("?", 1)[0]
            return any(
                normalized == deny or normalized.startswith(deny + "/")
                for deny in _DENIED_TOP
            )

        def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler 規約)
            if self._is_denied():
                self.send_error(403, "Forbidden")
                return
            super().do_GET()

        def log_message(self, *args: Any) -> None:
            """アクセスログを抑制（公開リポジトリのログに余計な情報を残さない）。"""

    return _Handler


def serve_static(root: str | Path, *, port: int = 0) -> StaticServer:
    """``root`` を配信する HTTP サーバをバックグラウンドで起動する（§7.7）。

    ``port=0`` で OS に空きポートを割り当てさせる。``.github`` / ``docs`` / ``.git``
    へのリクエストは 403 で拒否する。
    """
    handler = _make_handler(Path(root))
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    actual_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return StaticServer(
        base_url=f"http://127.0.0.1:{actual_port}",
        _httpd=httpd,
        _thread=thread,
    )


def capture(
    base_url: str,
    book: str,
    *,
    out_dir: str | Path,
    viewports: Sequence[int] = VIEWPORTS,
) -> list[dict]:
    """対象絵本を各ビューポート × 各フェーズでスクショする（§7.3）。

    Playwright を **この関数内でのみ遅延 import** する（未インストール / chromium 未 DL
    の環境では ``RuntimeError`` を送出し、呼び出し側がスタブにフォールバックできる）。
    返り値は ``[{book, viewport, phase, path}]``。
    """
    try:
        from playwright.sync_api import sync_playwright  # 遅延 import
    except ImportError as exc:  # Playwright 未インストール
        raise RuntimeError("playwright が未インストールです") from exc

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    url = f"{base_url}/{book}/" if book else f"{base_url}/"

    shots: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in viewports:
                shots.extend(_capture_one_viewport(browser, url, book, width, out_path))
        finally:
            browser.close()
    return shots


def _capture_one_viewport(
    browser: Any,
    url: str,
    book: str,
    width: int,
    out_path: Path,
) -> list[dict]:
    """1 ビューポートぶんの 3 フェーズ（初期 / タップ後 / 送り後）を撮る。"""
    context = browser.new_context(viewport={"width": width, "height": VIEWPORT_HEIGHT})
    page = context.new_page()
    page.goto(url)
    shots: list[dict] = []
    try:
        for phase in PHASES:
            _advance_phase(page, phase)
            path = out_path / f"{book or 'shelf'}_{width}_{phase}.png"
            page.screenshot(path=str(path))
            shots.append(
                {
                    "book": book or "shelf",
                    "viewport": width,
                    "phase": phase,
                    "path": str(path),
                }
            )
    finally:
        context.close()
    return shots


def _advance_phase(page: Any, phase: str) -> None:
    """フェーズに応じてページを操作する（主要タップ / ページ送りを近似）。

    要素特定はできるだけ汎用に保つ（絵本ごとの DOM 差を吸収）。失敗しても落とさず、
    その時点の状態でスクショする（所見は人間が最終判断するため、撮れる範囲で撮る）。
    """
    if phase == "initial":
        return
    try:
        if phase == "after_tap":
            page.mouse.click(page.viewport_size["width"] // 2, 400)
        elif phase == "after_page":
            page.keyboard.press("ArrowRight")
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001  操作失敗でも撮れる範囲で撮る
        return
