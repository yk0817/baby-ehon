"""privacy.py のテスト（TDD: 実装より先に書く）。

設計: docs/automation/agent-pipeline.md §8.2 / §8.6
- hard-banned regex（メール / 電話 / 住所）
- configurable denylist（env BABY_EHON_NAME_DENYLIST、値はコード/ログに残さない）
- __NAME__ positive assert（talks の呼びかけが __NAME__ でなければエラー）
- 違反メッセージに denylist の実値を漏らさない（§8.6: 本文に値を出さない）
"""

from common import privacy


class TestLoadDenylist:
    def test_parses_comma_separated_stripped_sorted_deduped(self):
        env = {"BABY_EHON_NAME_DENYLIST": "ろく, さぶ ,さぶ,  "}
        assert privacy.load_denylist(env) == ("さぶ", "ろく")

    def test_empty_when_unset(self):
        assert privacy.load_denylist({}) == ()


class TestScanText:
    def test_detects_email(self):
        violations = privacy.scan_text("連絡は foo@example.com まで")
        assert any(v.kind == "email" for v in violations)

    def test_detects_jp_mobile_number(self):
        violations = privacy.scan_text("電話は 090-1234-5678 です")
        assert any(v.kind == "phone" for v in violations)

    def test_detects_address_with_chome(self):
        violations = privacy.scan_text("渋谷区道玄坂2丁目のあたり")
        assert any(v.kind == "address" for v in violations)

    def test_detects_denylist_name_case_insensitive(self):
        violations = privacy.scan_text("Yamada san", denylist=("yamada",))
        assert any(v.kind == "denylist" for v in violations)

    def test_clean_text_has_no_violation(self):
        assert privacy.scan_text("でんしゃ が はしる", denylist=("ろく",)) == []

    def test_violation_message_does_not_leak_denylist_value(self):
        violations = privacy.scan_text("ろく が あそぶ", denylist=("ろく",))
        assert violations
        assert all("ろく" not in v.message for v in violations)

    # --- 部分文字列の過検出を弾く（名前は LLM 非公開なので偶然一致が大半） ----

    def test_substring_inside_longer_hiragana_word_is_not_flagged(self):
        # 「やま」は「やまみち」(山道) の部分文字列だが名前ではない
        violations = privacy.scan_text("やまみち を あるく", denylist=("やま",))
        assert all(v.kind != "denylist" for v in violations)

    def test_common_word_substring_is_not_flagged(self):
        # 「はな」は「はなび」(花火) の部分文字列
        violations = privacy.scan_text("はなび が きれい", denylist=("はな",))
        assert all(v.kind != "denylist" for v in violations)

    def test_name_with_honorific_is_flagged(self):
        violations = privacy.scan_text("はなちゃん おはよう", denylist=("はな",))
        assert any(v.kind == "denylist" for v in violations)

    def test_name_followed_by_punctuation_is_flagged(self):
        violations = privacy.scan_text("やあ たろう、げんき？", denylist=("たろう",))
        assert any(v.kind == "denylist" for v in violations)

    def test_name_at_string_end_is_flagged(self):
        violations = privacy.scan_text("よんで たろう", denylist=("たろう",))
        assert any(v.kind == "denylist" for v in violations)


class TestAssertNamePlaceholder:
    def test_ok_when_vocative_uses_placeholder(self):
        src = "export const config = { talks: ['__NAME__、\\nしゅっぱつ だよ！'] };"
        assert privacy.assert_name_placeholder(src) == []

    def test_flags_hardcoded_vocative(self):
        src = "export const config = { talks: ['ろく、\\nおはよう'] };"
        violations = privacy.assert_name_placeholder(src)
        assert any(v.kind == "name_placeholder" for v in violations)

    def test_ignores_non_vocative_comma(self):
        # 主語＋読点（呼びかけ改行ではない）は誤検知しない
        src = "export const config = { talks: ['でんしゃ、はしるよ！'] };"
        assert privacy.assert_name_placeholder(src) == []

    def test_flag_message_does_not_leak_name(self):
        src = "export const config = { talks: ['ろく、\\nおはよう'] };"
        violations = privacy.assert_name_placeholder(src)
        assert violations
        assert all("ろく" not in v.message for v in violations)


class TestCheck:
    def test_returns_violations_for_text_and_loads_denylist_from_env(self):
        env = {"BABY_EHON_NAME_DENYLIST": "ろく"}
        violations = privacy.check("ろく の でんわ", env=env)
        assert any(v.kind == "denylist" for v in violations)

    def test_clean_text_passes(self):
        assert privacy.check("でんしゃ が はしる", env={}) == []
