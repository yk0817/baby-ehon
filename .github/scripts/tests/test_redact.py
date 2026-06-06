"""redact() のテスト（TDD）。

ログ出力前に機密（メール/電話/住所/denylist 名）をマスクする。
設計: docs/automation/agent-pipeline.md §8.3
"""

from common import privacy


def test_redact_masks_email():
    out = privacy.redact("連絡 foo@example.com まで")
    assert "foo@example.com" not in out
    assert "***" in out


def test_redact_masks_phone():
    out = privacy.redact("電話 090-1234-5678")
    assert "090-1234-5678" not in out


def test_redact_masks_denylist_name_case_insensitive():
    out = privacy.redact("Yamada san", denylist=("yamada",))
    assert "Yamada" not in out
    assert "yamada" not in out.lower()


def test_redact_keeps_clean_text_unchanged():
    assert privacy.redact("でんしゃ が はしる") == "でんしゃ が はしる"
