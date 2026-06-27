"""privacy_gate（ゲート③）の契約テスト。

Contract: 絵本の ``*/config.js`` が ``__NAME__`` プレースホルダを使い、実名・連絡先が
混入していないことを検査する。判定は既存 ``.github/scripts/common/privacy.py`` の再利用で、
ここではゲートとしての**集約・終了コード・秘匿（実値を出さない）**を固定する。

なぜこの挙動が必要か: 公開リポジトリなので maker が生成した config.js に実名が紛れたら
即座に赤（未完了）にしたい。verify.sh の1ゲートとして決定的に判定できることが要件。
"""

from __future__ import annotations

from pathlib import Path

from automation.harness import privacy_gate


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── find_config_js: <slug>/config.js だけを拾う ──────────────────────────────
def test_find_config_js_picks_book_configs(tmp_path: Path) -> None:
    _write(tmp_path / "densha" / "config.js", "x")
    _write(tmp_path / "iro" / "config.js", "y")
    _write(tmp_path / "shared" / "ehon.js", "z")  # config.js でないので対象外

    found = privacy_gate.find_config_js(tmp_path)

    assert [p.name for p in found] == ["config.js", "config.js"]
    assert {p.parent.name for p in found} == {"densha", "iro"}


# ── scan_config: __NAME__ を使う talk は違反なし ─────────────────────────────
def test_scan_config_clean_when_placeholder_used(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "kuruma" / "config.js",
        "window.BOOK_CONFIG = { title: '__NAME__の くるま',\n"
        "  talks: ['__NAME__、\\nしゅっぱつ だよ！'] };\n",
    )

    assert privacy_gate.scan_config(cfg, denylist=()) == []


# ── scan_config: 呼びかけが実名なら name_placeholder 違反 ────────────────────
def test_scan_config_flags_hardcoded_name_in_vocative(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "kuruma" / "config.js",
        "window.BOOK_CONFIG = { talks: ['たろう、\\nしゅっぱつ！'] };\n",
    )

    violations = privacy_gate.scan_config(cfg, denylist=())

    assert any(v.kind == "name_placeholder" for v in violations)


# ── scan_config: denylist の実名はトークン一致で検出 ─────────────────────────
def test_scan_config_flags_denylisted_name(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "kuruma" / "config.js",
        "// __NAME__ で呼ぶが、コメントに たろうくん が紛れた\n"
        "window.BOOK_CONFIG = { talks: ['__NAME__、\\nやあ！'] };\n",
    )

    violations = privacy_gate.scan_config(cfg, denylist=("たろう",))

    assert any(v.kind == "denylist" for v in violations)


# ── main: 違反なしの明示パスは exit 0 ───────────────────────────────────────
def test_main_returns_zero_for_clean_paths(tmp_path: Path, capsys) -> None:
    cfg = _write(
        tmp_path / "iro" / "config.js",
        "window.BOOK_CONFIG = { talks: ['__NAME__、\\nあかだよ！'] };\n",
    )

    code = privacy_gate.main([str(cfg)])

    assert code == 0


# ── main: 違反ありは exit 1、かつ実名を出力に漏らさない ─────────────────────
def test_main_returns_one_and_masks_value(tmp_path: Path, capsys) -> None:
    secret = "たろう"
    _write(
        tmp_path / "kuruma" / "config.js",
        f"window.BOOK_CONFIG = {{ talks: ['{secret}、\\nやあ！'] }};\n",
    )
    cfg = tmp_path / "kuruma" / "config.js"

    code = privacy_gate.main([str(cfg)])
    out = capsys.readouterr()

    assert code == 1
    # Contract: 違反メッセージにも標準出力にも実値（実名）を一切出さない（§8.6）
    assert secret not in out.out
    assert secret not in out.err


# ── main: 存在しない明示パスは traceback でなく exit 1 ──────────────────────
def test_main_returns_one_for_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "config.js"

    code = privacy_gate.main([str(missing)])

    assert code == 1  # FileNotFoundError を投げず、明示的に赤を返す


# ── 出荷済みの絵本 config は全て privacy-clean（回帰契約） ───────────────────
def test_shipped_book_configs_are_clean() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    configs = privacy_gate.find_config_js(repo_root)

    assert configs, "リポジトリに */config.js が見つからない（前提崩れ）"
    for cfg in configs:
        assert privacy_gate.scan_config(cfg, denylist=()) == [], f"{cfg} に違反"
