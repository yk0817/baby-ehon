"""maker（作り手）の抽象と差し替え（足場の maker エンジン）。

harness の肝は「作った本人に採点させない」こと。maker はプロダクトコードを書くだけで、
合否は checker（verify）が別に判定する。ここでは maker を1つのインタフェース（Maker）に
抽象化し、オフライン・決定的な MockMaker を用意する。実エンジン（claude -p / langgraph）は
PR-6 で追加し、build_maker のテーブルに1行足すだけで差し替わる（OCP）。

設計の正: docs/automation/harness-loop.md §3.2 maker/checker 分離 / §3.3 maker 抽象化。
ラボ ~/harness-loop-lab/loop の Maker 基底の写像。
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from automation.loop.config import (
    MAKER_CLAUDE_P,
    MAKER_LANGGRAPH,
    MAKER_MOCK,
    LoopConfig,
)
from automation.loop.state import Feature

# 既定のフィクスチャ置き場（§6）。build_maker が MockMaker に渡す。実フィクスチャは
# PR-5 で追加する。cwd に依存しないよう、このモジュールからの相対で解決する。
DEFAULT_FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


class Maker(ABC):
    """1回の起動で「ちょうど1機能」を実装する作り手のインタフェース。

    毎回まっさらに呼ばれる（記憶は AGENTS.md・state・テストにしか無い）。返り値は
    「何をしたか」のログ。**合否は返さない**——採点は checker が別に行う（§3.2）。
    """

    @abstractmethod
    def implement(
        self, feature: Feature, feedback: str = ""
    ) -> str:  # pragma: no cover
        """feature を1つ実装する。feedback は前回の失敗理由（無ければ空文字）。"""
        raise NotImplementedError


@dataclass(frozen=True)
class MockMaker(Maker):
    """フィクスチャを workspace に配置するだけの maker（外部依存ゼロ・無課金）。

    LLM もネットワークも使わないので、ループ自体をオフライン・決定的にテストできる。
    `fixtures_root/<feature.id>/` の中身を workspace 直下へコピーする。
    """

    workspace: Path
    fixtures_root: Path

    def implement(self, feature: Feature, feedback: str = "") -> str:
        src = self.fixtures_root / feature.id
        if not src.is_dir():
            # フィクスチャが無い＝mock は何も作れない。握りつぶさずログに残す
            # （checker が赤にするので、黙って done にはならない）。
            return f"mock: フィクスチャ無し（{src}）。何も配置しませんでした。"
        shutil.copytree(src, self.workspace, dirs_exist_ok=True)
        placed = sum(1 for p in src.rglob("*") if p.is_file())
        return f"mock: {feature.id} のフィクスチャ {placed} 件を workspace に配置しました。"


# 未実装エンジン（PR-6 で追加）。黙って通さず、明示的に失敗させる。
_NOT_IMPLEMENTED = {
    MAKER_CLAUDE_P: "claude-p maker は未実装です（PR-6 で追加予定）。",
    MAKER_LANGGRAPH: "langgraph maker は未実装です（PR-6 で追加予定）。",
}


def build_maker(config: LoopConfig) -> Maker:
    """config.maker の切替値に対応する Maker を返すファクトリ（§3.3）。

    新エンジンの追加は、この関数のテーブルに1行足すだけ（OCP）。未実装エンジンは
    NotImplementedError で明示的に弾く（黙って別物を返さない）。
    """
    config.validate()
    if config.maker == MAKER_MOCK:
        return MockMaker(
            workspace=config.workspace, fixtures_root=DEFAULT_FIXTURES_ROOT
        )
    if config.maker in _NOT_IMPLEMENTED:
        raise NotImplementedError(_NOT_IMPLEMENTED[config.maker])
    raise ValueError(f"未知の maker: {config.maker!r}")  # pragma: no cover
