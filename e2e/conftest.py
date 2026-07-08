"""baby-ehon E2E テストの共通 fixture。

絵本ランタイム（HTML/CSS/JS）には一切手を入れず、テスト側だけで実ブラウザ操作の
土台を組む。方針:

- **静的配信**: ``python -m http.server`` 相当をスレッドで空きポート起動し、配信ルートは
  リポジトリルート。ただし ``.github`` / ``docs`` / ``.git`` を含むパスへのリクエストは
  403 で拒否する（``.github/scripts/child_reviewer/browser.py`` の除外と同方針）。
- **baby.js seed**: 既存 ``shared/baby.js`` があれば退避し、``shared/baby.example.js`` の
  内容（既定名「あかちゃん」）を ``shared/baby.js`` に書く。テスト後に退避を復元（無ければ
  削除）。実ファイルを壊さない・コミットしない。
- **page セットアップ**: ``getUserMedia`` をモックしてカメラ権限でハングさせない。
  ``AudioContext`` / ``webkitAudioContext`` をスタブして実音を鳴らさずに最低限動かす。
"""

from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path
from typing import Any

import pytest

#: リポジトリルート（このファイルは <repo>/e2e/conftest.py）。
REPO_ROOT = Path(__file__).resolve().parent.parent

#: 配信時に拒否するトップレベルパス（browser.py §7.7 と同じ）。
_DENIED_TOP = ("/.github", "/docs", "/.git")


# ─────────────────────────────────────────────────────────────
# 静的配信
# ─────────────────────────────────────────────────────────────
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

        def do_HEAD(self) -> None:  # noqa: N802
            if self._is_denied():
                self.send_error(403, "Forbidden")
                return
            super().do_HEAD()

        def log_message(self, *args: Any) -> None:
            """アクセスログを抑制（テスト出力を汚さない）。"""

    return _Handler


@pytest.fixture(scope="session")
def base_url() -> Any:
    """リポジトリルートを配信し ``base_url``（例: http://127.0.0.1:PORT）を yield する。

    ``port=0`` で OS に空きポートを割り当てさせ、終了時に停止する。
    """
    handler = _make_handler(REPO_ROOT)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    actual_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{actual_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# ─────────────────────────────────────────────────────────────
# baby.js seed（既定名「あかちゃん」をテスト中だけ配置）
# ─────────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def seed_baby_js() -> Any:
    """テスト中だけ ``shared/baby.js`` を example の内容で用意する。

    既存ファイルがあれば退避し、テスト後に復元する。無ければテスト後に削除する。
    実 ``shared/baby.js`` を壊さず、リポジトリにもコミットしない（.gitignore 済み）。
    """
    baby_js = REPO_ROOT / "shared" / "baby.js"
    example = REPO_ROOT / "shared" / "baby.example.js"

    backup: bytes | None = None
    if baby_js.exists():
        backup = baby_js.read_bytes()

    baby_js.write_bytes(example.read_bytes())
    try:
        yield baby_js
    finally:
        if backup is not None:
            baby_js.write_bytes(backup)
        elif baby_js.exists():
            baby_js.unlink()


# ─────────────────────────────────────────────────────────────
# page セットアップ（getUserMedia / AudioContext モック）
# ─────────────────────────────────────────────────────────────
#: ブラウザに注入する init script。
#:
#: - ``navigator.mediaDevices.getUserMedia`` を、トラック付きの偽 MediaStream を返すよう
#:   差し替える。カメラ権限プロンプトでハングさせない（呼ばれたら window.__camera に記録）。
#: - ``AudioContext`` / ``webkitAudioContext`` をスタブ。実音は鳴らさず、生成・主要メソッド
#:   呼び出しを window.__audio に記録しつつ、ehon.js が触る API を最低限満たす。
_INIT_SCRIPT = r"""
(() => {
  // ── getUserMedia モック ──────────────────────────────
  // 本物の MediaStream を返す（canvas.captureStream() 由来）。偽オブジェクトだと
  // video.srcObject 代入で TypeError になり ehon.js が catch に落ちてしまうため、
  // 実際に srcObject へ設定できる本物のストリームを使う。
  window.__camera = { calls: 0, lastConstraints: null };
  const fakeStream = () => {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 16;
      canvas.height = 16;
      // getContext を一度呼んで captureStream が空にならないようにする
      canvas.getContext('2d');
      if (canvas.captureStream) {
        return canvas.captureStream(0);
      }
    } catch (_) {}
    // captureStream が無い環境の保険（srcObject 代入はできないが呼び出しは記録済み）
    return new MediaStream();
  };
  if (!navigator.mediaDevices) {
    try {
      Object.defineProperty(navigator, 'mediaDevices', { value: {}, configurable: true });
    } catch (_) {}
  }
  if (navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = (constraints) => {
      window.__camera.calls += 1;
      window.__camera.lastConstraints = constraints || null;
      return Promise.resolve(fakeStream());
    };
  }

  // ── AudioContext スタブ ──────────────────────────────
  // compressors / intoCompressor / directToDestination は Issue #78（マスター
  // コンプレッサー経由の出力）の契約観測用。接続経路をカウンタで可視化する。
  window.__audio = {
    contexts: 0, oscillators: 0, gains: 0, tones: 0,
    compressors: 0, intoCompressor: 0, directToDestination: 0,
  };
  class FakeAudioParam {
    constructor(value = 0) { this.value = value; }
    setValueAtTime() { return this; }
    exponentialRampToValueAtTime() { return this; }
    linearRampToValueAtTime() { return this; }
  }
  class FakeNode {
    constructor() {
      this.frequency = new FakeAudioParam();
      this.gain = new FakeAudioParam();
      // DynamicsCompressorNode の AudioParam（実 API に合わせて備える）
      this.threshold = new FakeAudioParam();
      this.knee = new FakeAudioParam();
      this.ratio = new FakeAudioParam();
      this.attack = new FakeAudioParam();
      this.release = new FakeAudioParam();
      this.isDestination = false;
      this.isCompressor = false;
    }
    connect(dest) {
      // 「マスター段を経由せず destination 直結した音源」を検出できるようにする
      if (dest && dest.isDestination && !this.isCompressor) window.__audio.directToDestination += 1;
      if (dest && dest.isCompressor) window.__audio.intoCompressor += 1;
      return dest;
    }
    disconnect() {}
    start() { window.__audio.tones += 1; }
    stop() {}
    setValueAtTime() {}
  }
  class FakeAudioContext {
    constructor() {
      window.__audio.contexts += 1;
      this.state = 'running';
      this.currentTime = 0;
      this.destination = new FakeNode();
      this.destination.isDestination = true;
    }
    createOscillator() { window.__audio.oscillators += 1; return new FakeNode(); }
    createGain() { window.__audio.gains += 1; return new FakeNode(); }
    createDynamicsCompressor() {
      window.__audio.compressors += 1;
      const node = new FakeNode();
      node.isCompressor = true;
      return node;
    }
    resume() { this.state = 'running'; return Promise.resolve(); }
    suspend() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
  }
  window.AudioContext = FakeAudioContext;
  window.webkitAudioContext = FakeAudioContext;
})();
"""


@pytest.fixture(autouse=True)
def _mock_browser_apis(page: Any) -> Any:
    """全テストの ``page`` に getUserMedia / AudioContext モックを注入する。

    ``add_init_script`` なので、各 ``page.goto`` の前にドキュメントへ適用される。
    """
    page.add_init_script(_INIT_SCRIPT)
    return page
