"""daily_investigator のノード / 整形 / dedupe / プライバシーのテスト（TDD）。

nodes.py は langgraph を import せず、純関数で state dict を受け取り更新を返す形。
ネットワーク・langgraph・実 LLM には依存しない（llm.chat はフェイク注入で回避）。

設計: docs/automation/agent-pipeline.md §4.1 / §4.2 / §4.3 / §4.4 / §2.1
"""

from datetime import datetime, timedelta, timezone

from daily_investigator import nodes

JST = timezone(timedelta(hours=9))


def _fake_chat(reply: str):
    """common.llm.chat 互換のフェイク。常に reply を返す。"""

    def _chat(client, **kwargs):  # noqa: ANN001, ANN003
        return reply

    return _chat


# --- format_comment（純 Python） ---------------------------------------------


class TestFormatComment:
    def test_leading_two_markers_with_jst_date(self):
        # Arrange
        state = {
            "issue_number": 3,
            "issue_title": "タップで音が鳴る",
            "score": 87,
            "score_rationale": "発達価値が高い",
            "research_notes": "共同注意の研究",
            "difficulty": {
                "level": "中",
                "html_css_js_feasible": True,
                "notes": "shared/ehon.js を拡張",
            },
            "feature_proposal": "talks に問いかけを追加",
        }
        today = datetime(2026, 5, 25, 12, 0, tzinfo=JST)

        # Act
        result = nodes.format_comment(state, now=today)
        body = result["rendered_comment"]
        lines = body.splitlines()

        # Assert
        assert lines[0] == "<!-- claude-score: 87 -->"
        assert lines[1] == "<!-- claude-run: 2026-05-25 -->"

    def test_includes_score_and_rubric_breakdown_headings(self):
        # Arrange
        state = {
            "issue_number": 3,
            "issue_title": "T",
            "score": 72,
            "score_rationale": "理由",
            "research_notes": "根拠",
            "difficulty": {"level": "低", "html_css_js_feasible": True, "notes": "n"},
            "feature_proposal": "案",
            "score_breakdown": {
                "developmental": 30,
                "feasibility": 20,
                "reusability": 15,
                "accessibility": 7,
            },
        }

        # Act
        body = nodes.format_comment(state, now=datetime(2026, 1, 1, tzinfo=JST))[
            "rendered_comment"
        ]

        # Assert
        assert "72" in body
        assert "研究根拠" in body
        assert "実装難易度" in body
        assert "優先度スコア" in body
        assert "追加提案" in body
        assert "発達価値" in body

    def test_uses_jst_even_when_now_is_utc_late(self):
        # Arrange: UTC で 2026-05-25 16:00 は JST だと 2026-05-26 01:00（翌日）
        state = {
            "issue_number": 1,
            "issue_title": "T",
            "score": 50,
            "score_rationale": "r",
            "research_notes": "n",
            "difficulty": {"level": "中", "html_css_js_feasible": True, "notes": "x"},
            "feature_proposal": "p",
        }
        utc_now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)

        # Act
        body = nodes.format_comment(state, now=utc_now)["rendered_comment"]

        # Assert
        assert "<!-- claude-run: 2026-05-26 -->" in body


# --- dedupe_gate -------------------------------------------------------------


class TestDedupeGate:
    def test_skips_when_today_marker_present(self):
        # Arrange
        today = datetime(2026, 5, 25, 9, 0, tzinfo=JST)
        state = {
            "existing_comments_today": True,
        }

        # Act
        result = nodes.dedupe_gate(state, now=today, force=False)

        # Assert
        assert result["skip"] is True

    def test_proceeds_when_no_today_marker(self):
        # Arrange
        state = {"existing_comments_today": False}

        # Act
        result = nodes.dedupe_gate(
            state, now=datetime(2026, 5, 25, tzinfo=JST), force=False
        )

        # Assert
        assert result["skip"] is False

    def test_force_overrides_existing_marker(self):
        # Arrange
        state = {"existing_comments_today": True}

        # Act
        result = nodes.dedupe_gate(
            state, now=datetime(2026, 5, 25, tzinfo=JST), force=True
        )

        # Assert
        assert result["skip"] is False


class TestHasTodayMarker:
    def test_detects_today_run_marker_jst(self):
        # Arrange
        bodies = [
            "<!-- claude-run: 2026-05-24 -->\n古い",
            "<!-- claude-score: 80 -->\n<!-- claude-run: 2026-05-25 -->\n本日",
        ]
        now = datetime(2026, 5, 25, 9, 0, tzinfo=JST)

        # Act / Assert
        assert nodes.has_today_marker(bodies, now=now) is True

    def test_false_when_only_other_days(self):
        # Arrange
        bodies = ["<!-- claude-run: 2026-05-24 -->"]
        now = datetime(2026, 5, 25, tzinfo=JST)

        # Act / Assert
        assert nodes.has_today_marker(bodies, now=now) is False


# --- privacy_check -----------------------------------------------------------


class TestPrivacyCheck:
    def test_aborts_and_records_error_on_denylist_hit(self):
        # Arrange: rendered_comment に denylist 名が混入
        state = {
            "rendered_comment": "ひみつのなまえ が混入したコメント",
            "errors": [],
        }
        denylist = ("ひみつのなまえ",)

        # Act
        result = nodes.privacy_check(state, denylist=denylist)

        # Assert
        assert result["abort"] is True
        assert len(result["errors"]) >= 1

    def test_error_message_does_not_leak_actual_value(self):
        # Arrange
        secret = "ひみつのなまえ"
        state = {"rendered_comment": f"{secret} が混入", "errors": []}

        # Act
        result = nodes.privacy_check(state, denylist=(secret,))

        # Assert: 実値はエラーメッセージに含めない（§8.6）
        assert all(secret not in msg for msg in result["errors"])

    def test_passes_clean_comment(self):
        # Arrange
        state = {"rendered_comment": "クリーンなコメント", "errors": []}

        # Act
        result = nodes.privacy_check(state, denylist=("ひみつ",))

        # Assert
        assert result["abort"] is False
        assert result["errors"] == []


# --- score_priority のクランプ -----------------------------------------------


class TestScorePriorityClamp:
    def test_clamps_above_100(self):
        # Arrange
        chat = _fake_chat("スコア: 150\n理由: 高すぎ")
        state = {"issue_title": "T", "issue_body": "B", "research_notes": "n"}

        # Act
        result = nodes.score_priority(state, chat=chat, client=None, env={})

        # Assert
        assert result["score"] == 100

    def test_clamps_below_0(self):
        # Arrange
        chat = _fake_chat("スコア: -20")
        state = {"issue_title": "T", "issue_body": "B", "research_notes": "n"}

        # Act
        result = nodes.score_priority(state, chat=chat, client=None, env={})

        # Assert
        assert result["score"] == 0

    def test_parses_in_range(self):
        # Arrange
        chat = _fake_chat("総合スコア: 73 / 100\n発達価値: 30/40")
        state = {"issue_title": "T", "issue_body": "B", "research_notes": "n"}

        # Act
        result = nodes.score_priority(state, chat=chat, client=None, env={})

        # Assert
        assert result["score"] == 73
        assert result["score_rationale"]

    def test_defaults_to_zero_when_unparseable(self):
        # Arrange
        chat = _fake_chat("数値がありません")
        state = {"issue_title": "T", "issue_body": "B", "research_notes": "n"}

        # Act
        result = nodes.score_priority(state, chat=chat, client=None, env={})

        # Assert
        assert result["score"] == 0


# --- LLM ノード（フェイク注入で純関数として検証） ----------------------------


class TestLLMNodes:
    def test_research_notes_sets_field(self):
        # Arrange
        chat = _fake_chat("先行研究: 共同注意")
        state = {"issue_title": "T", "issue_body": "B"}

        # Act
        result = nodes.research_notes(state, chat=chat, client=None, env={})

        # Assert
        assert result["research_notes"] == "先行研究: 共同注意"

    def test_difficulty_estimate_returns_dict(self):
        # Arrange
        chat = _fake_chat("難易度: 中\nHTML/CSS/JS で完結可能\n影響: shared/ehon.js")
        state = {"issue_title": "T", "issue_body": "B"}

        # Act
        result = nodes.difficulty_estimate(state, chat=chat, client=None, env={})

        # Assert
        assert isinstance(result["difficulty"], dict)
        assert "level" in result["difficulty"]
        assert "notes" in result["difficulty"]

    def test_feature_proposal_sets_field(self):
        # Arrange
        chat = _fake_chat("追加案: talks に問いかけ")
        state = {"issue_title": "T", "issue_body": "B", "research_notes": "n"}

        # Act
        result = nodes.feature_proposal(state, chat=chat, client=None, env={})

        # Assert
        assert result["feature_proposal"] == "追加案: talks に問いかけ"


class TestDifficultyLevels:
    def test_detects_high(self):
        chat = _fake_chat("難易度は 高 です。新規ロジックが多い")
        result = nodes.difficulty_estimate(
            {"issue_title": "T", "issue_body": "B"}, chat=chat, client=None, env={}
        )
        assert result["difficulty"]["level"] == "高"

    def test_detects_low(self):
        chat = _fake_chat("low difficulty, simple")
        result = nodes.difficulty_estimate(
            {"issue_title": "T", "issue_body": "B"}, chat=chat, client=None, env={}
        )
        assert result["difficulty"]["level"] == "低"

    def test_infeasible_marks_false(self):
        chat = _fake_chat("中。ただしビルドツールが必要で HTML/CSS/JS では実装できない")
        result = nodes.difficulty_estimate(
            {"issue_title": "T", "issue_body": "B"}, chat=chat, client=None, env={}
        )
        assert result["difficulty"]["html_css_js_feasible"] is False


# --- load_issue --------------------------------------------------------------


class _FakeLabel:
    def __init__(self, name):
        self.name = name


class _FakeIssue:
    def __init__(self, number, title, body, labels):
        self.number = number
        self.title = title
        self.body = body
        self.labels = labels


class TestLoadIssue:
    def test_extracts_label_names_and_today_flag(self):
        # Arrange
        issue = _FakeIssue(
            7, "タイトル", "本文", [_FakeLabel("approved"), _FakeLabel("automation")]
        )
        bodies = ["<!-- claude-run: 2026-05-25 -->"]
        now = datetime(2026, 5, 25, 9, tzinfo=JST)

        # Act
        result = nodes.load_issue({}, issue=issue, comment_bodies=bodies, now=now)

        # Assert
        assert result["issue_number"] == 7
        assert result["labels"] == ["approved", "automation"]
        assert result["existing_comments_today"] is True


# --- post_comment ------------------------------------------------------------


class _FakeIO:
    def __init__(self):
        self.commented = None
        self.labeled = None

    def create_issue_comment(self, number, body):
        self.commented = (number, body)

        class _C:
            html_url = "https://example.test/c/1"

        return _C()

    def add_labels(self, number, *labels):
        self.labeled = (number, labels)


class TestPostComment:
    def test_dry_run_does_not_write(self):
        # Arrange
        io = _FakeIO()
        state = {"issue_number": 3, "rendered_comment": "body"}

        # Act
        result = nodes.post_comment(state, io=io, dry_run=True)

        # Assert
        assert result["posted_comment_url"] is None
        assert io.commented is None
        assert io.labeled is None

    def test_posts_and_adds_stage_label(self):
        # Arrange
        io = _FakeIO()
        state = {"issue_number": 3, "rendered_comment": "body"}

        # Act
        result = nodes.post_comment(state, io=io, dry_run=False)

        # Assert
        assert io.commented == (3, "body")
        assert io.labeled == (3, (nodes.STAGE_LABEL,))
        assert result["posted_comment_url"] == "https://example.test/c/1"


# --- prompts ローダ委譲 ------------------------------------------------------


class TestPromptsModule:
    def test_load_role_prompts_delegates_to_common(self):
        # Arrange / Act
        from daily_investigator import prompts

        loaded = prompts.load()

        # Assert: daily 役の system が読めている
        assert loaded.role == "daily"
        assert loaded.system


# --- run.process_issue が LLM クライアントを各ノードへ転送する（回帰） ---------


class TestProcessIssueForwardsClient:
    """dry-run + API キー有りで client=None 固定だと None.chat になる回帰の防止。"""

    def test_forwards_client_to_llm_nodes(self):
        # Arrange
        from daily_investigator import prompts, run

        captured: dict = {}

        def spy_chat(client, **kwargs):
            captured["client"] = client
            return "ok"

        sentinel = object()
        config = run.RunConfig(
            dry_run=True,
            force=False,
            only_issue=1,
            has_api_key=True,
            repo=None,
            denylist=(),
        )

        # Act
        run.process_issue(
            run._StubIssue(number=1),
            config=config,
            io=None,
            chat=spy_chat,
            client=sentinel,
            role_prompts=prompts.load(),
            env={},
        )

        # Assert: ノードに渡ったのは None ではなく与えた client
        assert captured["client"] is sentinel
