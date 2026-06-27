"""verify.sh ゲート③（プライバシー）の実体 — 絵本 config.js の実名混入を弾く。

絵本の ``<slug>/config.js`` が ``__NAME__`` プレースホルダを使い、実名・連絡先・住所が
混入していないかを検査する薄い CLI。判定ロジックは二重実装せず、既存の単一ガード
``.github/scripts/common/privacy.py`` を再利用する（``assert_name_placeholder`` ＋
``scan_text``）。

終了コード: 0 = 違反なし / 1 = 違反あり。違反メッセージには **実値を出さない**
（ログ・PR に流れても秘匿が漏れないように。設計 §8.6）。denylist は env
``BABY_EHON_NAME_DENYLIST`` から読む（値はコードに書かない）。

設計: docs/automation/harness-loop.md §3.5 ③ / §7。
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

# 既存ガードを再利用するため、.github/scripts を import パスに足す。
# このファイルは <repo>/automation/harness/privacy_gate.py。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / ".github" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from common import privacy  # noqa: E402  (sys.path 調整後に import する必要がある)


def find_config_js(root: Path) -> list[Path]:
    """``<slug>/config.js``（絵本1冊ぶんの設定）を列挙する。決定的にソート。"""
    return sorted(root.glob("*/config.js"))


def scan_config(path: Path, denylist: Sequence[str] = ()) -> list[privacy.Violation]:
    """config.js 1ファイルを検査し、違反のリストを返す（空なら clean）。"""
    text = path.read_text(encoding="utf-8")
    return [
        *privacy.assert_name_placeholder(text),
        *privacy.scan_text(text, denylist),
    ]


def scan_all(
    paths: Sequence[Path], denylist: Sequence[str] = ()
) -> list[tuple[Path, privacy.Violation]]:
    """複数 config.js を検査し、(path, violation) の列を返す。"""
    found: list[tuple[Path, privacy.Violation]] = []
    for path in paths:
        for violation in scan_config(path, denylist):
            found.append((path, violation))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    denylist = privacy.load_denylist()
    paths = [Path(a) for a in args] if args else find_config_js(_REPO_ROOT)

    missing = [p for p in paths if not p.is_file()]
    if missing:
        print("✗ privacy gate: 対象ファイルが見つかりません", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    violations = scan_all(paths, denylist)
    if violations:
        print("✗ privacy gate: 違反あり（実値はマスク）", file=sys.stderr)
        for path, violation in violations:
            print(f"  - {path}: [{violation.kind}] {violation.message}", file=sys.stderr)
        return 1

    print(f"✓ privacy gate: config.js {len(paths)} 件を検査・違反なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
