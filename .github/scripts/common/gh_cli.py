"""gh CLI の薄い subprocess ラッパ（ローカルデバッグ用）。

CI 本番は github_io.py（PyGithub）を使うが、ローカルで手元のログイン済み ``gh`` を
使って動作確認したいときにこちらを使う。``runner`` を注入できるので、テストでは
fake を渡して実際の ``gh`` を呼ばずに検証できる。

設計: docs/automation/agent-pipeline.md §3.1
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

GH = "gh"


def run_gh(
    args: Sequence[str],
    *,
    runner=subprocess.run,
    check: bool = True,
) -> Any:
    """``gh <args...>`` を実行する。``runner`` 注入でテスト時に差し替え可能。

    戻り値は ``runner`` の返り値（既定では ``subprocess.CompletedProcess``）。
    """
    return runner(
        [GH, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def gh_json(
    args: Sequence[str],
    *,
    runner=subprocess.run,
) -> Any:
    """``gh ... --json ...`` の stdout を JSON としてパースして返す。"""
    completed = run_gh(args, runner=runner)
    return json.loads(completed.stdout)
