"""ループ本体（run_loop）と maker 抽象（MockMaker/build_maker）の契約テスト。

Contract: maker→checker→state 更新の「一周」が、外部依存ゼロ・決定的に回ること。
  - checker は注入可能（実 e2e を回さない）＝ maker と checker が分離（自己採点しない）
  - checker 緑で pending→done、赤で record_failure→リトライ→上限で failed
  - max_iters で全体を打ち切る（暴走しない）
  - 途中 state を save/load して再開できる（PR-1 の不変 state を使用）
設計の正: docs/automation/harness-loop.md §3.1 一周 / §3.2 分離 / §3.3 抽象 / §3.4 上限。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation.loop.config import LoopConfig
from automation.loop.maker import Maker, MockMaker, build_maker
from automation.loop.run_loop import (
    _default_state_path,
    _tail,
    load_or_init_state,
    main,
    make_verify_checker,
    run_loop,
)
from automation.loop.state import DONE, FAILED, IN_PROGRESS, PENDING, LoopState


# ── ヘルパ ─────────────────────────────────────────────
def _write_features(spec_dir: Path, ids=("F1", "F2")) -> Path:
    spec_dir.mkdir(parents=True, exist_ok=True)
    features = [
        {"id": i, "title": i, "goal": f"{i} を作る", "acceptance_test": f"test_{i}.py"}
        for i in ids
    ]
    fj = spec_dir / "features.json"
    fj.write_text(
        json.dumps({"project": "demo", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return fj


def _fixtures(root: Path, ids=("F1", "F2")) -> Path:
    """各 feature の参照実装（marker ファイル）を fixtures_root/<id>/ に置く。"""
    for i in ids:
        d = root / i
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{i.lower()}.txt").write_text(f"{i} placed", encoding="utf-8")
    return root


def _config(tmp_path: Path, **overrides) -> LoopConfig:
    base = dict(
        spec_dir=tmp_path / "spec",
        workspace=tmp_path / "ws",
        maker="mock",
        level="L2",
    )
    base.update(overrides)
    return LoopConfig(**base)


def _state(tmp_path: Path, ids=("F1", "F2")) -> LoopState:
    return LoopState.from_features_json(_write_features(tmp_path / "spec", ids))


# checker（注入・決定的）。maker とは別主体なので自己採点にならない。
def _green(feature):
    return True, "ok"


def _red(feature):
    return False, "boom: assertion failed"


def _green_after_one(feature):
    # 1回失敗させてから緑（attempts は record_failure で増える）。
    ok = feature.attempts >= 1
    return ok, "retry ok" if ok else "boom"


class RecordingMaker(Maker):
    """呼び出し（feature.id, feedback）を記録する maker。

    「毎回まっさら起動」「前回失敗が feedback として渡る」ことの検証用。
    """

    def __init__(self, inner: Maker | None = None):
        self.calls: list[tuple[str, str, str]] = []  # (id, feedback, status)
        self._inner = inner

    def implement(self, feature, feedback: str = "") -> str:
        self.calls.append((feature.id, feedback, feature.status))
        if self._inner is not None:
            return self._inner.implement(feature, feedback)
        return f"recorded {feature.id}"


# ── MockMaker ─────────────────────────────────────────
def test_mock_maker_places_fixture_files(tmp_path):
    # Contract: MockMaker は fixtures_root/<id>/ の中身を workspace 直下へ配置する。
    ws = tmp_path / "ws"
    fx = _fixtures(tmp_path / "fx", ids=("F1",))
    maker = MockMaker(workspace=ws, fixtures_root=fx)
    state = _state(tmp_path, ids=("F1",))

    log = maker.implement(state._get("F1"))

    assert (ws / "f1.txt").read_text(encoding="utf-8") == "F1 placed"
    assert "F1" in log


def test_mock_maker_missing_fixture_does_not_crash(tmp_path):
    # Contract: フィクスチャが無くても例外を投げず、その旨をログに残す（黙って done にしない）。
    ws = tmp_path / "ws"
    maker = MockMaker(workspace=ws, fixtures_root=tmp_path / "empty")
    state = _state(tmp_path, ids=("F1",))

    log = maker.implement(state._get("F1"))

    assert "フィクスチャ無し" in log
    assert not ws.exists() or list(ws.iterdir()) == []


# ── build_maker（ファクトリ／OCP） ─────────────────────
def test_build_maker_returns_mock(tmp_path):
    maker = build_maker(_config(tmp_path, maker="mock"))
    assert isinstance(maker, MockMaker)


@pytest.mark.parametrize("engine", ["claude-p", "langgraph"])
def test_build_maker_rejects_unimplemented(tmp_path, engine):
    # Contract: 未実装エンジンは黙って通さず NotImplementedError で明示的に失敗する。
    with pytest.raises(NotImplementedError):
        build_maker(_config(tmp_path, maker=engine))


# ── 一周（maker→checker→state） ───────────────────────
def test_fixtures_placed_and_green_marks_done(tmp_path):
    # Contract: MockMaker が実物を配置し、注入 checker が緑なら pending→done。
    ws = tmp_path / "ws"
    fx = _fixtures(tmp_path / "fx", ids=("F1", "F2"))
    maker = MockMaker(workspace=ws, fixtures_root=fx)
    state = _state(tmp_path)

    report = run_loop(_config(tmp_path), maker, _green, state)

    assert report.state.all_done()
    assert report.stopped_reason == "complete"
    assert set(report.done) == {"F1", "F2"}
    assert report.iterations == 2
    assert (ws / "f1.txt").exists() and (ws / "f2.txt").exists()


def test_red_retries_then_fails(tmp_path):
    # Contract: checker が赤を返すと attempts が増え、max_attempts 到達で failed。
    maker = MockMaker(workspace=tmp_path / "ws", fixtures_root=tmp_path / "fx")
    state = _state(tmp_path, ids=("F1",))

    report = run_loop(_config(tmp_path, max_attempts=2), maker, _red, state)

    assert set(report.failed) == {"F1"}
    assert report.stopped_reason == "all_failed"  # 全 FAILED は complete と区別する
    assert report.state._get("F1").status == FAILED
    assert report.state._get("F1").attempts == 2


def test_red_once_then_green_completes(tmp_path):
    # Contract: 1回赤→再試行→緑 で done。attempts=1 が残る。
    maker = MockMaker(workspace=tmp_path / "ws", fixtures_root=tmp_path / "fx")
    state = _state(tmp_path, ids=("F1",))

    report = run_loop(_config(tmp_path, max_attempts=3), maker, _green_after_one, state)

    assert report.state._get("F1").status == DONE
    assert report.state._get("F1").attempts == 1


def test_max_iters_stops_runaway(tmp_path):
    # Contract: max_iters で総呼び出しを打ち切る（max_attempts が大きくても暴走しない）。
    maker = MockMaker(workspace=tmp_path / "ws", fixtures_root=tmp_path / "fx")
    state = _state(tmp_path, ids=("F1",))

    report = run_loop(
        _config(tmp_path, max_iters=3, max_attempts=99), maker, _red, state
    )

    assert report.stopped_reason == "max_iters"
    assert report.iterations == 3
    assert report.state._get("F1").status == IN_PROGRESS  # まだ failed になっていない


def test_maker_called_fresh_with_feedback(tmp_path):
    # Contract: maker は毎回まっさらに呼ばれ、前回の失敗が feedback として渡る（自己採点しない）。
    maker = RecordingMaker()
    state = _state(tmp_path, ids=("F1",))

    run_loop(_config(tmp_path, max_attempts=2), maker, _red, state)

    assert [c[0] for c in maker.calls] == ["F1", "F1"]  # 同じ feature を2回、独立起動
    assert maker.calls[0][1] == ""  # 初回は feedback 無し
    assert "boom" in maker.calls[1][1]  # 2回目は前回の verify ログが渡る
    assert maker.calls[0][2] == IN_PROGRESS  # maker には着手中(=最新)の feature が渡る


# ── 再開（state 永続化） ───────────────────────────────
def test_resume_from_saved_state(tmp_path):
    # Contract: 途中 state を save→load して再開できる（PR-1 の不変 state を使用）。
    maker = MockMaker(workspace=tmp_path / "ws", fixtures_root=tmp_path / "fx")
    state = _state(tmp_path)
    state_file = tmp_path / "state.json"
    cfg = _config(tmp_path)

    first = run_loop(_config(tmp_path, max_iters=1), maker, _green, state, state_file)
    assert first.stopped_reason == "max_iters"
    assert first.state._get("F1").status == DONE
    assert first.state._get("F2").status == PENDING

    resumed = load_or_init_state(cfg, state_file)  # ファイルから再開
    second = run_loop(cfg, maker, _green, resumed, state_file)
    assert second.state.all_done()


def test_load_or_init_state_from_features_json(tmp_path):
    # Contract: state が無ければ spec の features.json から全 pending で作る。
    cfg = _config(tmp_path)
    _write_features(cfg.spec_dir)
    state = load_or_init_state(cfg, tmp_path / "missing.json")
    assert {f.id for f in state.features} == {"F1", "F2"}
    assert all(f.status == PENDING for f in state.features)


# ── L1（レポートのみ・実装しない） ─────────────────────
def test_l1_reports_without_calling_maker(tmp_path):
    # Contract: level=L1 は現状報告だけで maker を呼ばない（一番安全なロールアウト）。
    maker = RecordingMaker()
    state = _state(tmp_path)

    report = run_loop(_config(tmp_path, level="L1"), maker, _green, state)

    assert report.stopped_reason == "report_only"
    assert maker.calls == []  # maker は呼ばれない
    assert report.done == ()  # 実装しないので done は増えない


def test_l2_requires_maker_and_checker(tmp_path):
    # Contract: L2/L3 で maker/checker が無ければ弾く（黙って空回りしない）。
    with pytest.raises(ValueError):
        run_loop(_config(tmp_path), None, None, _state(tmp_path, ids=("F1",)))


# ── 既定 checker（verify.sh ラッパ）／CLI ──────────────
def test_make_verify_checker_translates_exit_code(tmp_path):
    # Contract: 既定 checker は verify.sh の exit code を (緑, ログ) に写す（決定的な偽物で検証）。
    for code, expect in ((0, True), (1, False)):
        root = tmp_path / f"root{code}"
        script = root / "automation" / "harness" / "verify.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            f"#!/usr/bin/env bash\necho stub\nexit {code}\n", encoding="utf-8"
        )
        checker = make_verify_checker(root)

        ok, log = checker(_state(tmp_path, ids=("F1",))._get("F1"))

        assert ok is expect
        assert "stub" in log


def test_tail_truncates_long_logs():
    # Contract: state に残す失敗ログは上限で切り詰める（state.json 肥大を防ぐ）。
    short = _tail("ok", "did")
    assert "[verify]" in short and not short.startswith("…")

    long = _tail("x" * 2000, "did")
    assert long.startswith("…") and len(long) <= 801


def test_default_state_path_uses_spec_name():
    assert (
        _default_state_path(Path("automation/specs/issue-86")).name == "issue-86.json"
    )


def test_main_l1_smoke(tmp_path, capsys):
    # Contract: CLI が L1 で完走し、progress.md を書き、exit 0 を返す（未実装 maker でも安全）。
    spec_dir = tmp_path / "spec"
    _write_features(spec_dir)
    state_file = tmp_path / "state" / "s.json"

    rc = main(
        [
            "--spec",
            str(spec_dir),
            "--level",
            "L1",
            "--workspace",
            str(tmp_path / "ws"),
            "--state",
            str(state_file),
        ]
    )

    assert rc == 0
    assert (state_file.parent / "progress.md").exists()
    assert "ループ結果" in capsys.readouterr().out
