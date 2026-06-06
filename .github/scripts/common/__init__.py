"""共通基盤モジュール（全役が依存）。

このパッケージには、リサーチャー / 作成者 / こども の各役が共通で使う部品を置く。
個々の実装は後続 Issue で追加する（雛形のため現状は空）。

- privacy.py         : 名前 denylist + __NAME__ positive assert（#11）
- llm.py             : OpenAI SDK ラッパ・base_url/モデル選択（#12）
- prompts_loader.py  : prompts/<role>/ の system/persona/rubric 読込（#13）
- github_io.py       : PyGithub ラッパ（#14）
- gh_cli.py          : ローカルデバッグ用 gh CLI ラッパ（#14）
- repo_reader.py     : allowlist 制限付きファイル読み出し（#14）
- score_parser.py    : claude-score / child-review-score マーカー抽出（#14）

設計の正は docs/automation/agent-pipeline.md。
"""
