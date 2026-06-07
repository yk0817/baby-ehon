"""PyGithub の薄いラッパ（issue / comment / PR / label 操作）。

各役は GitHub への読み書きをここ経由で行う。PyGithub を直接触らず 1 段かませる
ことで、(1) テストで fake クライアントを注入でき、(2) 将来 API を差し替えても
呼び出し側を変えずに済む。

設計方針:

- ``from github import Github`` は **メソッド内で遅延 import** する
  （PyGithub 未インストールの環境でも、client を注入すればテストが回るように）。
- コンストラクタに ``client`` を注入できる（未指定なら token から実クライアントを生成）。
- 実装は薄く保ち、ロジックは持たない（委譲のみ）。

設計: docs/automation/agent-pipeline.md §3.1 / §6
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

TOKEN_ENV = "GITHUB_TOKEN"


class GitHubIO:
    """単一リポジトリに対する GitHub 操作の薄いラッパ。"""

    def __init__(
        self,
        repo: str,
        *,
        client: Any | None = None,
        token: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """``repo`` は ``owner/name`` 形式。

        ``client`` を渡せばそれを使う（テスト用 fake 注入）。未指定のときは
        ``token`` / env ``GITHUB_TOKEN`` から PyGithub の ``Github`` を遅延生成する。
        """
        self._repo_name = repo
        if client is None:
            client = self._build_client(token, env)
        self._client = client

    @staticmethod
    def _build_client(token: str | None, env: Mapping[str, str] | None) -> Any:
        """PyGithub クライアントを遅延 import で生成する。"""
        from github import Github  # 遅延 import（未インストール環境を壊さない）

        source = os.environ if env is None else env
        resolved = token if token is not None else source.get(TOKEN_ENV)
        return Github(resolved)

    def _repo(self) -> Any:
        return self._client.get_repo(self._repo_name)

    def get_issue(self, number: int) -> Any:
        """Issue オブジェクトを取得する。"""
        return self._repo().get_issue(number)

    def list_issue_comments(self, number: int) -> Any:
        """Issue の全コメントを取得する。"""
        return self.get_issue(number).get_comments()

    def create_issue_comment(self, number: int, body: str) -> Any:
        """Issue にコメントを投稿する。"""
        return self.get_issue(number).create_comment(body)

    def add_labels(self, number: int, *labels: str) -> None:
        """Issue にラベルを追加する。"""
        self.get_issue(number).add_to_labels(*labels)

    def remove_label(self, number: int, label: str) -> None:
        """Issue からラベルを 1 つ外す。"""
        self.get_issue(number).remove_from_labels(label)

    def create_pull(self, *, title: str, body: str, head: str, base: str) -> Any:
        """Pull Request を作成する。"""
        return self._repo().create_pull(title=title, body=body, head=head, base=base)
