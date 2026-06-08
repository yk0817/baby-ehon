"""Child Reviewer のエントリポイント（env 解決・前段 I/O・グラフ実行）。

CI（``child-review.yml``）から ``python -m child_reviewer.run`` で起動する。前段の I/O
（PR チェックアウト・baby.js 種付け・静的配信・差分検出・スクショ・差分読込）をここで
実行して初期 state を作り、``graph.build_graph`` の judge→post_pr_comment を回す。

前段ノード（§7.1）:
    checkout_pr → seed_baby_js → serve_static → detect_changed_books → capture
    → read_code_diff → (graph: judge → ... → post_pr_comment)

**seed_baby_js**: ``shared/baby.example.js`` を ``shared/baby.js`` に複製する。これで
デフォルト名「あかちゃん」が使われ、**実名を CI に持ち込まない**（§8.5）。

オフライン dry-run（DoD）:
    ``DRY_RUN`` が真なら PR へ投稿しない。Playwright / chromium が使えない環境では
    capture をスタブ化（プレースホルダのスクショパスを置く）。``OPENAI_API_KEY`` 未設定
    なら judge もスタブにする。所見（rendered_review）とルーブリックを stdout に出して
    完走する。GITHUB 系 env 未設定でも落ちない。

env:
    DRY_RUN, PR_NUMBER, OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL_CHILD,
    BABY_EHON_NAME_DENYLIST, PROMPT_DIR, GITHUB_TOKEN, GITHUB_REPOSITORY

設計: docs/automation/agent-pipeline.md §7 / §8.5 / §2.1 / §3.1
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import llm as llm_mod
from common import privacy

from . import nodes, prompts

ROLE = "child"
DRY_RUN_ENV = "DRY_RUN"
PR_NUMBER_ENV = "PR_NUMBER"
REPO_ENV = "GITHUB_REPOSITORY"
TOKEN_ENV = "GITHUB_TOKEN"

#: スクショ出力先（Actions artifact にアップロードする想定、§7.5）。
SCREENSHOT_DIR_ENV = "CHILD_REVIEW_SCREENSHOT_DIR"
DEFAULT_SCREENSHOT_DIR = "child-review-screenshots"

#: judge / score スタブ応答（オフライン dry-run 用、ネットワーク不要）。
_STUB_REVIEW = (
    "（stub: Vision LLM 未接続）\n\n"
    "### 良かった点\n"
    "- タップに即時の反応がありそう（fun=4）\n"
    "- 操作対象が分かりやすい（clarity=4）\n\n"
    "### 気になった点\n"
    "- 音量・点滅は控えめか要確認（safety=4）\n"
    "- 既存 5 冊とトーンが揃っているか要確認（consistency=4）"
)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RunConfig:
    """run のオプション（env から解決した不変設定）。"""

    dry_run: bool
    pr_number: int | None
    has_api_key: bool
    repo: str | None
    token: str | None
    screenshot_dir: str
    denylist: tuple[str, ...] = field(default_factory=tuple)


def load_config(env: Mapping[str, str] | None = None) -> RunConfig:
    """env から ``RunConfig`` を組み立てる。"""
    source = os.environ if env is None else env
    pr_raw = source.get(PR_NUMBER_ENV, "").strip()
    pr_number = int(pr_raw) if pr_raw.isdigit() else None
    return RunConfig(
        dry_run=_is_truthy(source.get(DRY_RUN_ENV)),
        pr_number=pr_number,
        has_api_key=bool(source.get(llm_mod.API_KEY_ENV, "").strip()),
        repo=source.get(REPO_ENV, "").strip() or None,
        token=source.get(TOKEN_ENV, "").strip() or None,
        screenshot_dir=source.get(SCREENSHOT_DIR_ENV, DEFAULT_SCREENSHOT_DIR).strip()
        or DEFAULT_SCREENSHOT_DIR,
        denylist=privacy.load_denylist(source),
    )


def _repo_root() -> Path:
    """リポジトリルート（.github/scripts の 2 つ上）を返す。"""
    return Path(__file__).resolve().parents[3]


def _discover_books(repo_root: Path) -> list[str]:
    """``*/config.js`` を持つ絵本ディレクトリ名を列挙する（決定的順）。"""
    return sorted(p.parent.name for p in repo_root.glob("*/config.js"))


# --- 前段 I/O（checkout / seed / serve / diff / capture / read） --------------


def seed_baby_js(repo_root: Path) -> bool:
    """``shared/baby.example.js`` を ``shared/baby.js`` に複製する（§8.5）。

    デフォルト名「あかちゃん」を使い、実名を CI に持ち込まない。example が無ければ
    何もしない（False を返す）。
    """
    example = repo_root / "shared" / "baby.example.js"
    target = repo_root / "shared" / "baby.js"
    if not example.is_file():
        return False
    shutil.copyfile(example, target)
    return True


def git_diff_names(branch: str, *, base: str = "origin/main") -> str:
    """``git diff <base>...<branch>`` の出力を返す（差分検出用）。

    取得に失敗したら空文字（呼び出し側が本棚 index.html にフォールバック）。
    """
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{branch}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    # name-only 出力を detect_changed_books が読める ``b/<path>`` 形に整える。
    return "\n".join(f"b/{line}" for line in completed.stdout.splitlines() if line)


def read_code_diff(repo_root: Path, books: Sequence[str]) -> dict[str, str]:
    """対象冊の HTML/CSS/JS を allowlist 経由で読み込む（§7.7）。

    ``common.repo_reader`` の allowlist（core + ``*/config.js`` + 代表 index.html）を
    使い、対象冊の ``index.html`` / ``theme.css`` を extra_paths で追加する。
    """
    from common import repo_reader

    extras: list[str] = []
    for book in books:
        extras.append(f"{book}/index.html")
        extras.append(f"{book}/theme.css")
    return repo_reader.read_allowlisted(repo_root, extra_paths=extras)


def capture_or_stub(
    base_url: str | None,
    books: Sequence[str],
    *,
    out_dir: Path,
) -> list[dict]:
    """実 Playwright でスクショを撮る。使えなければプレースホルダにフォールバックする。

    ``base_url`` が None（配信なし）か Playwright / chromium が無い場合は、各冊 ×
    各ビューポート × 各フェーズの**スタブ paths** を返す（実ファイルは作らない）。
    これでブラウザ / ネット無しでも capture 経路を完走できる（DoD）。
    """
    targets = list(books) or [""]

    if base_url is not None:
        try:
            from . import browser  # 遅延 import（Playwright をここでだけ要求）

            shots: list[dict] = []
            for book in targets:
                shots.extend(browser.capture(base_url, book, out_dir=out_dir))
            if shots:
                return shots
        except Exception as exc:  # noqa: BLE001  ブラウザ不可ならスタブに落とす
            print(f"WARN: 実スクショ取得に失敗、スタブにフォールバック（{exc}）")

    return _stub_shots(targets, out_dir)


def _stub_shots(books: Sequence[str], out_dir: Path) -> list[dict]:
    """Playwright 不可時のプレースホルダ・スクショ記述（実ファイルは作らない）。"""
    from .browser import PHASES, VIEWPORTS

    shots: list[dict] = []
    for book in books:
        name = book or "shelf"
        for width in VIEWPORTS:
            for phase in PHASES:
                shots.append(
                    {
                        "book": name,
                        "viewport": width,
                        "phase": phase,
                        "path": str(out_dir / f"{name}_{width}_{phase}.png"),
                    }
                )
    return shots


# --- judge / IO の解決 --------------------------------------------------------


def _build_judge(config: RunConfig, env: Mapping[str, str], system_persona: str):
    """Vision judge 関数を返す。API キーが無ければスタブ（オフライン）。"""
    if not config.has_api_key:

        def stub_judge(_system: str, _user: str, _images: Sequence[str]) -> str:
            return _STUB_REVIEW

        return stub_judge

    client = llm_mod.create_client(env=env)
    budget = llm_mod.RunBudget()

    def call(system: str, user: str, image_urls: Sequence[str]) -> str:
        merged = f"{system_persona}\n\n{system}" if system else system_persona
        return llm_mod.chat(
            client,
            role=ROLE,
            system=merged,
            user=user,
            image_urls=image_urls,
            budget=budget,
            env=env,
        )

    return call


def _make_io(config: RunConfig, env: Mapping[str, str]) -> Any | None:
    """GitHubIO を生成する。token / repo 未設定なら None（dry-run のみ許容）。"""
    if not config.repo or not config.token:
        return None
    from common.github_io import GitHubIO

    return GitHubIO(config.repo, token=config.token, env=env)


def _system_persona(role_prompts: Any) -> str:
    """system + persona を連結した judge 用システムプロンプト。"""
    base = role_prompts.system
    persona = (role_prompts.persona or "").strip()
    return f"{base}\n\n{persona}" if persona else base


# --- dedupe（§7.6） -----------------------------------------------------------


def already_reviewed_today(io: Any | None, pr_number: int) -> bool:
    """PR に当日の child-review-run マーカーがあれば True（二重起動防止、§7.6）。"""
    if io is None:
        return False
    bodies = [getattr(c, "body", "") or "" for c in io.list_issue_comments(pr_number)]
    return nodes.has_today_review_marker(bodies)


# --- main --------------------------------------------------------------------


def main(env: Mapping[str, str] | None = None, *, out=sys.stdout) -> int:
    """Child Reviewer を 1 回実行する。0 が正常終了。"""
    source = dict(os.environ if env is None else env)
    config = load_config(source)

    if config.pr_number is None:
        print(
            f"ERROR: {PR_NUMBER_ENV} が未設定です（対象 PR 番号が必要）",
            file=sys.stderr,
        )
        return 1

    io = _make_io(config, source)
    if io is None and not config.dry_run:
        print(
            "ERROR: GITHUB_TOKEN/GITHUB_REPOSITORY が未設定です"
            "（実運用には必須。DRY_RUN=true ならオフラインで回せます）",
            file=sys.stderr,
        )
        return 1

    if already_reviewed_today(io, config.pr_number):
        print(
            f"--- PR #{config.pr_number}: 当日レビュー済みのためスキップ ---", file=out
        )
        return 0

    repo_root = _repo_root()
    role_prompts = prompts.load(env=source)

    state = _prepare_state(config, repo_root, io)
    state = _run_graph(state, config, source, role_prompts, io)

    _report(state, config=config, out=out)
    return 1 if state.get("abort") else 0


def _prepare_state(
    config: RunConfig, repo_root: Path, io: Any | None
) -> nodes.ChildReviewState:
    """前段 I/O を実行して初期 state を組み立てる（checkout は CI 側が済ませる前提）。"""
    seed_baby_js(repo_root)

    branch = (
        f"claude/issue-{config.pr_number}"  # 既定の命名規約（実 branch は CI 取得）
    )
    diff_text = git_diff_names(branch)
    known = _discover_books(repo_root)
    books = nodes.detect_changed_books(diff_text, known_books=known)

    out_dir = repo_root / config.screenshot_dir
    # 配信は実ブラウザがある場合のみ意味を持つ。スタブ経路では base_url=None。
    base_url = _maybe_serve(repo_root)
    shots = capture_or_stub(base_url, books, out_dir=out_dir)
    code = read_code_diff(repo_root, books)

    pr_body = ""
    if io is not None:
        pr_body = _fetch_pr_body(io, config.pr_number)

    return {
        "pr_number": config.pr_number,
        "branch": branch,
        "pr_body": pr_body,
        "changed_books": books,
        "screenshots": shots,
        "code_excerpts": code,
        "raw_review": "",
        "rubric": {},
        "rendered_review": "",
        "artifact_url": None,
        "posted_comment_url": None,
        "errors": [],
    }


def _maybe_serve(repo_root: Path) -> str | None:
    """Playwright が import できるときだけ静的配信を立てる（それ以外は None）。"""
    try:
        import playwright  # noqa: F401  存在確認のみ
    except ImportError:
        return None
    try:
        from . import browser

        server = browser.serve_static(repo_root)
        return server.base_url
    except Exception as exc:  # noqa: BLE001  配信失敗はスタブに落とす
        print(f"WARN: 静的配信の起動に失敗（{exc}）")
        return None


def _fetch_pr_body(io: Any, pr_number: int) -> str:
    """PR 本文を取得する（issue API 互換で body を読む）。失敗時は空。"""
    try:
        issue = io.get_issue(pr_number)
        return getattr(issue, "body", "") or ""
    except Exception:  # noqa: BLE001  取得失敗で全体を止めない
        return ""


def _run_graph(
    state: nodes.ChildReviewState,
    config: RunConfig,
    env: Mapping[str, str],
    role_prompts: Any,
    io: Any | None,
) -> nodes.ChildReviewState:
    """judge → score → format → privacy → post をグラフで回す。"""
    judge_fn = _build_judge(config, env, _system_persona(role_prompts))

    from .graph import build_graph  # 遅延 import（langgraph をここでだけ要求）

    graph = build_graph(
        judge_fn=judge_fn,
        io=io,
        system="",
        denylist=config.denylist,
        dry_run=config.dry_run,
    )
    return graph.invoke(state)


def _report(state: nodes.ChildReviewState, *, config: RunConfig, out) -> None:
    """所見・ルーブリック・結果を stdout にまとめて出す（DoD）。"""
    print("\n=== Child Reviewer 実行結果 ===", file=out)
    print(f"対象 PR : #{state.get('pr_number')}", file=out)
    print(f"対象冊  : {state.get('changed_books') or '（本棚 index.html）'}", file=out)
    print(f"スクショ: {len(state.get('screenshots', []))} 枚", file=out)
    print(f"ルーブリック: {state.get('rubric')}", file=out)
    if config.dry_run:
        print("投稿    : DRY_RUN のため投稿していません", file=out)
    else:
        print(f"投稿    : {state.get('posted_comment_url') or '(投稿なし)'}", file=out)
    if state.get("abort"):
        print("プライバシー違反で中断（投稿なし）:", file=out)
        for msg in state.get("errors", []):
            print(f"  - {privacy.redact(msg, config.denylist)}", file=out)
    print("\n--- 所見（rendered_review） ---", file=out)
    print(state.get("rendered_review", ""), file=out)


if __name__ == "__main__":
    raise SystemExit(main())
