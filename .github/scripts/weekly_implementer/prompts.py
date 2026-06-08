"""Weekly Implementer のプロンプト取得（文言は持たず common.prompts_loader に委譲）。

役の振る舞い文言（system / persona / rubric）は ``prompts/creator/`` の Markdown に
外部化されている。このモジュールは文言を一切ハードコードせず、ローダを ``role="creator"``
で呼ぶだけの薄い窓口にする（設計 §3.2 の DoD）。creator は system.md / persona.md
のみで rubric は任意。

設計: docs/automation/agent-pipeline.md §3.2 / §6
"""

from __future__ import annotations

from collections.abc import Mapping

from common.prompts_loader import RolePrompts, load_role_prompts

ROLE = "creator"


def load(
    *,
    prompt_dir: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RolePrompts:
    """Creator 役の system / persona / rubric を読み込む。"""
    return load_role_prompts(ROLE, prompt_dir=prompt_dir, env=env)
