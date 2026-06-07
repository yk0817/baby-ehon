"""prompts_loader.py のテスト（TDD: 実装より先に書く）。

設計: docs/automation/agent-pipeline.md §3.2 / §8.1
- 各役の system / persona / rubric 文言を prompts/<role>/ の Markdown に外部化
- 環境変数 PROMPT_DIR（既定 "prompts"）でルートを切替（A/B 用）
- §8.1 の共通プライバシー system プロンプト（prompts/common/privacy_system.md）を
  全役の system 先頭に必ず連結する（省略不可）
- system.md は必須、persona.md / rubric.md は任意（無ければ空文字）
- 未知役割は ValueError
"""

import pytest

from common import prompts_loader

PRIVACY_TEXT = "これはプライバシー方針です。"


def _build_tree(root, *, role="daily", system="SYS", persona="PER", rubric="RUB"):
    """tmp_path 直下に prompts ツリーを組む（AAA の Arrange ヘルパ）。"""
    common = root / "common"
    common.mkdir(parents=True, exist_ok=True)
    (common / "privacy_system.md").write_text(PRIVACY_TEXT, encoding="utf-8")

    role_dir = root / role
    role_dir.mkdir(parents=True, exist_ok=True)
    if system is not None:
        (role_dir / "system.md").write_text(system, encoding="utf-8")
    if persona is not None:
        (role_dir / "persona.md").write_text(persona, encoding="utf-8")
    if rubric is not None:
        (role_dir / "rubric.md").write_text(rubric, encoding="utf-8")
    return root


class TestLoadRolePrompts:
    def test_reads_system_persona_rubric(self, tmp_path):
        # Arrange
        root = _build_tree(tmp_path, role="daily")

        # Act
        prompts = prompts_loader.load_role_prompts("daily", prompt_dir=str(root))

        # Assert
        assert prompts.persona == "PER"
        assert prompts.rubric == "RUB"
        assert "SYS" in prompts.system

    def test_privacy_system_is_prepended_to_system(self, tmp_path):
        # Arrange
        root = _build_tree(tmp_path, role="creator", system="ROLE_SYS")

        # Act
        prompts = prompts_loader.load_role_prompts("creator", prompt_dir=str(root))

        # Assert
        assert prompts.system.startswith(PRIVACY_TEXT)
        assert prompts.system.index(PRIVACY_TEXT) < prompts.system.index("ROLE_SYS")

    def test_persona_and_rubric_optional(self, tmp_path):
        # Arrange: persona / rubric を置かない
        root = _build_tree(tmp_path, role="child", persona=None, rubric=None)

        # Act
        prompts = prompts_loader.load_role_prompts("child", prompt_dir=str(root))

        # Assert
        assert prompts.persona == ""
        assert prompts.rubric == ""
        assert PRIVACY_TEXT in prompts.system

    def test_prompt_dir_switches_directory(self, tmp_path):
        # Arrange: 2 つの別ルートで system 文言を変える（A/B 切替の確認）
        root_a = _build_tree(tmp_path / "a", role="proposer", system="VARIANT_A")
        root_b = _build_tree(tmp_path / "b", role="proposer", system="VARIANT_B")

        # Act
        a = prompts_loader.load_role_prompts("proposer", prompt_dir=str(root_a))
        b = prompts_loader.load_role_prompts("proposer", prompt_dir=str(root_b))

        # Assert
        assert "VARIANT_A" in a.system
        assert "VARIANT_B" in b.system

    def test_prompt_dir_from_env(self, tmp_path):
        # Arrange
        root = _build_tree(tmp_path, role="daily", system="ENV_SYS")
        env = {"PROMPT_DIR": str(root)}

        # Act
        prompts = prompts_loader.load_role_prompts("daily", env=env)

        # Assert
        assert "ENV_SYS" in prompts.system

    def test_missing_privacy_system_raises(self, tmp_path):
        # Arrange: privacy_system.md を消す
        root = _build_tree(tmp_path, role="daily")
        (root / "common" / "privacy_system.md").unlink()

        # Act / Assert
        with pytest.raises(FileNotFoundError):
            prompts_loader.load_role_prompts("daily", prompt_dir=str(root))

    def test_missing_system_raises(self, tmp_path):
        # Arrange: system.md を置かない
        root = _build_tree(tmp_path, role="daily", system=None)

        # Act / Assert
        with pytest.raises(FileNotFoundError):
            prompts_loader.load_role_prompts("daily", prompt_dir=str(root))

    def test_unknown_role_raises_value_error(self, tmp_path):
        # Arrange
        root = _build_tree(tmp_path, role="daily")

        # Act / Assert
        with pytest.raises(ValueError):
            prompts_loader.load_role_prompts("unknown", prompt_dir=str(root))


class TestRoles:
    def test_roles_constant_has_four_roles(self):
        assert set(prompts_loader.ROLES) == {"daily", "proposer", "creator", "child"}
