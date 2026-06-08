"""auto_close.py のテスト（TDD: 実装より先に書く）。

設計: docs/automation/agent-pipeline.md §2.1 / §2.2
- 3 ステージラベル（researched / implemented / child-reviewed）が揃ったら True
- 2 つだけでは False
- automation:skip があれば False（自動クローズ対象外）
- approved はクローズ条件に含めない（§2.2: 入口ゲートであり、各役の処理完了の記録ではない）
- 順不同・重複ラベルでも正しく判定する
"""

from common import auto_close


class TestShouldClose:
    def test_true_when_all_three_stage_labels_present(self):
        # Arrange
        labels = [
            "stage:researched",
            "stage:implemented",
            "stage:child-reviewed",
        ]

        # Act
        result = auto_close.should_close(labels)

        # Assert
        assert result is True

    def test_false_when_only_two_stage_labels(self):
        # Arrange
        labels = ["stage:researched", "stage:implemented"]

        # Act
        result = auto_close.should_close(labels)

        # Assert
        assert result is False

    def test_false_when_no_labels(self):
        # Arrange / Act / Assert
        assert auto_close.should_close([]) is False

    def test_false_when_all_three_but_automation_skip_present(self):
        # Arrange
        labels = [
            "stage:researched",
            "stage:implemented",
            "stage:child-reviewed",
            "automation:skip",
        ]

        # Act
        result = auto_close.should_close(labels)

        # Assert
        assert result is False

    def test_approved_does_not_affect_judgement(self):
        # approved は入口ゲート。クローズ判定には影響しない（§2.2）。
        # Arrange
        only_two_with_approved = [
            "stage:researched",
            "stage:implemented",
            "approved",
        ]
        all_three_with_approved = [
            "stage:researched",
            "stage:implemented",
            "stage:child-reviewed",
            "approved",
        ]

        # Act / Assert
        assert auto_close.should_close(only_two_with_approved) is False
        assert auto_close.should_close(all_three_with_approved) is True

    def test_true_when_labels_unordered_and_duplicated(self):
        # Arrange: 順不同 + 重複 + 無関係ラベル混在
        labels = [
            "automation",
            "stage:child-reviewed",
            "stage:researched",
            "stage:researched",
            "stage:implemented",
            "claude-proposed",
        ]

        # Act
        result = auto_close.should_close(labels)

        # Assert
        assert result is True

    def test_accepts_arbitrary_iterable(self):
        # Arrange: list 以外の Iterable（generator）でも動く
        labels = (
            label
            for label in (
                "stage:researched",
                "stage:implemented",
                "stage:child-reviewed",
            )
        )

        # Act
        result = auto_close.should_close(labels)

        # Assert
        assert result is True


class TestConstants:
    def test_stage_labels_are_the_three_role_stages(self):
        assert auto_close.STAGE_LABELS == (
            "stage:researched",
            "stage:implemented",
            "stage:child-reviewed",
        )

    def test_skip_label_value(self):
        assert auto_close.SKIP_LABEL == "automation:skip"

    def test_close_marker_is_machine_readable_html_comment(self):
        # 機械可読マーカー（HTML コメント）で冪等判定に使える形であること
        marker = auto_close.CLOSE_MARKER
        assert marker.startswith("<!--")
        assert marker.endswith("-->")
        assert "auto-closed" in marker
