# AI エージェントの読み取り制限

確認日: 2026-11-08（Claude Code で実測）

## 目的

`--preview` の確認用画像（`<出力先>_preview/`）には、マスク前の機密文字列がそのまま残る。AI エージェントがこの画像を開くと、機密がモデルの文脈と会話ログに入る。これを防ぐ。

## 設定内容

| 対象 | ファイル | 内容 |
| --- | --- | --- |
| Git | `.gitignore` | `*_preview/` を除外。`-o` で出力先を変えても、どの階層の `<名前>_preview/` もコミットされない |
| Claude Code | `.claude/settings.json` | `permissions.deny` に `Read(//**/*_preview/**)`。名前が `_preview` で終わるフォルダの中身を、ファイルシステム上のどこにあっても読ませない |
| Codex など | `AGENTS.md` | 「元画像と `*_preview/` を開かない」という指示のみ。強制する仕組みは無い |

`//` で始まるパターンはファイルシステムのルートからの絶対パス（gitignore 形式）。プロジェクト外の出力先（例: `~/Desktop/masked_preview/`）も対象にするため、`/`（リポジトリ基準）ではなく `//` にしている。

## 効く範囲・効かない範囲

- 効く: Claude Code の Read・Grep・Glob、プロンプトへの画像パスの貼り付け、`cat` などの Claude Code が認識するファイル系コマンド（公式ドキュメントの記載）
- 効かない: Python・Node などのスクリプトが自分で開く場合、`grep -r` のように対象ファイルを名指ししない読み取り、コマンドを別の形に書き換えるフック（例: `cat` を独自コマンドに置き換えるもの）を経由した場合
- 元のスクリーンショットは保護していない。置き場所が利用者ごとに違い、パターンで決められないため。AGENTS.md の指示で補っている
- OS レベルで強制したい場合は Claude Code のサンドボックスを使う（このリポジトリでは未設定）

## 検証結果（2026-11-08）

- 検証済み: リポジトリ内の `masked_preview/` と、リポジトリ外の `x_preview/` のダミーファイルは Read が拒否された。`_preview` で終わらないフォルダは読めた
- 検証済み: `git check-ignore` で `masked_preview/`・`out_preview/`・`sub/out_preview/` が除外されることを確認
- 未検証: Bash の `cat` が deny ルールで止まるか（検証環境ではフックが `cat` を別コマンドに書き換えたため判定できなかった）

## 変更するとき

- `PREVIEW_DIR_SUFFIX`（`src/screenshot_masker/cli.py`）を変えたら、`.gitignore` と `.claude/settings.json` のパターンも同じ接尾辞に揃える
- deny は allow より優先されるため、`.claude/settings.local.json` の allow ではこの制限に例外を作れない。緩める必要があるときは、共有の `.claude/settings.json` のパターン自体を変える（変えた理由をこのメモに残す）
- 参考: [Claude Code の権限設定](https://code.claude.com/docs/en/permissions)
