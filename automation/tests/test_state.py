"""不変状態機械（automation/loop/state.py）の契約テスト。

Contract: ループの「記憶」を会話の外（ファイル）に置き、途中で落ちても再開できること。
状態遷移は **新オブジェクトを返し元を破壊しない**（coding-style: Immutability）。
設計の正: docs/automation/harness-loop.md §2 ②State / §3.1。
"""

from __future__ import annotations

import json

import pytest

from automation.loop.state import (
    DONE,
    FAILED,
    IN_PROGRESS,
    PENDING,
    Feature,
    LoopState,
)


def _sample_state() -> LoopState:
    """2機能（どちらも pending）の素の状態。"""
    return LoopState(
        project="demo",
        features=(
            Feature(id="F1", title="一", goal="g1", acceptance_test="test_f1.py"),
            Feature(id="F2", title="二", goal="g2", acceptance_test="test_f2.py"),
        ),
    )


# ─────────────────────────────────────────────
# 問い合わせ
# ─────────────────────────────────────────────
def test_next_actionable_returns_first_pending():
    # Contract: 次に着手すべきは pending/in_progress の先頭。
    state = _sample_state()
    assert state.next_actionable().id == "F1"


def test_next_actionable_skips_done():
    # Contract: done は飛ばして次の未完了を返す。
    state = _sample_state().mark_done("F1")
    assert state.next_actionable().id == "F2"


def test_next_actionable_none_when_all_finished():
    # Contract: 全機能が done/failed なら着手対象なし。
    state = _sample_state().mark_done("F1").mark_done("F2")
    assert state.next_actionable() is None


def test_is_complete_and_all_done():
    # Contract: is_complete=done|failed が全部、all_done=全部 done。
    state = _sample_state()
    assert state.is_complete() is False
    assert state.all_done() is False

    failed = state.record_failure("F1", "boom", max_attempts=1).mark_done("F2")
    assert failed.is_complete() is True  # F1=failed, F2=done → これ以上動かせない
    assert failed.all_done() is False  # failed が混じるので全 done ではない


# ─────────────────────────────────────────────
# 不変性（元を破壊しない）
# ─────────────────────────────────────────────
def test_mark_done_does_not_mutate_original():
    # Contract: 遷移は新オブジェクトを返し、元の state は不変。
    original = _sample_state()
    updated = original.mark_done("F1")

    assert original._get("F1").status == PENDING  # 元はそのまま
    assert updated._get("F1").status == DONE  # 新だけ変わる
    assert original is not updated


def test_feature_is_frozen():
    # Contract: Feature は frozen（属性の直接書き換え不可）。
    f = Feature(id="F1", title="一", goal="g", acceptance_test="t.py")
    with pytest.raises(Exception):
        f.status = DONE  # type: ignore[misc]


# ─────────────────────────────────────────────
# 遷移
# ─────────────────────────────────────────────
def test_mark_in_progress():
    state = _sample_state().mark_in_progress("F1")
    assert state._get("F1").status == IN_PROGRESS


def test_record_failure_retries_then_fails():
    # Contract: リトライ上限未満は in_progress のまま attempts を増やし、
    # 上限到達で failed。last_error も記録する。
    state = _sample_state()

    once = state.record_failure("F1", "err-1", max_attempts=2)
    assert once._get("F1").status == IN_PROGRESS
    assert once._get("F1").attempts == 1
    assert once._get("F1").last_error == "err-1"

    twice = once.record_failure("F1", "err-2", max_attempts=2)
    assert twice._get("F1").status == FAILED
    assert twice._get("F1").attempts == 2


def test_max_attempts_counts_total_tries_not_extra_retries():
    # Contract: max_attempts は「総試行回数」の上限（初回＋再挑戦の合計）であって、
    # 「初回に上乗せする再挑戦回数」ではない。max_attempts=3 なら 3 回目の試行で FAILED
    # （＝初回＋再挑戦2回）。#88: 旧名 max_retries が docs の「再挑戦上限」表記と実挙動
    # （総試行）でズレていたため、意味に合う名前へ統一したことを固定する回帰テスト。
    state = _sample_state()

    first = state.record_failure("F1", "e1", max_attempts=3)
    assert first._get("F1").status == IN_PROGRESS  # 1回目: まだ動かせる

    second = first.record_failure("F1", "e2", max_attempts=3)
    assert second._get("F1").status == IN_PROGRESS  # 2回目: まだ

    third = second.record_failure("F1", "e3", max_attempts=3)
    assert third._get("F1").status == FAILED  # 3回目（総試行=上限）で断念
    assert third._get("F1").attempts == 3


def test_mark_done_clears_last_error():
    # Contract: done になったら last_error は消える。
    state = _sample_state().record_failure("F1", "boom", max_attempts=3).mark_done("F1")
    assert state._get("F1").last_error == ""


def test_get_unknown_feature_raises():
    with pytest.raises(KeyError):
        _sample_state()._get("UNKNOWN")


# ─────────────────────────────────────────────
# 永続化（再開可能性）
# ─────────────────────────────────────────────
def test_save_then_load_roundtrip(tmp_path):
    # Contract: save→load で状態が完全復元できる（=途中から再開できる）。
    state = _sample_state().mark_done("F1").record_failure("F2", "boom", max_attempts=3)
    path = tmp_path / "state.json"

    state.save(path)
    restored = LoopState.load(path)

    assert restored == state
    assert restored._get("F1").status == DONE
    assert restored._get("F2").last_error == "boom"


def test_to_dict_does_not_expose_internal_state():
    # Contract: to_dict() の返値を変更しても元 state は不変（frozen の保護を貫く）。
    # 回帰: vars(f) は __dict__ への参照を返し frozen を無音で汚染するため asdict を使う。
    state = _sample_state()
    snapshot = state.to_dict()
    snapshot["features"][0]["status"] = IN_PROGRESS
    assert state._get("F1").status == PENDING


def test_save_is_atomic_no_temp_residue(tmp_path):
    # Contract: save は一時ファイル経由でアトミック置換し、後始末で .tmp を残さない。
    state = _sample_state()
    path = tmp_path / "state.json"
    state.save(path)
    assert LoopState.load(path) == state
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_overwrite_keeps_valid_file(tmp_path):
    # Contract: 既存 state.json への上書き保存後も常に valid JSON（再開可能）。
    path = tmp_path / "state.json"
    _sample_state().save(path)
    _sample_state().mark_done("F1").save(path)
    assert LoopState.load(path)._get("F1").status == DONE


def test_from_features_json_rejects_empty(tmp_path):
    # Contract: 空 spec は弾く。features=() だと is_complete/all_done が vacuous True
    # になり「何もせず全完了」扱いになるのを境界で防ぐ。
    features_json = tmp_path / "features.json"
    features_json.write_text(
        json.dumps({"project": "x", "features": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        LoopState.from_features_json(features_json)


def test_from_features_json(tmp_path):
    # Contract: spec の features.json から全 pending の初期状態を作れる。
    features_json = tmp_path / "features.json"
    features_json.write_text(
        json.dumps(
            {
                "project": "newbook",
                "features": [
                    {
                        "id": "F1-config",
                        "title": "config",
                        "goal": "config.js を作る",
                        "acceptance_test": "test_newbook.py",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = LoopState.from_features_json(features_json)
    assert state.project == "newbook"
    assert state._get("F1-config").status == PENDING
    assert state._get("F1-config").attempts == 0
