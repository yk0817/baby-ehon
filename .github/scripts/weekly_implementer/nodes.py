"""Weekly Implementer の純粋ノード関数群（langgraph 非依存・テスト可能）。

各ノードは ``WeeklyState`` の更新差分（dict）を返す純関数に保つ。LLM 呼び出し・
GitHub 読み書き・git 操作などの I/O は引数注入（``llm`` / ``io`` / ``git`` /
``repo_root``）で差し替えられるようにし、ネットワーク・実 LLM・langgraph 無しで
単体テストできるようにする。``graph.py`` だけが langgraph を import し、ここは
ノードの中身と分岐ヘルパに徹する。

フロー（§6.1）::

    list_open_issues → collect_scores → select_top → gather_context
    → plan_change → generate_patch → privacy_check
        ├ 違反 → record_failure_comment → exit 1
        └ OK   → apply_patches → git_commit_push → open_draft_pr → trigger_child_review

最重要ゲート（§2.2 / §6.1）:

- ``select_top``: ``approved`` ラベル必須に絞り、``automation:skip`` / wip を除外、
  最新 ``claude-score`` 最上位を 1 件選ぶ（同点は Issue 番号小）。approved 候補が
  ゼロなら何もせず終了（``selected_issue`` を空のまま返す）。

設計: docs/automation/agent-pipeline.md §6.1 / §6.2 / §6.3 / §6.4 / §6.5 / §2.1 / §2.2 / §8
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypedDict

from common import privacy, score_parser

# --- 定数（マジックナンバー / マジック文字列を排除） --------------------------

APPROVED_LABEL = "approved"  # 人間の作成承認（入口ゲート、§2.2）
SKIP_LABEL = "automation:skip"  # 自動処理の対象外（§2.1）
WIP_LABEL = "wip"  # 作業中（select_top で除外）
STAGE_IMPLEMENTED_LABEL = "stage:implemented"  # 作成者の処理完了（§2.1）
NEEDS_CHILD_REVIEW_LABEL = "needs-child-review"  # こどもレビュワーのキー（§6.4）
CHILD_REVIEW_WORKFLOW = "child-review.yml"  # 連鎖起動するワークフロー（§6.5）

# --- State スキーマ（§6.2 を素直に TypedDict 化） -----------------------------


class WeeklyState(TypedDict, total=False):
    """Weekly Implementer グラフの共有状態（§6.2）。

    ``total=False`` にして、ノードが必要なキーだけを段階的に埋められるようにする。
    """

    candidate_issues: list[dict[str, Any]]  # [{number, title, score, comment_url}]
    selected_issue: dict[str, Any]  # {number, title, body, score}
    context_files: dict[str, str]  # path -> contents
    change_plan: str
    proposed_patches: list[dict[str, Any]]  # [{path, new_contents}]
    privacy_violations: list[str]
    branch_name: str
    pr_url: str | None
    pr_number: int | None
    errors: list[str]


# 注入する LLM 呼び出しの型: (system, user) -> 応答テキスト。
LLMFn = Callable[[str, str], str]


# --- 補助: ラベル抽出 ---------------------------------------------------------


def _label_names(issue: Any) -> list[str]:
    """Issue オブジェクトのラベル名を文字列リストで返す（PyGithub / dict 互換）。"""
    if isinstance(issue, Mapping):
        labels = issue.get("labels", []) or []
    else:
        labels = getattr(issue, "labels", []) or []
    names: list[str] = []
    for label in labels:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, Mapping):
            names.append(str(label.get("name", "")))
        else:
            names.append(getattr(label, "name", str(label)))
    return names


def _issue_attr(issue: Any, key: str, default: Any = None) -> Any:
    """Issue オブジェクトから属性 / キーを取り出す（PyGithub / dict 互換）。"""
    if isinstance(issue, Mapping):
        return issue.get(key, default)
    return getattr(issue, key, default)


# --- list_open_issues（§6.1） ------------------------------------------------


def list_open_issues(
    state: Mapping[str, Any],
    *,
    issues: Sequence[Any],
) -> WeeklyState:
    """open Issue 群を素のまま state に載せる（I/O は呼び出し側で実施）。

    ``issues`` は ``number`` / ``title`` / ``body`` / ``labels`` を持つオブジェクト列
    （PyGithub Issue 互換、または dict）。
    """
    raw: list[dict[str, Any]] = []
    for issue in issues:
        raw.append(
            {
                "number": int(_issue_attr(issue, "number", 0)),
                "title": _issue_attr(issue, "title", "") or "",
                "body": _issue_attr(issue, "body", "") or "",
                "labels": _label_names(issue),
            }
        )
    return {
        "candidate_issues": raw,
        "errors": list(state.get("errors", [])),
    }


# --- collect_scores（§6.1 / §4.3） -------------------------------------------


def collect_scores(
    state: Mapping[str, Any],
    *,
    comments_by_issue: Mapping[int, Sequence[tuple[str, Any]]],
) -> WeeklyState:
    """各 Issue の最新 ``claude-score`` を ``common.score_parser`` で抽出して付与する。

    ``comments_by_issue`` は ``{issue_number: [(body, created_at), ...]}``。コメントが
    無い / マーカーが無い Issue は score を None にする（select_top が弾く）。
    """
    enriched: list[dict[str, Any]] = []
    for issue in state.get("candidate_issues", []):
        number = int(issue.get("number", 0))
        comments = comments_by_issue.get(number, [])
        score = score_parser.latest_claude_score(comments)
        enriched.append({**issue, "score": score})
    return {"candidate_issues": enriched}


# --- select_top（最重要・§2.2 / §6.1） --------------------------------------


def _is_eligible(issue: Mapping[str, Any]) -> bool:
    """select_top の候補資格を判定する。

    - ``approved`` ラベル必須（入口ゲート、§2.2）
    - ``automation:skip`` / ``wip`` が付いていれば除外
    - ``claude-score`` が抽出済み（None でない）
    """
    labels = set(issue.get("labels", []))
    if APPROVED_LABEL not in labels:
        return False
    if SKIP_LABEL in labels or WIP_LABEL in labels:
        return False
    return issue.get("score") is not None


def select_top(state: Mapping[str, Any]) -> WeeklyState:
    """approved 候補のうち最新 ``claude-score`` 最上位を 1 件選ぶ（同点は番号小）。

    approved 候補がゼロなら ``selected_issue`` を空のまま返し、何もしないで終了する
    （§2.2 / §6.1）。errors にスキップ理由を残す。
    """
    candidates = [
        issue for issue in state.get("candidate_issues", []) if _is_eligible(issue)
    ]
    errors = list(state.get("errors", []))

    if not candidates:
        errors.append(
            "select_top: approved 付きの採点済み Issue が無いため実装をスキップ"
        )
        return {"selected_issue": {}, "errors": errors}

    # スコア降順、同点は Issue 番号昇順（小さい方を優先）。
    top = sorted(
        candidates,
        key=lambda i: (-int(i.get("score", 0)), int(i.get("number", 0))),
    )[0]

    selected = {
        "number": int(top["number"]),
        "title": top.get("title", ""),
        "body": top.get("body", ""),
        "score": int(top.get("score", 0)),
    }
    return {"selected_issue": selected, "errors": errors}


def route_selected(state: Mapping[str, Any]) -> str:
    """select_top の分岐: 選定ありなら ``"continue"``、無ければ ``"skip"``。"""
    return "continue" if state.get("selected_issue") else "skip"


# --- gather_context（§6.3） --------------------------------------------------

# 対象 Issue 本文から拾う絵本ファイル（extra_paths として渡す）。
_TARGET_FILE_RE = re.compile(r"[\w./-]+/(?:index\.html|theme\.css)")


def _extra_paths_from_issue(body: str) -> list[str]:
    """Issue 本文に現れる ``*/index.html`` / ``*/theme.css`` を extra_paths 候補に拾う。

    allowlist 側（repo_reader.is_allowed）でさらに絞られるため、ここは緩く拾ってよい。
    """
    found = _TARGET_FILE_RE.findall(body or "")
    # 決定的順 & 重複排除
    seen: set[str] = set()
    paths: list[str] = []
    for path in found:
        normalized = path.lstrip("./")
        if normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)
    return paths


def gather_context(
    state: Mapping[str, Any],
    *,
    reader: Callable[..., dict[str, str]],
    repo_root: Any,
) -> WeeklyState:
    """allowlist 内のファイルを読み込んで state に載せる（150KB cap、§6.3）。

    ``reader`` は ``common.repo_reader.read_allowlisted`` 互換。対象 Issue が指す
    ``*/index.html`` / ``*/theme.css`` は extra_paths として追加で渡す。
    """
    selected = state.get("selected_issue", {}) or {}
    extra = _extra_paths_from_issue(selected.get("body", ""))
    files = reader(repo_root, extra_paths=extra)
    return {"context_files": files}


# --- plan_change / generate_patch（LLM 注入、§6.1） --------------------------


def plan_change(state: Mapping[str, Any], *, llm: LLMFn) -> WeeklyState:
    """LLM に変更計画（触るファイル + 方針）を立てさせる（§6.1）。"""
    selected = state.get("selected_issue", {}) or {}
    context = state.get("context_files", {}) or {}
    system = _plan_system()
    user = _plan_user(selected, context)
    plan = llm(system, user)
    return {"change_plan": (plan or "").strip()}


def _plan_system() -> str:
    return (
        "対象 Issue を HTML/CSS/JS のみで実装するための変更計画を日本語で簡潔に述べてください。\n"
        "触るファイルのパスと、各ファイルでの変更方針を箇条書きで示すこと。"
        "新規ファイルもパスを明記すること。ビルドツール・外部ライブラリは使わない。"
    )


def _plan_user(selected: Mapping[str, Any], context: Mapping[str, str]) -> str:
    file_list = "\n".join(f"- {path}" for path in sorted(context)) or "（なし）"
    return (
        f"# Issue #{selected.get('number', '?')}: {selected.get('title', '')}\n\n"
        f"## Issue 本文\n{selected.get('body', '')}\n\n"
        f"## 読み込み済みファイル\n{file_list}"
    )


def generate_patch(state: Mapping[str, Any], *, llm: LLMFn) -> WeeklyState:
    """LLM に変更計画を反映した全ファイル書き換え案を出させる（§6.1）。

    LLM 応答は ``=== path: <相対パス> ===`` 区切りの複数ブロックを期待し、
    ``[{path, new_contents}]`` にパースする。区切りが無い場合は空のパッチ列にして
    errors を残す（落とさない）。
    """
    selected = state.get("selected_issue", {}) or {}
    context = state.get("context_files", {}) or {}
    plan = state.get("change_plan", "")
    system = _generate_system()
    user = _generate_user(selected, context, plan)
    raw = llm(system, user)

    patches = parse_patch_blocks(raw)
    errors = list(state.get("errors", []))
    if not patches:
        # gpt-5 系の出力截断・形式崩れなどで 0 件のことがある。crash させず、
        # route_generated → record_failure_comment で graceful に終わらせる。
        errors.append(
            "generate_patch: LLM 応答からファイルブロックを抽出できませんでした"
            f"（応答長 {len(raw or '')} 文字）"
        )
    return {"proposed_patches": patches, "errors": errors}


def route_generated(state: Mapping[str, Any]) -> str:
    """生成パッチが空なら failure へ、あれば通常フローへ。"""
    return "ok" if state.get("proposed_patches") else "empty"


# パッチブロックの区切り: `=== path: <相対パス> ===` の次行以降がそのファイルの内容。
_PATCH_HEADER_RE = re.compile(
    r"^===\s*path:\s*(?P<path>[^\n=]+?)\s*===\s*$", re.MULTILINE
)


def parse_patch_blocks(raw: str) -> list[dict[str, str]]:
    """``=== path: <相対パス> ===`` 区切りの応答を ``[{path, new_contents}]`` に分解する。

    各ヘッダの直後から次ヘッダ直前までを当該ファイルの内容とする。コードフェンス
    （```）でくるまれている場合は外側のフェンスを 1 段はがす。
    """
    matches = list(_PATCH_HEADER_RE.finditer(raw or ""))
    patches: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        path = match.group("path").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = raw[start:end]
        patches.append({"path": path, "new_contents": _strip_fence(body)})
    return patches


def _strip_fence(text: str) -> str:
    """前後の改行を整え、外側のコードフェンス（```...```）を 1 段はがす。"""
    stripped = text.strip("\n")
    fence = re.match(r"^```[^\n]*\n(?P<inner>.*)\n```\s*$", stripped, re.DOTALL)
    if fence:
        return fence.group("inner")
    return stripped


def _generate_system() -> str:
    return (
        "変更計画に従い、変更後のファイル内容を全文で出力してください。\n"
        "各ファイルは次の形式で区切ること:\n"
        "=== path: <リポジトリ相対パス> ===\n"
        "<そのファイルの全文>\n"
        "複数ファイルは続けて区切りを並べる。説明文は付けない。"
        "呼びかけ文は必ず __NAME__ プレースホルダで書く（実名禁止）。"
    )


def _generate_user(
    selected: Mapping[str, Any],
    context: Mapping[str, str],
    plan: str,
) -> str:
    blocks = "\n\n".join(
        f"=== path: {path} ===\n{content}" for path, content in sorted(context.items())
    )
    return (
        f"# 変更計画\n{plan}\n\n"
        f"# 現在のファイル内容\n{blocks}\n\n"
        "上記の変更計画を反映した全ファイルを、指定の区切り形式で出力してください。"
    )


# --- privacy_check（§8） -----------------------------------------------------


def privacy_check(
    state: Mapping[str, Any],
    *,
    denylist: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> WeeklyState:
    """生成パッチ全体をプライバシーガードに通す（§8）。

    各パッチ内容に hard-banned / denylist 検査をかけ、``*/config.js`` には
    ``__NAME__`` positive assert もかける。違反があれば ``privacy_violations`` に
    **実値を含まない** メッセージだけを積む（exit 1 は run 側 / 分岐で扱う）。
    """
    violations: list[str] = []
    for patch in state.get("proposed_patches", []):
        path = patch.get("path", "")
        contents = patch.get("new_contents", "")

        for v in privacy.check(contents, denylist=denylist, env=env):
            violations.append(f"{path}: [{v.kind}] {v.message}")

        if path.endswith("config.js"):
            for v in privacy.assert_name_placeholder(contents):
                violations.append(f"{path}: [{v.kind}] {v.message}")

    return {"privacy_violations": violations}


def route_privacy(state: Mapping[str, Any]) -> str:
    """privacy_check の分岐: 違反なしで ``"ok"``、ありで ``"violation"``。"""
    return "violation" if state.get("privacy_violations") else "ok"


def record_failure_comment(
    state: Mapping[str, Any],
    *,
    io: Any,
    dry_run: bool = False,
) -> WeeklyState:
    """プライバシー違反を対象 Issue にコメントする（実値は出さない、§8）。

    違反の件数と種別だけを記し、詳細はログ参照に誘導する。dry_run では投稿しない。
    """
    selected = state.get("selected_issue", {}) or {}
    number = int(selected.get("number", 0))
    violations = state.get("privacy_violations", [])

    body = _failure_comment_body(violations)
    errors = list(state.get("errors", []))
    errors.append(f"privacy violation: {len(violations)} 件検出のため Draft PR を中止")

    if not dry_run and io is not None and number:
        io.create_issue_comment(number, body)
    return {"errors": errors}


def _failure_comment_body(violations: Sequence[str]) -> str:
    """失敗コメント本文を組み立てる（種別のみ・実値は含めない）。"""
    kinds = sorted({v.split("] ")[0].split("[")[-1] for v in violations})
    kind_line = "、".join(kinds) if kinds else "不明"
    return (
        "<!-- weekly-implementer: privacy-block -->\n\n"
        "## ⚠️ プライバシーガードにより Draft PR を中止しました\n\n"
        f"生成された変更案にプライバシー違反の疑いが {len(violations)} 件検出されたため、"
        "PR を作成しませんでした。\n\n"
        f"- 検出種別: {kind_line}\n"
        "- 実際の値はセキュリティのため出力していません（CI ログを参照してください）\n\n"
        "人間が内容を確認し、`__NAME__` プレースホルダ化や denylist 設定を見直してください。"
    )


# --- apply_patches（§6.1） ---------------------------------------------------


def apply_patches(
    state: Mapping[str, Any],
    *,
    writer: Callable[[str, str], None],
    dry_run: bool = False,
) -> WeeklyState:
    """生成パッチをファイルに書き込む（``writer`` 注入で I/O を差し替え可能）。

    ``writer`` は ``(relative_path, contents) -> None``。dry_run では書き込まない。
    """
    if dry_run:
        return {}
    for patch in state.get("proposed_patches", []):
        writer(patch["path"], patch["new_contents"])
    return {}


# --- git_commit_push（§6.4） -------------------------------------------------


def branch_name_for(number: int) -> str:
    """Issue 番号からブランチ名を組み立てる（固定パターン、§6.4）。"""
    return f"claude/issue-{int(number)}"


def commit_message_for(number: int, summary: str) -> str:
    """Conventional Commits 形式のコミットメッセージを組み立てる（§6.4）。

    件名 ``feat: <英語要約> (#N)``、本文 ``Refs #N``。個人メアドは入れない。
    """
    subject = f"feat: {summary.strip()} (#{int(number)})"
    return f"{subject}\n\nRefs #{int(number)}"


def git_commit_push(
    state: Mapping[str, Any],
    *,
    git: Any,
    dry_run: bool = False,
) -> WeeklyState:
    """ブランチを切り、変更をコミットして push する（``git`` 注入）。

    ``git`` は ``create_branch(name)`` / ``add_all()`` / ``commit(message)`` /
    ``push(name)`` を持つオブジェクト。dry_run では branch 名のみ確定し I/O しない。
    """
    selected = state.get("selected_issue", {}) or {}
    number = int(selected.get("number", 0))
    branch = branch_name_for(number)

    if dry_run:
        return {"branch_name": branch}

    summary = _english_summary(selected)
    message = commit_message_for(number, summary)
    git.create_branch(branch)
    git.add_all()
    git.commit(message)
    git.push(branch)
    return {"branch_name": branch}


def _english_summary(selected: Mapping[str, Any]) -> str:
    """コミット件名の英語要約。LLM を使わず安全側で Issue 番号ベースの定型にする。

    日本語タイトルのローマ字化は不安定なので、英語要約は機械的な定型にしておき、
    詳細は PR 本文（§6.4 テンプレ）に委ねる。
    """
    return f"implement issue #{int(selected.get('number', 0))}"


# --- open_draft_pr（§6.4） ---------------------------------------------------


def pr_title_for(number: int, issue_title: str) -> str:
    """PR タイトルを組み立てる（``[draft] <Issue タイトル> (#N)``、§6.4）。"""
    return f"[draft] {issue_title} (#{int(number)})"


def pr_body_for(
    number: int, change_plan: str, patches: Sequence[Mapping[str, str]]
) -> str:
    """PR 本文を §6.4 テンプレで組み立てる（先頭 ``Closes #N``）。"""
    file_lines = (
        "\n".join(f"- {p.get('path', '')}" for p in patches) or "- （変更なし）"
    )
    plan = (change_plan or "").strip() or "（変更計画なし）"
    return _PR_BODY_TEMPLATE.format(
        number=int(number),
        change_plan=plan,
        file_lines=file_lines,
    )


_PR_BODY_TEMPLATE = """Closes #{number}

## 自動生成された変更案
{change_plan}

## 変更ファイル
{file_lines}

## レビュー観点
- [ ] `__NAME__` プレースホルダ以外に人名が入っていないか
- [ ] HTML/CSS/JS のみで完結しているか
- [ ] 5 冊の絵本それぞれで挙動を確認したか
- [ ] README の「ラインナップ」「機能」「構成」セクション更新が必要か

---
このPRはClaude (LangGraph agent) が自動生成しました。**必ず人間がレビューしてからマージしてください。**
"""


def open_draft_pr(
    state: Mapping[str, Any],
    *,
    pr_runner: Callable[..., dict[str, Any]],
    base: str = "main",
    dry_run: bool = False,
) -> WeeklyState:
    """Draft PR を作成し、isDraft == true を assert する（§6.4）。

    ``pr_runner`` は ``(title, body, head, base, draft) -> {url, number, isDraft}`` 互換。
    作成後に再 read した ``isDraft`` が True でなければ ``AssertionError``。
    作成時に PR へ ``needs-child-review``、対象 Issue へ ``stage:implemented`` を付与する
    のは run / graph 側（io 経由）に任せ、ここは PR 作成と assert に徹する。
    dry_run では作成せず ``pr_url`` / ``pr_number`` を None にする。
    """
    selected = state.get("selected_issue", {}) or {}
    number = int(selected.get("number", 0))
    title = pr_title_for(number, selected.get("title", ""))
    body = pr_body_for(
        number, state.get("change_plan", ""), state.get("proposed_patches", [])
    )
    branch = state.get("branch_name", branch_name_for(number))

    if dry_run:
        return {"pr_url": None, "pr_number": None}

    result = pr_runner(title=title, body=body, head=branch, base=base, draft=True)
    if not result.get("isDraft"):
        raise AssertionError("作成した PR が Draft ではありません（isDraft != true）")
    return {"pr_url": result.get("url"), "pr_number": result.get("number")}


def label_pr_and_issue(
    state: Mapping[str, Any],
    *,
    io: Any,
    dry_run: bool = False,
) -> WeeklyState:
    """PR に ``needs-child-review``、対象 Issue に ``stage:implemented`` を付与（§6.4 / §2.1）。

    dry_run では何もしない。``io`` は ``add_labels(number, *labels)`` を持つ
    ``GitHubIO`` 互換。
    """
    if dry_run or io is None:
        return {}
    selected = state.get("selected_issue", {}) or {}
    issue_number = int(selected.get("number", 0))
    pr_number = state.get("pr_number")

    if pr_number:
        io.add_labels(int(pr_number), NEEDS_CHILD_REVIEW_LABEL)
    if issue_number:
        io.add_labels(issue_number, STAGE_IMPLEMENTED_LABEL)
    return {}


# --- trigger_child_review（§6.5） --------------------------------------------


def trigger_child_review(
    state: Mapping[str, Any],
    *,
    workflow_runner: Callable[[str, dict[str, str]], Any],
    dry_run: bool = False,
) -> WeeklyState:
    """こどもレビュワーを連鎖起動する（``gh workflow run``、§6.5）。

    ``workflow_runner`` は ``(workflow_file, inputs) -> None`` 互換。dry_run では実行
    しない（DoD: dry-run は GitHub への書き込みを一切しない）。
    """
    if dry_run:
        return {}
    pr_number = state.get("pr_number")
    if not pr_number:
        return {}
    workflow_runner(CHILD_REVIEW_WORKFLOW, {"pr_number": str(int(pr_number))})
    return {}
