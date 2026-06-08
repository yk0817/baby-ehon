"""allowlist 制限付きでリポジトリ内容を読み出す。

LLM に晒すリポジトリ内容を限定するためのゲート。各役（リサーチャー / 作成者 /
こども）は、リポジトリ全体ではなく **ここが許可したファイルだけ** を文脈に載せる。

許可ポリシー（設計 §6.3 / §7.7）:

必ず含める:
  - ``CLAUDE.md``
  - ``README.md``
  - ``shared/ehon.js``
  - ``shared/ehon.css``
  - 全 ``*/config.js``（絵本ディレクトリごとの config）
  - 代表 1 冊の ``index.html``

必要に応じて（呼び出し側が ``extra_paths`` で渡す）:
  - 対象 Issue が指す ``*/index.html`` / ``*/theme.css``

安全策:

- **allowlist 外は読まない**（``secret.txt`` / ``.github/`` / ``shared/baby.js`` 等）。
- **パストラバーサル防御**: ``os.path.realpath`` で repo_root 配下に収まるかを検査し、
  ``..`` 等で外に出るパスは拒否（スキップ）する。拒否は「黙ってスキップ」で一貫させる
  （壊れた / 悪意ある extra_paths でパイプラインを止めない）。
- **ハードキャップ**: 合計サイズが ``MAX_TOTAL_BYTES`` を超えたら、それ以降の
  ファイルを読み込まず切り詰める。

設計: docs/automation/agent-pipeline.md §6.3 / §7.7
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

MAX_TOTAL_BYTES = 150 * 1024  # 150KB ハードキャップ（§6.3）

# 明示的に許可する固定パス（repo_root からの相対）。
_CORE_FILES = (
    "CLAUDE.md",
    "README.md",
    "shared/ehon.js",
    "shared/ehon.css",
)

# glob で許可するパターン（repo_root を走査して解決する）。
_ALLOWED_GLOBS = ("*/config.js",)

# 代表 1 冊として index.html を選ぶときの優先順。最初に見つかったものを使う。
_INDEX_HTML_GLOB = "*/index.html"

# extra_paths として追加許可してよいパターン（対象 Issue が指す任意の 1 冊）。
_EXTRA_ALLOWED_GLOBS = ("*/index.html", "*/theme.css")


def _matches_glob(rel_path: str, pattern: str) -> bool:
    """``rel_path`` が単純グロブ ``pattern`` に一致するか（PurePosixPath ベース）。"""
    return Path(rel_path).match(pattern)


def is_allowed(rel_path: str) -> bool:
    """相対パスが allowlist（core / glob）に含まれるか判定する。

    extra_paths 用のグロブ（``*/index.html`` / ``*/theme.css``）も許可対象に含める。
    """
    normalized = rel_path.replace(os.sep, "/")
    if normalized in _CORE_FILES:
        return True
    for pattern in (*_ALLOWED_GLOBS, *_EXTRA_ALLOWED_GLOBS):
        if _matches_glob(normalized, pattern):
            return True
    return False


def _within_root(repo_root: Path, rel_path: str) -> Path | None:
    """``rel_path`` を解決し、repo_root 配下に収まるなら絶対 Path を返す。

    トラバーサル（``..`` で外へ出る）や repo_root 外を指す場合は None。
    """
    root_real = os.path.realpath(repo_root)
    target_real = os.path.realpath(os.path.join(root_real, rel_path))
    # root 自身、または root/ 配下のみ許可。
    if target_real == root_real:
        return None
    if not target_real.startswith(root_real + os.sep):
        return None
    return Path(target_real)


def _collect_candidates(repo_root: Path, extra_paths: Sequence[str]) -> list[str]:
    """読込候補の相対パス列を allowlist に従って構築する（順序は決定的）。"""
    candidates: list[str] = []

    # 1. core ファイル（固定順）
    candidates.extend(_CORE_FILES)

    # 2. 全 */config.js（ディレクトリ名でソートして決定的に）
    for path in sorted(repo_root.glob("*/config.js")):
        candidates.append(path.relative_to(repo_root).as_posix())

    # 3. 代表 1 冊の index.html（最初の 1 つだけ）
    index_files = sorted(repo_root.glob(_INDEX_HTML_GLOB))
    if index_files:
        candidates.append(index_files[0].relative_to(repo_root).as_posix())

    # 4. extra_paths（allowlist を満たすものだけ）
    for extra in extra_paths:
        candidates.append(extra.replace(os.sep, "/"))

    # 重複排除（最初の出現を保持）
    seen: set[str] = set()
    unique: list[str] = []
    for rel in candidates:
        if rel not in seen:
            seen.add(rel)
            unique.append(rel)
    return unique


def read_allowlisted(
    repo_root: str | Path,
    *,
    extra_paths: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """allowlist 内のファイルを読み、``{相対パス: 内容}`` を返す。

    - allowlist 外・存在しない・トラバーサルは黙ってスキップする。
    - 合計サイズが ``MAX_TOTAL_BYTES`` を超えたら以降を読まずに切り詰める。

    ``env`` は将来の上書き用フック（現状未使用だが、他モジュールと注入形を揃える）。
    """
    _ = env  # 予約引数（注入形の一貫性のため）
    root = Path(repo_root)
    result: dict[str, str] = {}
    total_bytes = 0

    for rel in _collect_candidates(root, extra_paths):
        if not is_allowed(rel):
            continue
        target = _within_root(root, rel)
        if target is None or not target.is_file():
            continue

        data = target.read_bytes()
        if total_bytes + len(data) > MAX_TOTAL_BYTES:
            break
        result[rel] = data.decode("utf-8", errors="replace")
        total_bytes += len(data)

    return result
