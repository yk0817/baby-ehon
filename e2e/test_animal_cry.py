"""どうぶつパーティーの Web Audio 合成 鳴き声 の E2E（Issue #76）。

「どうぶつパーティー」の各シーン（いぬ/ねこ/ぶた/ぞう/パーティー）で、タップ時に
動物ごとの合成鳴き声が鳴ることを保証する。鳴き声は録音ファイルではなく Web Audio の
オシレーター＋ゲインで手続き的に合成する（プロジェクト方針: 音声アセットを持たない）。

実音は conftest の FakeAudioContext で鳴らさず、``window.__audio`` の生成カウンタ
（oscillators / gains / tones）で「何回・何個の音源が組まれたか」を観測する。

- Contract: 全シーンが ``cry`` プロファイル（1 つ以上の chirp）を持ち、各 chirp は
  数値の ``f0``（基本周波数）と ``dur``（長さ）を備える＝動物ごとに鳴き声が定義される。
- Contract: 通常タップで **複数オシレーターの鳴き声**が組まれる（単発ビープではない）。
  鳴き声は複数 chirp の重ね/連なりなので、1 タップで oscillator が 2 個以上増える。
- Contract: 鳴き声は**追加**であり、``cry`` を持たないブック（例: hikouki）の挙動は
  変えない＝従来どおり 1 タップ = 単発トーン（oscillator +1）のまま。
- Contract: 0-2 歳の安全性として各 chirp の音量（``gain``）は上限内（≤ 0.25）に収める。
"""

from __future__ import annotations

from pages import open_book

#: 安全上限。playTone のピーク（0.18）と同等オーダーに収め、鳴き声で突出させない。
MAX_CRY_GAIN = 0.25


def _reset_audio_counters(page) -> None:
    """``window.__audio`` の観測カウンタを 0 に戻す（タップ前の基準点を作る）。"""
    page.evaluate(
        "() => { window.__audio.oscillators = 0;"
        " window.__audio.gains = 0; window.__audio.tones = 0; }"
    )


def _tap_center(page) -> None:
    """画面中央タップ（pointerdown → onTap → emitSfxAt）。

    既存 ``pages.advance_by_tap`` と同様に短い待機を挟む。emitSfxAt は同期だが、
    タップ直後の ``page.evaluate`` がハンドラ完了前に走る余地を消して決定的にする。
    """
    size = page.viewport_size or {"width": 375, "height": 800}
    page.mouse.click(size["width"] // 2, size["height"] // 2)
    page.wait_for_timeout(100)


# ─────────────────────────────────────────────────────────────
# cry プロファイルの存在と形（データ契約）
# ─────────────────────────────────────────────────────────────
def test_every_scene_defines_a_cry(page, base_url):
    """どうぶつの全シーンが非空の ``cry``（chirp 配列）を持ち、各 chirp が数値を備える。"""
    open_book(page, base_url, "doubutsu")
    scenes = page.evaluate("() => window.BOOK_CONFIG.scenes")
    assert scenes, "BOOK_CONFIG.scenes が空"
    for key, scene in scenes.items():
        cry = scene.get("cry")
        assert isinstance(cry, list) and len(cry) >= 1, f"{key}: cry が無い/空"
        for chirp in cry:
            assert isinstance(chirp.get("f0"), (int, float)), f"{key}: f0 が数値でない"
            assert isinstance(chirp.get("dur"), (int, float)), f"{key}: dur が数値でない"


def test_cry_gain_within_safe_bound(page, base_url):
    """各 chirp の音量（gain）が 0-2 歳向けの上限内（≤ MAX_CRY_GAIN）に収まる。"""
    open_book(page, base_url, "doubutsu")
    scenes = page.evaluate("() => window.BOOK_CONFIG.scenes")
    for key, scene in scenes.items():
        for chirp in scene["cry"]:
            # gain 省略時は playCry の既定（0.18）で鳴るので、その値で検査を続ける。
            gain = chirp.get("gain", 0.18)
            assert 0 < gain <= MAX_CRY_GAIN, f"{key}: gain={gain} が安全上限を超過"


# ─────────────────────────────────────────────────────────────
# タップで鳴き声が組まれる（合成の発火）
# ─────────────────────────────────────────────────────────────
def test_tap_builds_multi_oscillator_cry(page, base_url):
    """どうぶつの通常タップで、複数オシレーターの鳴き声が組まれる（単発ビープでない）。

    初期シーン「いぬ」は複数 chirp の「わんわん」。1 タップで oscillator が 2 個以上
    生成されることを ``window.__audio`` で観測する（= 単音 playTone との区別）。
    """
    open_book(page, base_url, "doubutsu")
    _reset_audio_counters(page)
    _tap_center(page)
    audio = page.evaluate("() => window.__audio")
    assert audio["oscillators"] >= 2, (
        f"鳴き声が複数オシレーターで組まれていない: {audio}"
    )
    # ゲイン（音量エンベロープ）もオシレーターと対で組まれる。
    assert audio["gains"] >= 2, f"ゲインが chirp 数ぶん組まれていない: {audio}"


# ─────────────────────────────────────────────────────────────
# 追加であって置き換えでない（cry なしブックは不変）
# ─────────────────────────────────────────────────────────────
def test_non_cry_book_keeps_single_tone(page, base_url):
    """``cry`` を持たないブック（hikouki）はタップで従来どおり単発トーン（osc +1）。

    鳴き声は doubutsu への**追加**であり、共通エンジン側で他ブックの音を増やさない
    ことを回帰として固定する。
    """
    open_book(page, base_url, "hikouki")
    _reset_audio_counters(page)
    _tap_center(page)
    audio = page.evaluate("() => window.__audio")
    assert audio["oscillators"] == 1, (
        f"cry なしブックで単発トーン以外が鳴っている: {audio}"
    )
