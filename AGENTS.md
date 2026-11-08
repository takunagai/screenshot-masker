# AGENTS.md

このリポジトリで作業する AI コーディングエージェント（Claude Code・Codex など）への指示。利用者向けの説明は [README.md](README.md)。

公開・共有する前のスクリーンショット（ブログ・README・マニュアル・SNS・Issue・資料など）から機密文字列を OCR（Tesseract）で見つけてマスクする CLI と、指示ファイル（YAML / JSON）から注釈を描く `annotate` サブコマンド。Python 3.12・uv・Pillow・pytesseract・PyYAML。

## コマンド

```sh
uv sync                                           # 依存（dev グループを含む）
uv run ruff check && uv run ruff format --check   # lint・整形
uv run mypy                                       # strict。src と tests の両方が対象
uv run pytest                                     # 全テスト
uv run pytest tests/test_detect.py::test_allowed_domain_is_kept   # 1 件だけ
uv run pytest -m "not tesseract"                  # 実際の OCR を使うテストを除く
uv run pytest -rs                                 # skip の理由を表示
```

- 変更後は ruff check・ruff format --check・mypy・pytest の 4 つを通す
- `tests/test_ocr_integration.py` は Tesseract（`jpn+eng`）が無いと skip される。`ocr.py` や検出の境界を変えたときは `-rs` で skip されていないことを確かめる。skip を合格と数えない
- 手元での動作確認は `uv run screenshot-masker examples/sample.png --dry-run`（架空のメール・API キーが 2 件検出され、終了コード 1）

## 構成

処理の流れ（`src/screenshot_masker/`）:

```
cli.main ─┬─ マスク:   _load_image → ocr.run_ocr → detect.detect → mask.apply_mask → _save_image
          └─ annotate: annotate_cli.main → spec.load_spec → 画像ごとに（--mask なら上と同じ OCR マスク）→ render.render → _save_image
```

- `cli.main` は最初の引数が `annotate` なら `annotate_cli.main` に渡す。`annotate_cli` は `cli` の `plan_jobs`・`_load_image`・`_save_image`・`format_detection`・終了コード定数を再利用するため、`cli` 側では関数内で遅延 import している（循環 import の回避）。`_` 付きの非公開関数（`_load_image`・`_save_image`・`_report_error`）にも依存しているので、`cli` 側でこれらの名前や引数を変えるときは `annotate_cli` も直す
- `cli.main` は最初の引数が `hook` なら `hook_cli.main` に渡す。Claude Code のフック（`PreToolUse` の Read と `UserPromptSubmit`）の入力 JSON を標準入力で受け、検出したら止める（`--on-detect mask` なら Read に限りマスクした写しへ `updatedInput` で差し替える）。調べられないときも止める（安全側に倒す）。出力は Claude Code が読む JSON なので、形を変えるときは公式の hooks のドキュメントで確かめ、実機（`claude -p --settings <フックの設定>`）で動作を確かめる
- `main(argv, ocr=...)` で OCR 関数を差し替えられる。テストはこれでフェイクを渡す
- `ocr.prepare_for_ocr` はグレースケール化・暗い背景の反転・autocontrast を行う。寸法を変えないので、OCR の座標は元画像の座標としてそのまま使う。`_load_image` は EXIF の向きを先に反映する（座標と保存画像を一致させるため）
- `detect` は OCR に依存しない純関数。`Word.line_key` で行に組み立て、各行を「空白区切りで連結」と「隙間が行の高さ × `TIGHT_GAP_RATIO` 未満なら詰めて連結」の 2 通りで全ルールと照合する。同じ行で単語集合が既存の候補に含まれるものは捨てる（広い範囲が優先、同じ広さなら `build_rules` の並び順が優先順位）。照合の前に全角の英数字・記号を半角にそろえる（1 文字ずつの置き換えなので、文字と単語の位置の対応は崩れない）
- 種類は `DEFAULT_KINDS`（既定で検出）と `OPTIONAL_KINDS`（設定ファイルの `[detect] enabled` で指定したときだけ）に分かれる。`build_rules` の並びは `DEFAULT_KINDS` と一致させる（テストで確かめている）。誤検出を抑える検証関数（Luhn・マイナンバーの検査用数字・電話番号の桁数と先頭・IPv6 の形式など）は `Rule.validator` に置く
- 規則を足すときは、OCR の読み違い（ハイフンが長音記号「ー」になる、コロンや数字の途中に空白が入る、`\` が `¥` になる）を `tests/test_ocr_integration.py` の実画像で確かめる
- 設定は `config.load_config` が `-c`、`./screenshot-masker.toml`、`~/.config/screenshot-masker/config.toml` の順に最初の 1 つだけ読み、frozen dataclass の `Config` にする。`[annotate]` は `style.merge_style` で合成し、`blur.radius` / `fill.color` の既定値は `[mask]` から引き継ぐ
- スタイルの重なり順: `style.DEFAULT_STYLE` < 設定ファイルの `[annotate]` < 指示ファイルの `style` < 各指示に書いた項目
- `spec.parse_spec` は `masks` を `annotations` より前に並べる（ファイル内の記述順に関係なく先に処理）。`render.render` は `RENDERERS` の表で種類ごとの描画関数に振り分ける
- `render` の図形はスーパーサンプリング（`SUPERSAMPLE`、`MAX_LAYER_PIXELS` で上限）で描く。倍率は `画像の幅 ÷ reference_width` を四捨五入（`round()` の偶数丸めではない）した整数で最小 1。注釈の `blur` / `fill` は `geometry.Region.to_mask_box` を経て `mask` の処理を再利用する
- 利用者向けの例外は `ConfigError`・`SpecError`（`errors.py`）・`UsageError`・`OcrUnavailableError`。メッセージは利用者にそのまま見せる日本語で書く。CLI が捕捉して `エラー: …` を標準エラー出力に出し、`--debug` のときだけトレースバックを出す。設定・指示ファイルの誤りと OCR が無いことは全画像に共通なので即中止し、画像単位の `OSError`・`UnidentifiedImageError` は残りを処理してから終了コード 2

## 壊してはいけない性質

- **一致した文字列を出力・保持しない。** `Detection` は種類と位置だけを持つ。標準出力は `パス\t種類\tx=… y=… w=… h=…` の形だけ。ログ・例外メッセージ・テストの assert メッセージにも OCR のテキストを入れない
- **元画像を上書きしない。** 出力先の衝突検査は `cli.plan_jobs` に集約している。新しい出力経路もここを通す
- **確認用画像（`<出力先>_preview/`）はマスク前の文字を含む。** 接尾辞 `PREVIEW_DIR_SUFFIX` を変えるなら `.gitignore` と `.claude/settings.json` も揃える（[docs/AIエージェントの読み取り制限.md](docs/AIエージェントの読み取り制限.md)）
- マスクはモザイク化してからぼかし、半径を範囲の高さの半分以上に引き上げる。復元しやすい処理に弱めない
- 終了コード: 0 検出なし / 1 検出あり / 2 エラー。1 はエラーではない
- 設定ファイル・指示ファイルの未知の項目はエラーにする（綴りの誤りを見逃さないため）。設定の項目を足すときは `config.py` の `*_KEYS`、指示の項目を足すときは `spec.GEOMETRY_KEYS`・`spec.REQUIRED_KEYS`・`style.DEFAULT_STYLE` を、README の表・例とあわせて揃える。注釈の種類（`type`）そのものを足すときは、さらに `style.ANNOTATION_TYPES`・`render.RENDERERS`（マスク系なら `spec.MASK_TYPES` も）を揃える
- YAML は `yaml.safe_load` だけで読む

## テスト

- OCR はフェイクに差し替える。`tests/helpers.words_from_lines` で等幅に並べた `Word` を作れる
- `main` や `load_config(None)` を呼ぶテストは、`monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", ())` で既定の設定ファイルを探さないようにする（開発者の手元の `./screenshot-masker.toml`・`~/.config/screenshot-masker/config.toml` を読むと結果が環境によって変わる）。既存の CLI テストは autouse の fixture でこれを行っている
- 検出を伴う CLI テストでは、`assert SECRET not in output.out + output.err` のように、一致した文字列が出力に出ないことも確かめる
- 注釈は `tests/image_helpers.run` で描き、`changed_box`・`pixel` で画素を検査する
- テストと `examples/` の値は例示用だけを使う（`example.com`、`192.0.2.0/24` などの文書用アドレス、`sk-test-…` のような架空のトークン）。実在のメールアドレス・トークン・実際のスクリーンショットをリポジトリに入れない
- `.gitignore` は `examples/*.png` と `docs/images/*.png`（README の図）以外の画像（png / jpg / jpeg）をすべて除外している。説明用の画像を別の場所に足すときは `!` の例外行を足す。`git add -f` で除外を回避しない

## 同梱のスキル（Claude Code プラグイン）

- リポジトリのルートが Claude Code のプラグイン（`.claude-plugin/plugin.json`）。配布用のカタログ（マーケットプレイス `takunagai`）は別リポジトリ `takunagai/claude-plugins` にあり、このリポジトリを `github` ソースで参照している。プラグイン名 `screenshot-masker` はカタログの登録名と一致させたまま変えない（変えると既存のインストールが壊れる）
- スキルは `skills/mask-screenshots/SKILL.md`。Codex には同じフォルダを `~/.agents/skills/` に置いて使う。手元で試すときは `claude --plugin-dir .` で読み込める
- CLI の挙動（オプション・出力形式・終了コード・設定項目・確認用画像の場所）を変えたら、`SKILL.md` も同じコミットで直す
- `plugin.json` には `version` を書かない。書くと値を上げるまで利用者に変更が届かないため、コミットごとに更新が届く設定にしている
- スキルを変えたら `claude plugin validate .` と `claude plugin eval . --trust-plugin --no-publish` を通す。eval は `evals/<ケース名>/`（`prompt.md` と `graders/`）にあり、1 回の実行ごとにモデルを呼ぶので費用がかかる。結果は `evals/results/`（Git 管理外）
- 実行される環境では、プラグイン以外のユーザー設定・CLAUDE.md・`.claude/` は読まれない。eval の採点がこのリポジトリの `.claude/settings.json` に頼らないようにする

## このツールでスクリーンショットを処理するとき

エージェントが利用者に頼まれて実際の画像をマスクする場合:

- 元の画像と `*_preview/` の画像を開かない（Read・画像表示・OCR の結果表示を含む）。開くと機密がモデルの文脈と会話ログに入る。判断は標準出力（種類・位置だけ）と終了コードで行う
- 画像の目視は人間に任せる。マスク済みの出力でも、OCR が見落とした機密はそのまま写っているので、必要が無い限り開かない
- 終了コード 1 は「検出してマスクした」という意味。失敗として再実行しない
- 検出 0 件は安全の証明ではない（OCR の見落としがある）。公開前に人間が目視するよう伝える
- Claude Code では `.claude/settings.json` が `*_preview/` 配下の読み取りを拒否する。Codex など他のエージェントにはこの制限が効かないので、上の規律を自分で守る

## 規約

- コメント・docstring・利用者向けメッセージは日本語。コミットメッセージは日本語の Conventional Commits
- ruff の `allowed-confusables` で全角の `（`・`）`・`：` を許可している
- 利用者から見える挙動（オプション・設定項目・検出する種類・出力形式・終了コード）を変えたら README も更新する
- ライセンスは Apache-2.0（`LICENSE`）。依存を足すときは、Apache-2.0 と組み合わせられるライセンスか確かめる
