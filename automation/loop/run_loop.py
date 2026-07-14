"""ループ本体（足場の loop）。plan → (maker→checker)×N → report。

一周のフロー（§3.1）:
    state を読む（無ければ features.json から作る）
    while 未完了 かつ 上限内:
        次の未完了 feature を1つ取る
        maker.implement(feature, feedback=前回エラー)   # 作る（自己採点しない）
        ok, log = checker(feature)                     # 点検（e2e + pytest = verify.sh）
        ok なら done、赤なら record_failure して再試行    # State を不変更新
        state を保存                                    # 会話の外に記憶を残す（再開可能）
    report()

**checker は注入可能**（テストは決定的な checker を差し込み、実 e2e を回さない）。
既定は PR-2 の verify.sh を1コマンドで回すラッパ（make_verify_checker）。

設計の正: docs/automation/harness-loop.md §3.1 一周 / §3.2 分離 / §3.4 安全装置。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from automation.loop.config import LEVEL_REPORT, LoopConfig
from automation.loop.maker import Maker, build_maker
from automation.loop.state import DONE, FAILED, IN_PROGRESS, PENDING, Feature, LoopState

# checker: feature を受け取り (緑か, ログ) を返す。verify.sh の exit code を写す想定。
# maker とは別主体（別 Callable）＝ 作った本人に採点させない（§3.2）。
Checker = Callable[[Feature], "tuple[bool, str]"]

_ERROR_TAIL = (
    800  # state に残す失敗ログの上限。長い verify 出力で state.json が肥大化しない
)


@dataclass(frozen=True)
class LoopReport:
    """ループ1回の結果サマリ（人間・CI が読む）。"""

    state: LoopState
    iterations: int  # maker を呼んだ総回数（max_iters と対応）
    done: tuple[str, ...]
    failed: tuple[str, ...]
    pending: tuple[str, ...]
    stopped_reason: str  # complete / max_iters / report_only

    def summary(self) -> str:
        return (
            "\n".join(
                [
                    f"# ループ結果: {self.state.project}",
                    "",
                    f"- 停止理由: {self.stopped_reason}",
                    f"- maker 呼び出し回数: {self.iterations}",
                    f"- done: {', '.join(self.done) or '(なし)'}",
                    f"- failed: {', '.join(self.failed) or '(なし)'}",
                    f"- pending: {', '.join(self.pending) or '(なし)'}",
                ]
            )
            + "\n"
        )


def _tail(verify_log: str, maker_log: str) -> str:
    combined = f"[maker] {maker_log}\n[verify]\n{verify_log}".strip()
    if len(combined) <= _ERROR_TAIL:
        return combined
    return "…" + combined[-_ERROR_TAIL:]


def _snapshot(state: LoopState, iterations: int, stopped_reason: str) -> LoopReport:
    return LoopReport(
        state=state,
        iterations=iterations,
        done=tuple(f.id for f in state.features if f.status == DONE),
        failed=tuple(f.id for f in state.features if f.status == FAILED),
        pending=tuple(
            f.id for f in state.features if f.status in (PENDING, IN_PROGRESS)
        ),
        stopped_reason=stopped_reason,
    )


def run_loop(
    config: LoopConfig,
    maker: Maker | None,
    checker: Checker | None,
    state: LoopState,
    state_path: Path | str | None = None,
) -> LoopReport:
    """一周のフロー（§3.1）を回して結果を返す。checker は注入可能。"""
    config.validate()

    # L1（レポートのみ）: 実装せず現状だけ返す（一番安全な段階的ロールアウト）。
    if config.level == LEVEL_REPORT:
        return _snapshot(state, iterations=0, stopped_reason="report_only")

    if maker is None or checker is None:
        raise ValueError("L2/L3 では maker と checker の注入が必要です")

    iterations = 0
    stopped_reason = ""
    while True:
        if state.is_complete():
            # DONE も FAILED も is_complete。監視が誤読しないよう成否を区別して残す。
            stopped_reason = "complete" if state.all_done() else "all_failed"
            break
        if iterations >= config.max_iters:
            stopped_reason = "max_iters"  # 総呼び出し上限で打ち切り（暴走防止）
            break

        feature = state.next_actionable()
        if (
            feature is None
        ):  # pragma: no cover  # is_complete=False なら通常来ない（防御的）
            stopped_reason = "complete" if state.all_done() else "all_failed"
            break

        state = state.mark_in_progress(feature.id)
        feature = state._get(
            feature.id
        )  # IN_PROGRESS を反映した最新を maker/checker へ渡す
        iterations += 1

        # maker は毎回まっさら。前回の失敗理由だけを feedback として渡す。
        maker_log = maker.implement(feature, feedback=feature.last_error)
        ok, verify_log = checker(feature)

        if ok:
            state = state.mark_done(feature.id)
        else:
            state = state.record_failure(
                feature.id, _tail(verify_log, maker_log), config.max_attempts
            )

        if state_path is not None:
            state.save(state_path)  # 1周ごとに永続化＝途中で落ちても再開できる

    return _snapshot(state, iterations, stopped_reason)


def make_verify_checker(root: Path | None = None) -> Checker:
    """既定 checker: PR-2 の verify.sh を回し、exit code で合否を返す。

    実 e2e/pytest を起動するので、mock テストでは決定的な checker を注入してこれを使わない。
    """
    base = (root or _repo_root()).resolve()
    script = base / "automation" / "harness" / "verify.sh"

    def _check(feature: Feature) -> tuple[bool, str]:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(base),
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)

    return _check


def load_or_init_state(config: LoopConfig, state_path: Path | str) -> LoopState:
    """state.json があれば読む（再開）、無ければ spec の features.json から作る（§3.1）。"""
    p = Path(state_path)
    if p.exists():
        return LoopState.load(p)
    return LoopState.from_features_json(config.spec_dir / "features.json")


def _repo_root() -> Path:
    # automation/loop/run_loop.py → リポジトリルート
    return Path(__file__).resolve().parents[2]


def _default_state_path(spec_dir: Path) -> Path:
    return _repo_root() / "automation" / "state" / f"{spec_dir.name}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="baby-ehon harness×loop ランナー")
    parser.add_argument(
        "--spec", required=True, help="spec バンドル（automation/specs/<N>/）"
    )
    parser.add_argument("--maker", default=None, help="mock / claude-p / langgraph")
    parser.add_argument("--level", default=None, help="L1 / L2 / L3")
    parser.add_argument(
        "--workspace", default=None, help="成果物を作る場所（既定=リポジトリルート）"
    )
    parser.add_argument("--state", default=None, help="state.json のパス")
    args = parser.parse_args(argv)

    spec_dir = Path(args.spec)
    workspace = Path(args.workspace) if args.workspace else _repo_root()
    overrides: dict[str, str] = {}
    if args.maker is not None:
        overrides["maker"] = args.maker
    if args.level is not None:
        overrides["level"] = args.level
    config = LoopConfig(spec_dir=spec_dir, workspace=workspace, **overrides).validate()

    state_path = Path(args.state) if args.state else _default_state_path(spec_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = load_or_init_state(config, state_path)

    # L1 は maker/checker を使わない（未実装エンジンでも安全に現状把握できる）。
    maker = None
    checker = None
    if config.level != LEVEL_REPORT:
        maker = build_maker(config)
        checker = make_verify_checker()

    report = run_loop(config, maker, checker, state, state_path)

    (state_path.parent / "progress.md").write_text(report.summary(), encoding="utf-8")
    print(report.summary())

    return 0 if (config.level == LEVEL_REPORT or report.state.all_done()) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
