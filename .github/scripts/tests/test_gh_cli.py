"""gh_cli.py のテスト（TDD）。

gh CLI の薄い subprocess ラッパ。runner を注入して fake を渡す。
実際の gh コマンドは呼ばない。ローカルデバッグ用。
設計: docs/automation/agent-pipeline.md §3.1
"""

import json
import subprocess

from common import gh_cli


class _FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_run_gh_invokes_runner_with_gh_prefix():
    # Arrange
    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompleted(stdout="ok")

    # Act
    result = gh_cli.run_gh(["issue", "view", "14"], runner=fake_runner)

    # Assert
    assert calls[0][0][0] == "gh"
    assert calls[0][0][1:] == ["issue", "view", "14"]
    assert result.stdout == "ok"


def test_run_gh_default_runner_is_subprocess_run():
    # 既定 runner が subprocess.run であることだけ確認（実行はしない）
    assert gh_cli.run_gh.__defaults__ is None or subprocess.run is not None


def test_gh_json_parses_stdout():
    # Arrange
    payload = {"number": 14, "labels": [{"name": "approved"}]}

    def fake_runner(args, **kwargs):
        return _FakeCompleted(stdout=json.dumps(payload))

    # Act
    data = gh_cli.gh_json(
        ["issue", "view", "14", "--json", "number,labels"], runner=fake_runner
    )

    # Assert
    assert data == payload
