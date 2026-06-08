"""weekly_implementer の純粋ノードのテスト（TDD・AAA）。

select_top（最重要）/ collect_scores / privacy_check / PR 本文テンプレ / ブランチ名 を
fake LLM・fake IO 注入で検証する。ネットワーク・実 LLM・langgraph には依存しない。

設計: docs/automation/agent-pipeline.md §6.1 / §6.2 / §6.4 / §2.2 / §8
"""

from weekly_implementer import nodes

# --- collect_scores（§6.1 / §4.3） -------------------------------------------


class TestCollectScores:
    def test_extracts_latest_claude_score_per_issue(self):
        # Arrange: 2 件のうち #1 はコメントに最新スコアあり、#2 はマーカー無し
        state = {
            "candidate_issues": [
                {"number": 1, "title": "A", "body": "", "labels": ["approved"]},
                {"number": 2, "title": "B", "body": "", "labels": ["approved"]},
            ]
        }
        comments = {
            1: [
                ("<!-- claude-score: 50 -->", "2026-05-01"),
                ("<!-- claude-score: 80 -->", "2026-05-10"),  # こちらが最新
            ],
            2: [("採点なしのコメント", "2026-05-01")],
        }

        # Act
        result = nodes.collect_scores(state, comments_by_issue=comments)

        # Assert
        by_num = {i["number"]: i for i in result["candidate_issues"]}
        assert by_num[1]["score"] == 80
        assert by_num[2]["score"] is None

    def test_missing_issue_in_comments_map_is_none(self):
        # Arrange
        state = {
            "candidate_issues": [
                {"number": 7, "title": "X", "body": "", "labels": []},
            ]
        }

        # Act
        result = nodes.collect_scores(state, comments_by_issue={})

        # Assert
        assert result["candidate_issues"][0]["score"] is None


# --- select_top（最重要・§2.2 / §6.1） --------------------------------------


class TestSelectTop:
    def test_requires_approved_label(self):
        # Arrange: 高スコアでも approved 無しは候補にならない
        state = {
            "candidate_issues": [
                {
                    "number": 1,
                    "title": "no-approve",
                    "body": "",
                    "labels": [],
                    "score": 99,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert: 選定なし（何もせず終了）
        assert result["selected_issue"] == {}
        assert any("approved" in e for e in result["errors"])

    def test_picks_highest_score_among_approved(self):
        # Arrange
        state = {
            "candidate_issues": [
                {
                    "number": 1,
                    "title": "low",
                    "body": "",
                    "labels": ["approved"],
                    "score": 60,
                },
                {
                    "number": 2,
                    "title": "high",
                    "body": "",
                    "labels": ["approved"],
                    "score": 90,
                },
                {
                    "number": 3,
                    "title": "mid",
                    "body": "",
                    "labels": ["approved"],
                    "score": 75,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert
        assert result["selected_issue"]["number"] == 2
        assert result["selected_issue"]["score"] == 90

    def test_excludes_skip_and_wip_labels(self):
        # Arrange: 最高スコアは skip / wip 付きなので除外され、次点が選ばれる
        state = {
            "candidate_issues": [
                {
                    "number": 1,
                    "title": "skip",
                    "body": "",
                    "labels": ["approved", "automation:skip"],
                    "score": 100,
                },
                {
                    "number": 2,
                    "title": "wip",
                    "body": "",
                    "labels": ["approved", "wip"],
                    "score": 95,
                },
                {
                    "number": 3,
                    "title": "ok",
                    "body": "",
                    "labels": ["approved"],
                    "score": 70,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert
        assert result["selected_issue"]["number"] == 3

    def test_ties_break_by_lower_issue_number(self):
        # Arrange: 同点 88 の #5 と #3 → 番号が小さい #3 を選ぶ
        state = {
            "candidate_issues": [
                {
                    "number": 5,
                    "title": "five",
                    "body": "",
                    "labels": ["approved"],
                    "score": 88,
                },
                {
                    "number": 3,
                    "title": "three",
                    "body": "",
                    "labels": ["approved"],
                    "score": 88,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert
        assert result["selected_issue"]["number"] == 3

    def test_no_approved_candidate_returns_empty(self):
        # Arrange: approved はあるが採点されていない → 候補ゼロ
        state = {
            "candidate_issues": [
                {
                    "number": 1,
                    "title": "unscored",
                    "body": "",
                    "labels": ["approved"],
                    "score": None,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert
        assert result["selected_issue"] == {}
        assert nodes.route_selected(result) == "skip"

    def test_route_selected_continue_when_selected(self):
        # Arrange
        state = {
            "candidate_issues": [
                {
                    "number": 2,
                    "title": "ok",
                    "body": "",
                    "labels": ["approved"],
                    "score": 70,
                },
            ]
        }

        # Act
        result = nodes.select_top(state)

        # Assert
        assert nodes.route_selected(result) == "continue"


# --- list_open_issues（ラベル抽出の互換性） ----------------------------------


class TestListOpenIssues:
    def test_normalizes_pygithub_like_objects(self):
        # Arrange: PyGithub 風オブジェクト（labels は .name を持つ）
        class FakeLabel:
            def __init__(self, name):
                self.name = name

        class FakeIssue:
            def __init__(self, number, title, body, labels):
                self.number = number
                self.title = title
                self.body = body
                self.labels = [FakeLabel(n) for n in labels]

        issues = [FakeIssue(1, "T", "B", ["approved", "wip"])]

        # Act
        result = nodes.list_open_issues({}, issues=issues)

        # Assert
        assert result["candidate_issues"][0]["number"] == 1
        assert result["candidate_issues"][0]["labels"] == ["approved", "wip"]


# --- privacy_check（§8） -----------------------------------------------------


class TestPrivacyCheck:
    def test_blocks_on_denylist_name_without_leaking_value(self):
        # Arrange: パッチ内容に denylist 名が含まれる
        secret = "ひみつのなまえ"
        state = {
            "proposed_patches": [
                {
                    "path": "densha/index.html",
                    "new_contents": f"<p>{secret}、おはよう</p>",
                },
            ]
        }

        # Act
        result = nodes.privacy_check(state, denylist=[secret])

        # Assert: ブロックされ、メッセージに実値は出ない
        assert result["privacy_violations"]
        assert nodes.route_privacy(result) == "violation"
        for v in result["privacy_violations"]:
            assert secret not in v

    def test_config_js_requires_name_placeholder(self):
        # Arrange: config.js の呼びかけが __NAME__ でない（実名ハードコード疑い）
        state = {
            "proposed_patches": [
                {
                    "path": "densha/config.js",
                    "new_contents": "var talks = ['たろう、\\nしゅっぱつ'];",
                },
            ]
        }

        # Act
        result = nodes.privacy_check(state, denylist=[])

        # Assert
        assert result["privacy_violations"]
        assert any("name_placeholder" in v for v in result["privacy_violations"])

    def test_clean_patch_passes(self):
        # Arrange: __NAME__ を使った正しい呼びかけ・機密なし
        state = {
            "proposed_patches": [
                {
                    "path": "densha/config.js",
                    "new_contents": "var talks = ['__NAME__、\\nしゅっぱつ'];",
                },
                {"path": "densha/index.html", "new_contents": "<p>でんしゃ はしる</p>"},
            ]
        }

        # Act
        result = nodes.privacy_check(state, denylist=["ひみつ"])

        # Assert
        assert result["privacy_violations"] == []
        assert nodes.route_privacy(result) == "ok"


# --- record_failure_comment（実値非露出・§8） -------------------------------


class TestRecordFailureComment:
    def test_comments_kinds_only_not_values(self):
        # Arrange
        class FakeIO:
            def __init__(self):
                self.posted = []

            def create_issue_comment(self, number, body):
                self.posted.append((number, body))

        io = FakeIO()
        state = {
            "selected_issue": {"number": 42},
            "privacy_violations": ["densha/config.js: [name_placeholder] talks ..."],
        }

        # Act
        result = nodes.record_failure_comment(state, io=io, dry_run=False)

        # Assert: コメントは投稿され、件数・種別のみ。errors に記録。
        assert io.posted
        number, body = io.posted[0]
        assert number == 42
        assert "name_placeholder" in body
        assert any("privacy violation" in e for e in result["errors"])

    def test_dry_run_does_not_post(self):
        # Arrange
        class FakeIO:
            def __init__(self):
                self.posted = []

            def create_issue_comment(self, number, body):
                self.posted.append((number, body))

        io = FakeIO()
        state = {
            "selected_issue": {"number": 1},
            "privacy_violations": ["x: [email] ..."],
        }

        # Act
        nodes.record_failure_comment(state, io=io, dry_run=True)

        # Assert
        assert io.posted == []


# --- PR 本文 / タイトル / ブランチ名（§6.4） --------------------------------


class TestPullRequestText:
    def test_branch_name_pattern(self):
        # Act / Assert
        assert nodes.branch_name_for(19) == "claude/issue-19"

    def test_pr_title_pattern(self):
        # Act
        title = nodes.pr_title_for(19, "おとあそび ボタンの追加")

        # Assert
        assert title == "[draft] おとあそび ボタンの追加 (#19)"

    def test_pr_body_starts_with_closes_and_lists_files(self):
        # Arrange
        patches = [
            {"path": "shared/ehon.js", "new_contents": "..."},
            {"path": "densha/config.js", "new_contents": "..."},
        ]

        # Act
        body = nodes.pr_body_for(19, "音ボタンを足す計画", patches)

        # Assert
        assert body.startswith("Closes #19")
        assert "- shared/ehon.js" in body
        assert "- densha/config.js" in body
        assert "音ボタンを足す計画" in body
        assert "__NAME__" in body  # レビュー観点チェックリスト

    def test_commit_message_conventional_with_refs(self):
        # Act
        message = nodes.commit_message_for(19, "implement issue #19")

        # Assert
        assert message.startswith("feat: implement issue #19 (#19)")
        assert "Refs #19" in message
        assert "@" not in message  # 個人メアドを入れない


# --- generate_patch のパース（§6.1） ----------------------------------------


class TestParsePatchBlocks:
    def test_splits_blocks_and_strips_fence(self):
        # Arrange
        raw = (
            "=== path: shared/ehon.css ===\n"
            "```css\n"
            ".btn { color: red; }\n"
            "```\n"
            "=== path: densha/config.js ===\n"
            "var talks = ['__NAME__、\\nしゅっぱつ'];\n"
        )

        # Act
        patches = nodes.parse_patch_blocks(raw)

        # Assert
        by_path = {p["path"]: p["new_contents"] for p in patches}
        assert by_path["shared/ehon.css"] == ".btn { color: red; }"
        assert "__NAME__" in by_path["densha/config.js"]

    def test_no_header_returns_empty(self):
        # Act
        patches = nodes.parse_patch_blocks("ただの説明文でブロックなし")

        # Assert
        assert patches == []

    def test_generate_patch_records_error_when_no_blocks(self):
        # Arrange
        def fake_llm(_system, _user):
            return "ブロックがありません"

        state = {"selected_issue": {"number": 1}, "context_files": {}, "errors": []}

        # Act
        result = nodes.generate_patch(state, llm=fake_llm)

        # Assert
        assert result["proposed_patches"] == []
        assert any("generate_patch" in e for e in result["errors"])


# --- open_draft_pr の isDraft assert（§6.4） --------------------------------


class TestOpenDraftPr:
    def test_asserts_is_draft_true(self):
        # Arrange: pr_runner が isDraft=False を返したら AssertionError
        def runner(**_kwargs):
            return {"url": "u", "number": 5, "isDraft": False}

        state = {
            "selected_issue": {"number": 19, "title": "T"},
            "branch_name": "claude/issue-19",
        }

        # Act / Assert
        import pytest

        with pytest.raises(AssertionError):
            nodes.open_draft_pr(state, pr_runner=runner, dry_run=False)

    def test_returns_pr_url_when_draft(self):
        # Arrange
        def runner(**kwargs):
            assert kwargs["draft"] is True
            return {"url": "https://example/pr/5", "number": 5, "isDraft": True}

        state = {
            "selected_issue": {"number": 19, "title": "T"},
            "branch_name": "claude/issue-19",
        }

        # Act
        result = nodes.open_draft_pr(state, pr_runner=runner, dry_run=False)

        # Assert
        assert result["pr_url"] == "https://example/pr/5"
        assert result["pr_number"] == 5

    def test_dry_run_skips_creation(self):
        # Arrange
        def runner(**_kwargs):
            raise AssertionError("dry_run では呼ばれてはいけない")

        state = {"selected_issue": {"number": 19, "title": "T"}}

        # Act
        result = nodes.open_draft_pr(state, pr_runner=runner, dry_run=True)

        # Assert
        assert result["pr_url"] is None
        assert result["pr_number"] is None


# --- trigger_child_review（DRY_RUN で実行しない・§6.5） ----------------------


class TestTriggerChildReview:
    def test_runs_workflow_with_pr_number(self):
        # Arrange
        calls = []

        def runner(workflow_file, inputs):
            calls.append((workflow_file, inputs))

        state = {"pr_number": 5}

        # Act
        nodes.trigger_child_review(state, workflow_runner=runner, dry_run=False)

        # Assert
        assert calls == [("child-review.yml", {"pr_number": "5"})]

    def test_dry_run_does_not_trigger(self):
        # Arrange
        def runner(_workflow, _inputs):
            raise AssertionError("dry_run では起動しない")

        state = {"pr_number": 5}

        # Act
        nodes.trigger_child_review(state, workflow_runner=runner, dry_run=True)

        # Assert: 例外が出なければ OK（呼ばれていない）


# --- apply_patches / git_commit_push / label_pr_and_issue（注入 I/O） --------


class TestApplyPatches:
    def test_writes_each_patch(self):
        # Arrange
        written = {}

        def writer(path, contents):
            written[path] = contents

        state = {
            "proposed_patches": [
                {"path": "a.html", "new_contents": "A"},
                {"path": "b.css", "new_contents": "B"},
            ]
        }

        # Act
        nodes.apply_patches(state, writer=writer, dry_run=False)

        # Assert
        assert written == {"a.html": "A", "b.css": "B"}

    def test_dry_run_writes_nothing(self):
        # Arrange
        def writer(_path, _contents):
            raise AssertionError("dry_run では書かない")

        state = {"proposed_patches": [{"path": "a", "new_contents": "x"}]}

        # Act
        nodes.apply_patches(state, writer=writer, dry_run=True)

        # Assert: 例外が出なければ OK


class TestGitCommitPush:
    def test_creates_branch_commits_pushes(self):
        # Arrange
        class FakeGit:
            def __init__(self):
                self.calls = []

            def create_branch(self, name):
                self.calls.append(("branch", name))

            def add_all(self):
                self.calls.append(("add",))

            def commit(self, message):
                self.calls.append(("commit", message))

            def push(self, name):
                self.calls.append(("push", name))

        git = FakeGit()
        state = {"selected_issue": {"number": 19, "title": "T"}}

        # Act
        result = nodes.git_commit_push(state, git=git, dry_run=False)

        # Assert
        assert result["branch_name"] == "claude/issue-19"
        assert ("branch", "claude/issue-19") in git.calls
        assert ("push", "claude/issue-19") in git.calls
        commit_calls = [c for c in git.calls if c[0] == "commit"]
        assert "Refs #19" in commit_calls[0][1]

    def test_dry_run_only_sets_branch_name(self):
        # Arrange
        class FakeGit:
            def create_branch(self, name):
                raise AssertionError("dry_run では呼ばない")

        state = {"selected_issue": {"number": 7}}

        # Act
        result = nodes.git_commit_push(state, git=FakeGit(), dry_run=True)

        # Assert
        assert result["branch_name"] == "claude/issue-7"


class TestLabelPrAndIssue:
    def test_labels_pr_and_issue(self):
        # Arrange
        class FakeIO:
            def __init__(self):
                self.labels = []

            def add_labels(self, number, *labels):
                self.labels.append((number, labels))

        io = FakeIO()
        state = {"selected_issue": {"number": 19}, "pr_number": 5}

        # Act
        nodes.label_pr_and_issue(state, io=io, dry_run=False)

        # Assert
        assert (5, ("needs-child-review",)) in io.labels
        assert (19, ("stage:implemented",)) in io.labels

    def test_dry_run_no_labels(self):
        # Arrange
        class FakeIO:
            def add_labels(self, number, *labels):
                raise AssertionError("dry_run ではラベル付けしない")

        state = {"selected_issue": {"number": 19}, "pr_number": 5}

        # Act
        nodes.label_pr_and_issue(state, io=FakeIO(), dry_run=True)

        # Assert: 例外が出なければ OK


# --- plan_change（LLM 注入・§6.1） ------------------------------------------


class TestPlanChange:
    def test_returns_stripped_plan(self):
        # Arrange
        def fake_llm(system, user):
            assert "Issue #19" in user
            return "\n変更計画本体\n"

        state = {
            "selected_issue": {"number": 19, "title": "T", "body": "本文"},
            "context_files": {"README.md": "..."},
        }

        # Act
        result = nodes.plan_change(state, llm=fake_llm)

        # Assert
        assert result["change_plan"] == "変更計画本体"


# --- gather_context の extra_paths 抽出（§6.3） -----------------------------


class TestGatherContext:
    def test_passes_target_files_as_extra_paths(self):
        # Arrange: Issue 本文が指す絵本ファイルを reader に渡す
        captured = {}

        def fake_reader(repo_root, *, extra_paths):
            captured["extra"] = list(extra_paths)
            return {"README.md": "..."}

        state = {
            "selected_issue": {
                "number": 1,
                "body": "`hikouki/index.html` と `hikouki/theme.css` を変更",
            }
        }

        # Act
        result = nodes.gather_context(state, reader=fake_reader, repo_root="/repo")

        # Assert
        assert "hikouki/index.html" in captured["extra"]
        assert "hikouki/theme.css" in captured["extra"]
        assert result["context_files"] == {"README.md": "..."}
