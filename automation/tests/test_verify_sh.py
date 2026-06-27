"""verify.sh（足場③ Verification）の契約テスト。

Contract: §3.5 の4ゲート（① e2e ② 単体+coverage ③ privacy ④ 契約の不可侵）を順に走らせ、
**全 pass で exit 0 / 1つでも fail で exit≠0** を返す。完了判定は自己申告ではなく
スクリプトの exit code に集約する（人間・loop・CI が同じ1コマンドで同じ赤緑）。

なぜこの挙動が必要か: maker→checker ループの「緑」を客観的に決める単一の合否ゲート。
ここでは**集約ロジック（全ゲートを走らせ総合判定する）**を、各ゲートを差し替え可能な
コマンド（テスト seam）に置き換えて hermetic に固定する。既定値は本物のコマンド。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_VERIFY_SH = Path(__file__).resolve().parents[1] / "harness" / "verify.sh"
_BASE_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"


def _run_verify(root: Path, *, gates: dict[str, str], extra_env: dict | None = None):
    env = {
        "BABY_EHON_ROOT": str(root),
        "VERIFY_PYTHON": sys.executable,
        "PATH": _BASE_PATH,
        **gates,
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", str(_VERIFY_SH)], env=env, capture_output=True, text=True
    )


def _all_pass_gates(marker_dir: Path) -> dict[str, str]:
    """4ゲートを「マーカーを残して成功する」フェイクに差し替える。"""
    return {
        "VERIFY_E2E_CMD": f"bash -c 'touch {marker_dir}/e2e; true'",
        "VERIFY_UNIT_CMD": f"bash -c 'touch {marker_dir}/unit; true'",
        "VERIFY_PRIVACY_CMD": f"bash -c 'touch {marker_dir}/privacy; true'",
        "VERIFY_ACCEPTANCE_CMD": f"bash -c 'touch {marker_dir}/acceptance; true'",
    }


def test_exit_zero_when_all_gates_pass(tmp_path: Path) -> None:
    markers = tmp_path / "m"
    markers.mkdir()

    result = _run_verify(tmp_path, gates=_all_pass_gates(markers))

    assert result.returncode == 0, result.stdout + result.stderr
    # Contract: 4ゲートすべてが実際に実行される
    assert {p.name for p in markers.iterdir()} == {"e2e", "unit", "privacy", "acceptance"}


def test_exit_nonzero_when_one_gate_fails(tmp_path: Path) -> None:
    markers = tmp_path / "m"
    markers.mkdir()
    gates = _all_pass_gates(markers)
    gates["VERIFY_PRIVACY_CMD"] = f"bash -c 'touch {markers}/privacy; false'"

    result = _run_verify(tmp_path, gates=gates)

    assert result.returncode != 0


def test_runs_all_gates_even_after_a_failure(tmp_path: Path) -> None:
    markers = tmp_path / "m"
    markers.mkdir()
    gates = _all_pass_gates(markers)
    # 最初のゲート(e2e)が落ちても、後続(acceptance)まで走り切ること
    gates["VERIFY_E2E_CMD"] = f"bash -c 'touch {markers}/e2e; false'"

    result = _run_verify(tmp_path, gates=gates)

    assert result.returncode != 0
    assert (markers / "acceptance").exists(), "fail後も後続ゲートを走らせていない"


def test_summary_marks_failed_gate(tmp_path: Path) -> None:
    markers = tmp_path / "m"
    markers.mkdir()
    gates = _all_pass_gates(markers)
    gates["VERIFY_UNIT_CMD"] = f"bash -c 'touch {markers}/unit; false'"

    result = _run_verify(tmp_path, gates=gates)
    out = result.stdout + result.stderr

    # サマリで落ちたゲート名が分かる（どれが赤かを人間が即把握できる）
    assert "unit" in out.lower()


# ── 既定のゲート④（契約の不可侵）は本物の git 差分で判定する ─────────────────
def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={"PATH": _BASE_PATH, "HOME": str(root),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"},
    )


def _init_repo_with_acceptance(root: Path) -> Path:
    (root / "automation" / "specs" / "issue-1" / "acceptance").mkdir(parents=True)
    contract = root / "automation" / "specs" / "issue-1" / "acceptance" / "test_x.py"
    contract.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed contract")
    return contract


def test_acceptance_gate_passes_when_contract_unchanged(tmp_path: Path) -> None:
    _init_repo_with_acceptance(tmp_path)
    markers = tmp_path / "m"
    markers.mkdir()
    gates = _all_pass_gates(markers)
    del gates["VERIFY_ACCEPTANCE_CMD"]  # 既定（本物の git 差分）を使う

    result = _run_verify(tmp_path, gates=gates, extra_env={"HOME": str(tmp_path)})

    assert result.returncode == 0, result.stdout + result.stderr


def test_acceptance_gate_fails_when_contract_modified(tmp_path: Path) -> None:
    contract = _init_repo_with_acceptance(tmp_path)
    contract.write_text("def test_x():\n    assert False  # maker が契約を緩めた\n", encoding="utf-8")
    markers = tmp_path / "m"
    markers.mkdir()
    gates = _all_pass_gates(markers)
    del gates["VERIFY_ACCEPTANCE_CMD"]

    result = _run_verify(tmp_path, gates=gates, extra_env={"HOME": str(tmp_path)})

    # Contract: 受け入れ e2e（契約）の改変を検出して赤にする（自己採点の防止）
    assert result.returncode != 0
