"""Daily Investigator のプロンプト取得ローダ（文言は持たない）。

役の振る舞い（口調・評価観点・制約）は ``prompts/daily/`` の Markdown に外部化済み。
このモジュールは ``common.prompts_loader.load_role_prompts("daily")`` への薄い委譲に
徹し、文言自体はハードコードしない（設計 §3.2 の DoD）。

設計: docs/automation/agent-pipeline.md §3.2 / §8.1
"""

from __future__ import annotations

from collections.abc import Mapping

from common.prompts_loader import RolePrompts, load_role_prompts

ROLE = "daily"


def load(
    *,
    prompt_dir: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RolePrompts:
    """daily 役の system / persona / rubric を読み込む（§3.2）。"""
    return load_role_prompts(ROLE, prompt_dir=prompt_dir, env=env)
