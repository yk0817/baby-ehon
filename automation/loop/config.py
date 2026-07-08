"""ループの設定（安全装置のつまみ）。

ここに「maker・予算・上限・自動化レベル・検証の厳しさ」を集約する。loop engineering で
最も大事なのは **暴走させない仕組み** なので、設定を1か所に集める。

設計の正: docs/automation/harness-loop.md §3.3 maker 切替 / §3.4 安全装置。
ラボ ~/harness-loop-lab/loop/config.py の写像（baby-ehon 向けに既定を調整）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# 自動化レベル（段階的ロールアウト L1→L2→L3）
LEVEL_REPORT = "L1"  # 計画だけ立てて報告。実装しない（一番安全）
LEVEL_ASSIST = "L2"  # 実装するが Draft PR を人間が merge（baby-ehon の既定）
LEVEL_AUTO = "L3"  # 実装まで自動。baby-ehon では使わない（公開リポ・自動 merge 禁止）

VALID_LEVELS = (LEVEL_REPORT, LEVEL_ASSIST, LEVEL_AUTO)

# maker エンジン（§3.3）。値は --maker / BABY_EHON_MAKER と一致させる。
MAKER_MOCK = "mock"  # フィクスチャ配置（オフライン・決定的）
MAKER_CLAUDE_P = "claude-p"  # claude -p（headless）。ローカル実行の本命
MAKER_LANGGRAPH = "langgraph"  # 既存 weekly_implementer（OpenAI SDK）。CI 無人運用向け

VALID_MAKERS = (MAKER_MOCK, MAKER_CLAUDE_P, MAKER_LANGGRAPH)


@dataclass(frozen=True)
class LoopConfig:
    """ループ1回分の設定。frozen=True で不変（途中で書き換えない）。"""

    spec_dir: Path  # 仕様書バンドル(automation/specs/<name>/)
    workspace: Path  # 成果物を作る場所
    maker: str = MAKER_CLAUDE_P  # maker エンジン（既定 = ローカル本命 claude -p）
    level: str = LEVEL_ASSIST  # 自動化レベル（既定 = L2・人間 merge 前提）
    model: str = "sonnet"  # 本番 maker のモデル（opus/sonnet/haiku）
    max_iters: int = 12  # maker 呼び出しの総回数上限（暴走防止）
    max_attempts: int = 3  # 1機能あたりの総試行回数上限（初回を含む）
    max_budget_usd: float = (
        1.0  # 本番時の総コスト上限（claude --max-budget-usd に渡す）
    )
    min_coverage: int = (
        80  # 単体テスト網羅率の床%（verify.sh の --cov-fail-under、§3.5）
    )
    allowed_tools: tuple[str, ...] = field(
        default_factory=lambda: (
            "Read",
            "Edit",
            "Write",
            "Bash(python3 -m pytest:*)",
            "Bash(python -m pytest:*)",
        )
    )

    def validate(self) -> LoopConfig:
        if self.maker not in VALID_MAKERS:
            raise ValueError(f"maker は {VALID_MAKERS} のいずれか: {self.maker!r}")
        if self.level not in VALID_LEVELS:
            raise ValueError(f"level は {VALID_LEVELS} のいずれか: {self.level!r}")
        if self.max_iters < 1:
            raise ValueError("max_iters は1以上")
        if self.max_attempts < 1:
            raise ValueError("max_attempts は1以上")
        if not (0 <= self.min_coverage <= 100):
            raise ValueError("min_coverage は 0〜100")
        if self.max_budget_usd < 0:
            raise ValueError("max_budget_usd は0以上")
        return self
