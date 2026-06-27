"""init.sh（足場⑤ Session Lifecycle）の契約テスト。

Contract: maker を動かす前に「土台が整っている」ことを保証する。具体的には
``shared/baby.js`` を ``shared/baby.example.js``（既定名「あかちゃん」）から **冪等に
seed** し、Python / pytest の存在を確認する。

なぜこの挙動が必要か:
- 実 ``baby.js``（gitignore・実名入り）を CI/loop に持ち込まないため、seed は example
  からのみ行う（既存があれば壊さない＝冪等）。
- 土台が欠けたまま実装させると原因切り分けが難しくなるので、依存欠落は明示的に落とす。

ROOT は ``BABY_EHON_ROOT`` で差し替え可能（hermetic にテストするための seam）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_INIT_SH = Path(__file__).resolve().parents[1] / "harness" / "init.sh"
_EXAMPLE_CONTENT = (
    "window.BABY = {\n  name: 'あかちゃん',\n  honorific: '',\n};\n"
)


def _make_root(tmp_path: Path, *, with_example: bool = True) -> Path:
    """tmp に <root>/shared/baby.example.js を持つ最小リポジトリ構造を作る。"""
    shared = tmp_path / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    if with_example:
        (shared / "baby.example.js").write_text(_EXAMPLE_CONTENT, encoding="utf-8")
    return tmp_path


def _run_init(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_INIT_SH)],
        env={
            "BABY_EHON_ROOT": str(root),
            "VERIFY_PYTHON": sys.executable,  # pytest を持つ test ランナーの python
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
        capture_output=True,
        text=True,
    )


def test_seeds_baby_js_from_example_when_missing(tmp_path: Path) -> None:
    root = _make_root(tmp_path)

    result = _run_init(root)

    baby_js = root / "shared" / "baby.js"
    assert result.returncode == 0, result.stderr
    assert baby_js.exists()
    assert baby_js.read_text(encoding="utf-8") == _EXAMPLE_CONTENT


def test_seed_is_idempotent_keeps_existing(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    baby_js = root / "shared" / "baby.js"
    custom = "window.BABY = { name: 'あかちゃん', honorific: 'ちゃん' };\n"
    baby_js.write_text(custom, encoding="utf-8")

    result = _run_init(root)

    # Contract: 既存 baby.js は上書きしない（ローカルの設定を壊さない）
    assert result.returncode == 0, result.stderr
    assert baby_js.read_text(encoding="utf-8") == custom


def test_fails_when_example_missing(tmp_path: Path) -> None:
    root = _make_root(tmp_path, with_example=False)

    result = _run_init(root)

    assert result.returncode != 0
    assert "baby.example.js" in (result.stdout + result.stderr)


def test_reports_python_and_pytest(tmp_path: Path) -> None:
    root = _make_root(tmp_path)

    result = _run_init(root)

    out = result.stdout + result.stderr
    assert "python" in out.lower()
    assert "pytest" in out.lower()


def test_seeded_content_has_no_real_name(tmp_path: Path) -> None:
    root = _make_root(tmp_path)

    _run_init(root)

    # Contract: seed は example の既定名のみ。実名を持ち込まない
    assert (root / "shared" / "baby.js").read_text(encoding="utf-8") == _EXAMPLE_CONTENT
