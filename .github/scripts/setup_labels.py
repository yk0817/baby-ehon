"""自動化パイプラインに必要な GitHub ラベルを冪等に作成 / 更新する小スクリプト。

設計の §2.1 / §2.2 / §13（事前作業）で要求されるラベル一式を、リポジトリに過不足なく
揃えるためのもの。既存ラベルは color / description を更新し、未作成なら作成する
（**二重作成しない**）。人間が初期セットアップで 1 回流す想定。

実行（``.github/scripts`` から）::

    # 実際に作成 / 更新する
    GITHUB_REPOSITORY=yk0817/baby-ehon python setup_labels.py

    # 何もせず、対象ラベル一覧を stdout に出すだけ（GITHUB 系未設定でも落ちない）
    DRY_RUN=true python setup_labels.py

環境変数:

- ``GITHUB_REPOSITORY`` : ``owner/name``。未設定なら ``gh`` の既定リポジトリを使う
  （``gh label`` は省略時にカレントリポジトリへ向く）。
- ``GITHUB_TOKEN``       : ``gh`` が認証に使う（gh ログイン済みなら不要）。
- ``DRY_RUN``           : ``true`` で作成 / 更新を行わず一覧表示のみ。

実装は ``gh label`` を subprocess で叩く薄いもの。``runner`` を注入できるのでテスト時に
実際の ``gh`` を呼ばずに検証できる（common/gh_cli.py と同じ流儀）。

privacy: 出力はラベル名 / 色 / 説明のみ。個人名・トークン値は出さない。

設計: docs/automation/agent-pipeline.md §2.1 / §2.2 / §13
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

GH = "gh"
REPO_ENV = "GITHUB_REPOSITORY"
DRY_RUN_ENV = "DRY_RUN"


@dataclass(frozen=True)
class LabelSpec:
    """1 ラベルの定義。``color`` は ``#`` なしの 6 桁 16 進。"""

    name: str
    color: str
    description: str


# パイプラインで使う全ラベル（§2.1 / §2.2 / §13）。
# 色は GitHub の標準パレットから役割が読み取りやすいものを選んだ。
LABELS: tuple[LabelSpec, ...] = (
    LabelSpec(
        "approved",
        "0E8A16",
        "人間が実装を承認（作成者 Weekly の入口ゲート §2.2）",
    ),
    LabelSpec(
        "stage:researched",
        "1D76DB",
        "リサーチャー① が調査・採点済み（§2.1）",
    ),
    LabelSpec(
        "stage:implemented",
        "5319E7",
        "作成者 Weekly が Draft PR 化済み（§2.1）",
    ),
    LabelSpec(
        "stage:child-reviewed",
        "FBCA04",
        "こどもレビュワーが所見済み（Approve はしない、§2.1）",
    ),
    LabelSpec(
        "claude-proposed",
        "C5DEF5",
        "リサーチャー② が自動起票した Issue（§5）",
    ),
    LabelSpec(
        "needs-child-review",
        "D93F0B",
        "こどもレビュワーの所見待ち（Weekly が付与、§6 / §7）",
    ),
    LabelSpec(
        "automation:skip",
        "E4E669",
        "自動処理の対象外にする（人間が付与、§2.1）",
    ),
    LabelSpec(
        "score-lock",
        "BFD4F2",
        "claude-score の自動更新を固定する（人間が付与）",
    ),
)


def _repo_args(env: Mapping[str, str]) -> list[str]:
    """``--repo owner/name`` を返す。未設定なら空（gh の既定リポジトリに従う）。"""
    repo = env.get(REPO_ENV, "").strip()
    return ["--repo", repo] if repo else []


def is_dry_run(env: Mapping[str, str]) -> bool:
    """``DRY_RUN`` が truthy（true/1/yes、大小無視）なら True。"""
    return env.get(DRY_RUN_ENV, "").strip().lower() in {"true", "1", "yes"}


def ensure_label(
    spec: LabelSpec,
    *,
    env: Mapping[str, str],
    runner=subprocess.run,
) -> None:
    """ラベルを冪等に作成 / 更新する。

    ``gh label create --force`` は「無ければ作成、有れば更新」で二重作成しない
    （GitHub CLI のドキュメント通りの挙動）。``runner`` 注入でテスト時に差し替え可能。
    """
    args = [
        GH,
        "label",
        "create",
        spec.name,
        "--color",
        spec.color,
        "--description",
        spec.description,
        "--force",
        *_repo_args(env),
    ]
    runner(args, check=True)


def setup_labels(
    specs: Sequence[LabelSpec] = LABELS,
    *,
    env: Mapping[str, str] | None = None,
    runner=subprocess.run,
    out=sys.stdout,
) -> None:
    """全ラベルを冪等に整備する。``DRY_RUN`` 時は作成せず一覧を ``out`` に出す。"""
    resolved = os.environ if env is None else env
    dry = is_dry_run(resolved)
    mode = "DRY_RUN（作成 / 更新は行いません）" if dry else "ラベルを作成 / 更新します"
    print(f"[setup_labels] {mode} — 対象 {len(specs)} 件", file=out)
    for spec in specs:
        print(f"  - {spec.name}  (#{spec.color})  {spec.description}", file=out)
        if not dry:
            ensure_label(spec, env=resolved, runner=runner)
    if not dry:
        print("[setup_labels] 完了", file=out)


def main() -> int:
    setup_labels()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
