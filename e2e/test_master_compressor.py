"""タップ音のマスターコンプレッサー（Issue #78）の E2E。

タップごとに独立した音源（OscillatorNode + GainNode）を destination へ直結すると、
0-2 歳の典型操作である「画面連打」で複数音源が同時に生存し、出力が加算されて
ピークが単発時の想定（gain ≤ 0.25）を超えうる。共通エンジン ehon.js は全音源を
1 段の DynamicsCompressorNode（マスター段）経由で出力し、重なり時の音量累積を抑える。

実音は conftest の FakeAudioContext で鳴らさず、ノード生成数と接続経路のカウンタ
（``window.__audio`` の compressors / intoCompressor / directToDestination）で
「全音源がマスター段を通る」ことを契約として観測する。

- Contract: マスターコンプレッサーは AudioContext ごとに 1 個だけ（タップで増えない）。
- Contract: 単発トーン（playTone）も鳴き声（playCry）も destination 直結が 0 で、
  マスター段（intoCompressor）を経由する。
- Contract: 連打しても経路は変わらない＝直結 0 のまま全音源がマスター段を通る。
"""

from __future__ import annotations

from pages import open_book


def _reset_route_counters(page) -> None:
    """接続経路の観測カウンタを 0 に戻す(タップ前の基準点を作る)。"""
    page.evaluate(
        "() => { window.__audio.oscillators = 0; window.__audio.gains = 0;"
        " window.__audio.intoCompressor = 0; window.__audio.directToDestination = 0; }"
    )


def _tap_center(page, times: int = 1, settle_ms: int = 100) -> None:
    """画面中央を ``times`` 回タップする（連打は待機を短くして重なりを作る）。"""
    size = page.viewport_size or {"width": 375, "height": 800}
    for _ in range(times):
        page.mouse.click(size["width"] // 2, size["height"] // 2)
        page.wait_for_timeout(settle_ms)


# ─────────────────────────────────────────────────────────────
# マスター段は 1 個だけ（コンテキストと同寿命）
# ─────────────────────────────────────────────────────────────
def test_master_compressor_created_once(page, base_url):
    """初回タップでマスターコンプレッサーが 1 個作られ、以後のタップで増えない。"""
    open_book(page, base_url, "hikouki")
    _tap_center(page, times=3)
    audio = page.evaluate("() => window.__audio")
    assert audio["contexts"] == 1, f"AudioContext が複数生成されている: {audio}"
    assert audio["compressors"] == 1, (
        f"マスターコンプレッサーが1個でない（0=未導入 / 2以上=タップごと生成）: {audio}"
    )


# ─────────────────────────────────────────────────────────────
# 全音源がマスター段を経由する（直結 0）
# ─────────────────────────────────────────────────────────────
def test_tone_routes_through_master(page, base_url):
    """単発トーン（playTone）の経路が osc→gain→マスター段になり destination 直結しない。"""
    open_book(page, base_url, "hikouki")
    _tap_center(page)  # 初回タップでマスター段を作らせてから経路を観測する
    _reset_route_counters(page)
    _tap_center(page)
    audio = page.evaluate("() => window.__audio")
    assert audio["oscillators"] == 1, f"単発トーンの前提が崩れている: {audio}"
    assert audio["intoCompressor"] == 1, f"gain がマスター段へ接続されていない: {audio}"
    assert audio["directToDestination"] == 0, f"destination 直結の音源が残っている: {audio}"


def test_cry_routes_through_master(page, base_url):
    """鳴き声（playCry）の全 chirp もマスター段を経由し destination 直結しない。"""
    open_book(page, base_url, "doubutsu")
    _tap_center(page)
    _reset_route_counters(page)
    _tap_center(page)
    audio = page.evaluate("() => window.__audio")
    assert audio["oscillators"] >= 2, f"複数 chirp の鳴き声の前提が崩れている: {audio}"
    assert audio["intoCompressor"] == audio["gains"], (
        f"マスター段を経由しない chirp がある: {audio}"
    )
    assert audio["directToDestination"] == 0, f"destination 直結の音源が残っている: {audio}"


def test_fallback_without_compressor_keeps_sound(page, base_url):
    """``createDynamicsCompressor`` が無い環境では従来どおり直結で音が鳴り続ける。

    マスター段は聴覚保護の**追加**であり、非対応環境で音が全滅しないことを固定する
    （conftest のスタブから当該メソッドだけ落として旧環境を再現）。
    """
    page.add_init_script(
        "delete window.AudioContext.prototype.createDynamicsCompressor;"
    )
    open_book(page, base_url, "hikouki")
    _tap_center(page)
    audio = page.evaluate("() => window.__audio")
    assert audio["compressors"] == 0, f"非対応環境でコンプレッサーが作られている: {audio}"
    assert audio["tones"] >= 1, f"フォールバックで音が出ていない: {audio}"
    assert audio["directToDestination"] >= 1, (
        f"素通し（従来の destination 直結）になっていない: {audio}"
    )


def test_rapid_taps_all_route_through_single_master(page, base_url):
    """連打（重なりが生じる操作）でも全音源が 1 個のマスター段を通り、直結 0 を保つ。

    FakeAudioContext では実出力レベルは測れないため、「重なっても必ず同じマスター段
    を通る」接続契約を固定する（実ブラウザではこの 1 段が音量累積の天井になる）。
    """
    open_book(page, base_url, "doubutsu")
    _tap_center(page)
    _reset_route_counters(page)
    _tap_center(page, times=5, settle_ms=40)
    audio = page.evaluate("() => window.__audio")
    assert audio["compressors"] == 1, f"連打でマスター段が増殖している: {audio}"
    assert audio["gains"] >= 5, f"連打で音源が組まれていない: {audio}"
    assert audio["intoCompressor"] == audio["gains"], (
        f"マスター段を経由しない音源がある: {audio}"
    )
    assert audio["directToDestination"] == 0, f"destination 直結の音源が残っている: {audio}"
