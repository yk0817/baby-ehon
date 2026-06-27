"""ループ設定（automation/loop/config.py）の契約テスト。

Contract: 安全装置（maker/level/上限）を1か所に集約し、不正値は validate() で弾く。
設計の正: docs/automation/harness-loop.md §3.3 maker 切替 / §3.4 安全装置。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.loop.config import LoopConfig


def _config(**overrides) -> LoopConfig:
    base = dict(spec_dir=Path("automation/specs/x"), workspace=Path("workspace"))
    base.update(overrides)
    return LoopConfig(**base)


def test_defaults_match_baby_ehon_policy():
    # Contract: 既定はローカル本命 claude-p・L2（人間 merge 前提）・coverage 床 80。
    cfg = _config()
    assert cfg.maker == "claude-p"
    assert cfg.level == "L2"
    assert cfg.min_coverage == 80
    assert cfg.max_iters == 12
    assert cfg.max_retries == 3


def test_config_is_frozen():
    # Contract: LoopConfig は不変（起動時に確定し途中で書き換えない）。
    cfg = _config()
    with pytest.raises(Exception):
        cfg.maker = "mock"  # type: ignore[misc]


@pytest.mark.parametrize("maker", ["mock", "claude-p", "langgraph"])
def test_validate_accepts_known_makers(maker):
    _config(maker=maker).validate()  # 例外が出なければ OK


def test_validate_rejects_unknown_maker():
    with pytest.raises(ValueError):
        _config(maker="claude-cli").validate()


def test_validate_rejects_unknown_level():
    with pytest.raises(ValueError):
        _config(level="L9").validate()


@pytest.mark.parametrize("field,value", [("max_iters", 0), ("max_retries", 0)])
def test_validate_rejects_non_positive_limits(field, value):
    with pytest.raises(ValueError):
        _config(**{field: value}).validate()


@pytest.mark.parametrize("coverage", [-1, 101])
def test_validate_rejects_out_of_range_coverage(coverage):
    with pytest.raises(ValueError):
        _config(min_coverage=coverage).validate()


def test_validate_returns_self_for_chaining():
    cfg = _config()
    assert cfg.validate() is cfg
