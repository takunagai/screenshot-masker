# AI エージェントから使う

Claude Code や Codex などの AI エージェントにスクリーンショットの処理を任せるときは、エージェントが**マスク前の画像を見ない**ようにしてください。エージェントが画像を開くと、写っている機密情報がモデルへの入力と会話ログに残ります。

- 結果の判断は、標準出力（種類と位置だけ）と終了コードで足ります。画像を開く必要はありません
- 終了コード `1` は「検出してマスクした」という意味です。失敗として再実行させないでください
- 画像を目で確かめるのは人間の役目です。マスク済みの画像でも、OCR が見落とした機密はそのまま写っているため、エージェントには必要が無い限り開かせないでください

頼み方の例は [README の「こう頼めます」](../README.md#こう頼めます) にあります。

- [スキルを入れる](#スキルを入れる)
- [フックで画像を止める（Claude Code）](#フックで画像を止めるclaude-code)
- [スキルを使わない場合](#スキルを使わない場合)

## スキルを入れる

この使い方をエージェントに教えるスキル（[`skills/mask-screenshots/SKILL.md`](../skills/mask-screenshots/SKILL.md)）を同梱しています。入れておくと、「記事に載せるスクショの個人情報を隠して」のような依頼で自動的に読み込まれ、上の規律に沿って処理します。ツール本体（[導入](使い方.md#導入)）とは別に入れてください。

### Claude Code

プラグインとして配布しています。ターミナルで実行します。

```sh
# プラグイン集（マーケットプレイス takunagai）を登録する。最初の 1 回だけ
claude plugin marketplace add takunagai/claude-plugins

# スキルを入れる
claude plugin install screenshot-masker@takunagai
```

| 操作 | コマンド |
| --- | --- |
| 更新 | `claude plugin update screenshot-masker@takunagai` |
| 削除 | `claude plugin uninstall screenshot-masker@takunagai` |

- Claude Code 2.1.292 以降なら、登録とインストールを 1 行で行えます: `claude plugin install screenshot-masker --marketplace takunagai/claude-plugins`（セッションの中では `/plugin install screenshot-masker --marketplace takunagai/claude-plugins`。こちらは 2.1.275 以降）
- 更新は自動では届きません。`/plugin` の Marketplaces で `takunagai` を選び、自動更新を有効にすることもできます
- GitHub の SSH 鍵を設定していない場合は、`CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` を環境変数に設定してください（セッションの中からのインストールと更新が HTTPS で行われます）

### Codex

スキルのフォルダを `~/.agents/skills/` に置きます。

```sh
git clone https://github.com/takunagai/screenshot-masker.git
mkdir -p ~/.agents/skills
cp -R screenshot-masker/skills/mask-screenshots ~/.agents/skills/
```

スキルが認識されない場合は Codex を再起動してください。更新するときは、`git pull` してから同じ `cp` をやり直します。

## フックで画像を止める（Claude Code）

スキルは「開かない」という指示ですが、フックを入れると仕組みとして止められます。Claude Code が画像をモデルに渡す前に `screenshot-masker hook` が OCR で調べ、機密らしい文字列を見つけたら止めます。止めた理由には、ファイル名と検出の種類・件数だけを表示します。

| 画像が渡る経路 | フックの動き |
| --- | --- |
| エージェントが画像ファイルを開く（Read） | 検出したら開かせない。`--on-detect mask` を付けると、マスクした写しに差し替えて開かせる |
| プロンプトに画像のパスや `@画像.png` を書いて送る | 検出したら送信を止める（プロンプトは差し替えられないので、`mask` でも止める）。空白や括弧を含むパス（macOS のスクリーンショットの既定の名前など）は、エスケープしていなくても、直後に「を説明して」のような日本語や句点が続いていても読み取る |
| クリップボードから貼り付けた画像（Ctrl+V） | **調べられない。** フックの入力に画像が含まれないため |
| シェルのコマンドや MCP のツールが読む画像 | 対象外 |

使うには、ツール本体を `uv tool install` で入れて `screenshot-masker` をコマンドとして使える状態にし（[導入](使い方.md#導入)）、Claude Code の設定ファイル（全プロジェクトなら `~/.claude/settings.json`、このプロジェクトだけなら `.claude/settings.json`）に次を加えます。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [{ "type": "command", "command": "screenshot-masker hook", "timeout": 60 }]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [{ "type": "command", "command": "screenshot-masker hook", "timeout": 60 }]
      }
    ]
  }
}
```

- 検出したときに止めるのではなくマスクした写しを渡したいときは、Read の方の `command` を `screenshot-masker hook --on-detect mask` にします。差し替えるたびに確認を求めます（権限の規則は差し替えた後のパスで判定されるため、確認しないと、元の画像に掛けた拒否や確認の規則が効かなくなるため）。確認できない非対話モード（`claude -p`）では、止めるのと同じ結果になります。写しは OS の一時フォルダの `screenshot-masker-hook-<利用者 ID>/` に、所有者だけが読める形で置かれます（他の利用者が先に作ったフォルダやシンボリックリンクだった場合は、使わずに止めます）。見落とした機密は写しにもそのまま残ります
- 画像を調べられないとき（Tesseract が無い、画像を開けない・大きすぎる、設定ファイルが不正、予期しないエラーなど）も止めます
- 既定では URL も検出するので、開発中の画面のスクショを見せる作業でも止まりやすくなります。止めたくない種類は、設定ファイルの `disabled` に書いて `screenshot-masker hook -c <設定ファイル>` で渡してください（[設定ファイル](使い方.md#設定ファイル)）
- 止めたプロンプトの文字列は、Claude Code の仕様でセッションの記録に残ります（画像の中身は送られません）
- 2026-11-08 に Claude Code 2.1.319 で、プロンプトを止めること・Read を止めること・マスクした写しに差し替えることを、実際に確かめました。Codex には対応していません

## スキルを使わない場合

記事を書くリポジトリなど、このツールを使う側の指示ファイル（`AGENTS.md` / `CLAUDE.md`）に、次のように書いておくと伝わります。

```markdown
## スクリーンショットのマスク（screenshot-masker）

- 公開する画像は `screenshot-masker <画像またはフォルダ> -o <出力先>` でマスクしてから使う
- マスク前の画像と `*_preview/` の画像は開かない。結果は標準出力（種類・位置）と終了コードで判断する
- 終了コード: 0 検出なし / 1 検出してマスクした（エラーではない）/ 2 エラー
- 検出 0 件でも安全とは限らない。公開前に人間が目視で確認する
```

Claude Code では、設定ファイルで確認用画像の読み取りを禁止できます。このリポジトリでは [`.claude/settings.json`](../.claude/settings.json) で設定済みです。ほかのリポジトリでも同じ制限を掛けるには、そのリポジトリの `.claude/settings.json` に次を加えます。

```json
{
  "permissions": {
    "deny": ["Read(//**/*_preview/**)"]
  }
}
```

この設定は Claude Code にだけ効き、スクリプト経由の読み取りなど防げない経路もあります。効く範囲と確認結果は [AI エージェントの読み取り制限](AIエージェントの読み取り制限.md) にまとめています。
