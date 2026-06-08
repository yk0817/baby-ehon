"""github_io.py のテスト（TDD）。

PyGithub の薄いラッパ。テストでは fake クライアントを注入し、委譲を確認する。
実際の GitHub API・PyGithub には依存しない。
設計: docs/automation/agent-pipeline.md §3.1 / §6
"""

from common import github_io


class _FakeIssue:
    def __init__(self):
        self.added = None
        self.removed = None
        self.created_body = None
        self.comments = ["c1", "c2"]

    def add_to_labels(self, *labels):
        self.added = labels

    def remove_from_labels(self, label):
        self.removed = label

    def create_comment(self, body):
        self.created_body = body
        return "comment-obj"

    def get_comments(self):
        return self.comments


class _FakeRepo:
    def __init__(self):
        self.issue = _FakeIssue()
        self.requested_issue = None
        self.created_pull = None
        self.created_issue = None

    def get_issue(self, number):
        self.requested_issue = number
        return self.issue

    def create_pull(self, **kwargs):
        self.created_pull = kwargs
        return "pull-obj"

    def create_issue(self, **kwargs):
        self.created_issue = kwargs
        return "issue-obj"


class _FakeClient:
    def __init__(self):
        self.repo = _FakeRepo()
        self.requested_repo = None

    def get_repo(self, full_name):
        self.requested_repo = full_name
        return self.repo


def _make_io():
    client = _FakeClient()
    io = github_io.GitHubIO(repo="owner/baby-ehon", client=client)
    return io, client


class TestGitHubIO:
    def test_get_issue_delegates(self):
        io, client = _make_io()
        io.get_issue(14)
        assert client.requested_repo == "owner/baby-ehon"
        assert client.repo.requested_issue == 14

    def test_list_issue_comments_delegates(self):
        io, client = _make_io()
        assert io.list_issue_comments(14) == ["c1", "c2"]

    def test_create_issue_comment_delegates(self):
        io, client = _make_io()
        io.create_issue_comment(14, "hello")
        assert client.repo.issue.created_body == "hello"

    def test_add_labels_delegates(self):
        io, client = _make_io()
        io.add_labels(14, "approved", "automation")
        assert client.repo.issue.added == ("approved", "automation")

    def test_remove_label_delegates(self):
        io, client = _make_io()
        io.remove_label(14, "stale")
        assert client.repo.issue.removed == "stale"

    def test_create_pull_delegates(self):
        io, client = _make_io()
        io.create_pull(title="t", body="b", head="claude/issue-14", base="main")
        assert client.repo.created_pull == {
            "title": "t",
            "body": "b",
            "head": "claude/issue-14",
            "base": "main",
        }

    def test_create_issue_delegates(self):
        io, client = _make_io()
        io.create_issue(title="t", body="b", labels=["claude-proposed"])
        assert client.repo.created_issue == {
            "title": "t",
            "body": "b",
            "labels": ["claude-proposed"],
        }
