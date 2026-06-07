"""repo_reader.py のテスト（TDD: 実装より先に書く）。

allowlist 制限付きでリポジトリ内容を読み、LLM に晒す範囲を限定する。
設計: docs/automation/agent-pipeline.md §6.3 / §7.7

観点:
- allowlist のものだけ読める
- allowlist 外（secret.txt / .github/ 配下）は読まれない
- `..` トラバーサル・repo_root 外の明示パスは拒否（読まない）
- 合計 150KB 超でハードキャップ切り詰め
"""

from common import repo_reader


def _make_repo(root):
    """擬似リポジトリを tmp_path に構築する。"""
    (root / "shared").mkdir()
    (root / "densha").mkdir()
    (root / "hikouki").mkdir()
    (root / ".github").mkdir()

    (root / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "shared" / "ehon.js").write_text("// engine\n", encoding="utf-8")
    (root / "shared" / "ehon.css").write_text("/* style */\n", encoding="utf-8")
    (root / "densha" / "config.js").write_text(
        "export const config = {};\n", encoding="utf-8"
    )
    (root / "densha" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (root / "hikouki" / "config.js").write_text(
        "export const config = {};\n", encoding="utf-8"
    )

    # allowlist 外（読まれてはいけない）
    (root / "secret.txt").write_text("SECRET\n", encoding="utf-8")
    (root / ".github" / "foo.yml").write_text("on: push\n", encoding="utf-8")


class TestIsAllowed:
    def test_core_files_allowed(self):
        assert repo_reader.is_allowed("CLAUDE.md")
        assert repo_reader.is_allowed("README.md")
        assert repo_reader.is_allowed("shared/ehon.js")
        assert repo_reader.is_allowed("shared/ehon.css")

    def test_config_js_glob_allowed(self):
        assert repo_reader.is_allowed("densha/config.js")
        assert repo_reader.is_allowed("hikouki/config.js")

    def test_disallowed_paths(self):
        assert not repo_reader.is_allowed("secret.txt")
        assert not repo_reader.is_allowed(".github/foo.yml")
        assert not repo_reader.is_allowed("shared/baby.js")


class TestReadAllowlisted:
    def test_reads_only_allowlisted(self, tmp_path):
        # Arrange
        _make_repo(tmp_path)
        # Act
        result = repo_reader.read_allowlisted(tmp_path)
        # Assert: allowlist のものが含まれる
        assert "CLAUDE.md" in result
        assert "README.md" in result
        assert "shared/ehon.js" in result
        assert "shared/ehon.css" in result
        assert "densha/config.js" in result
        assert "hikouki/config.js" in result
        # allowlist 外は含まれない
        assert "secret.txt" not in result
        assert ".github/foo.yml" not in result

    def test_includes_one_representative_index_html(self, tmp_path):
        _make_repo(tmp_path)
        result = repo_reader.read_allowlisted(tmp_path)
        index_keys = [k for k in result if k.endswith("index.html")]
        assert len(index_keys) >= 1

    def test_extra_paths_read_when_allowed(self, tmp_path):
        _make_repo(tmp_path)
        (tmp_path / "hikouki" / "index.html").write_text(
            "<html>2</html>\n", encoding="utf-8"
        )
        (tmp_path / "hikouki" / "theme.css").write_text("/* t */\n", encoding="utf-8")
        result = repo_reader.read_allowlisted(
            tmp_path, extra_paths=["hikouki/index.html", "hikouki/theme.css"]
        )
        assert "hikouki/index.html" in result
        assert "hikouki/theme.css" in result

    def test_extra_path_outside_allowlist_is_rejected(self, tmp_path):
        _make_repo(tmp_path)
        result = repo_reader.read_allowlisted(tmp_path, extra_paths=["secret.txt"])
        assert "secret.txt" not in result

    def test_traversal_extra_path_is_rejected(self, tmp_path):
        # Arrange: repo_root の外に秘密ファイルを置く
        _make_repo(tmp_path)
        outside = tmp_path.parent / "outside_secret.txt"
        outside.write_text("OUTSIDE\n", encoding="utf-8")
        # Act
        result = repo_reader.read_allowlisted(
            tmp_path, extra_paths=["../outside_secret.txt"]
        )
        # Assert: トラバーサルで外を読まない
        assert all("OUTSIDE" not in content for content in result.values())
        assert "../outside_secret.txt" not in result

    def test_hard_caps_total_size(self, tmp_path):
        # Arrange: 大きいファイルで 150KB 超にする
        _make_repo(tmp_path)
        big = "x" * (200 * 1024)
        (tmp_path / "shared" / "ehon.js").write_text(big, encoding="utf-8")
        # Act
        result = repo_reader.read_allowlisted(tmp_path)
        # Assert: 合計が MAX_TOTAL_BYTES を超えない
        total = sum(len(c.encode("utf-8")) for c in result.values())
        assert total <= repo_reader.MAX_TOTAL_BYTES

    def test_missing_optional_files_are_skipped(self, tmp_path):
        # CLAUDE.md だけの最小リポジトリでも例外を投げない
        (tmp_path / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
        result = repo_reader.read_allowlisted(tmp_path)
        assert "CLAUDE.md" in result
        assert "README.md" not in result
