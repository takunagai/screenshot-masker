# AGENTS.md

このリポジトリで作業する AI コーディングエージェント（Claude Code・Codex など）への指示。利用者向けの説明は [README.md](README.md)。

ブログ用スクリーンショットから機密文字列を OCR（Tesseract）で見つけてマスクする CLI と、指示ファイル（YAML / JSON）から注釈を描く `annotate` サブコマンド。Python 3.12・uv・Pillow・pytesseract・PyYAML。

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
          └─ annotate: annotate_cli.main →（--mask なら上と同じ OCR マスク）→ spec.load_spec → render.render
```

- `cli.main` は最初の引数が `annotate` なら `annotate_cli.main` に渡す。`annotate_cli` は `cli` の `plan_jobs`・`_load_image`・`_save_image`・`format_detection`・終了コード定数を再利用するため、`cli` 側では関数内で遅延 import している（循環 import の回避）
- `main(argv, ocr=...)` で OCR 関数を差し替えられる。テストはこれでフェイクを渡す
- `ocr.prepare_for_ocr` はグレースケール化・暗い背景の反転・autocontrast を行う。寸法を変えないので、OCR の座標は元画像の座標としてそのまま使う。`_load_image` は EXIF の向きを先に反映する（座標と保存画像を一致させるため）
- `detect` は OCR に依存しない純関数。`Word.line_key` で行に組み立て、各行を「空白区切りで連結」と「隙間が行の高さ × `TIGHT_GAP_RATIO` 未満なら詰めて連結」の 2 通りで全ルールと照合する。同じ行で単語集合が既存の候補に含まれるものは捨てる（広い範囲が優先、同じ広さなら `build_rules` の並び順が優先順位）
- 設定は `config.load_config` が `-c`、`./screenshot-masker.toml`、`~/.config/screenshot-masker/config.toml` の順に最初の 1 つだけ読み、frozen dataclass の `Config` にする。`[annotate]` は `style.merge_style` で合成し、`blur.radius` / `fill.color` の既定値は `[mask]` から引き継ぐ
- スタイルの重なり順: `style.DEFAULT_STYLE` < 設定ファイルの `[annotate]` < 指示ファイルの `style` < 各指示に書いた項目
- `spec.parse_spec` は `masks` を `annotations` より前に並べる（ファイル内の記述順に関係なく先に処理）。`render.render` は `RENDERERS` の表で種類ごとの描画関数に振り分ける
- `render` の図形はスーパーサンプリング（`SUPERSAMPLE`、`MAX_LAYER_PIXELS` で上限）で描く。倍率は `画像の幅 ÷ reference_width` を四捨五入（`round()` の偶数丸めではない）した整数で最小 1。注釈の `blur` / `fill` は `geometry.Region.to_mask_box` を経て `mask` の処理を再利用する
- 利用者向けの例外は `ConfigError`・`SpecError`（`errors.py`）・`UsageError`・`OcrUnavailableError`。メッセージは利用者にそのまま見せる日本語で書く。CLI が捕捉して `エラー: …` を標準エラー出力に出し、`--debug` のときだけトレースバックを出す。設定・指示ファイルの誤りと OCR が無いことは全画像に共通なので即中止し、画像単位の `OSError` は残りを処理してから終了コード 2

## 壊してはいけない性質

- **一致した文字列を出力・保持しない。** `Detection` は種類と位置だけを持つ。標準出力は `パス\t種類\tx=… y=… w=… h=…` の形だけ。ログ・例外メッセージ・テストの assert メッセージにも OCR のテキストを入れない
- **元画像を上書きしない。** 出力先の衝突検査は `cli.plan_jobs` に集約している。新しい出力経路もここを通す
- **確認用画像（`<出力先>_preview/`）はマスク前の文字を含む。** 接尾辞 `PREVIEW_DIR_SUFFIX` を変えるなら `.gitignore` と `.claude/settings.json` も揃える（[docs/AIエージェントの読み取り制限.md](docs/AIエージェントの読み取り制限.md)）
- マスクはモザイク化してからぼかし、半径を範囲の高さの半分以上に引き上げる。復元しやすい処理に弱めない
- 終了コード: 0 検出なし / 1 検出あり / 2 エラー。1 はエラーではない
- 設定ファイル・指示ファイルの未知の項目はエラーにする（綴りの誤りを見逃さないため）。設定の項目を足すときは `config.py` の `*_KEYS`、指示の項目を足すときは `spec.GEOMETRY_KEYS`・`spec.REQUIRED_KEYS`・`style.DEFAULT_STYLE` を、README の表・例とあわせて揃える
- YAML は `yaml.safe_load` だけで読む

## テスト

- OCR はフェイクに差し替える。`tests/helpers.words_from_lines` で等幅に並べた `Word` を作れる
- 注釈は `tests/image_helpers.run` で描き、`changed_box`・`pixel` で画素を検査する
- テストと `examples/` の値は例示用だけを使う（`example.com`、`192.0.2.0/24` などの文書用アドレス、`sk-test-…` のような架空のトークン）。実在のメールアドレス・トークン・実際のスクリーンショットをリポジトリに入れない
- `.gitignore` は `examples/*.png` 以外の画像（png / jpg / jpeg）をすべて除外している。説明用の画像を別の場所に足すときは `!` の例外行を足す。`git add -f` で除外を回避しない

## このツールでスクリーンショットを処理するとき

エージェントが利用者に頼まれて実際の画像をマスクする場合:

- 元の画像と `*_preview/` の画像を開かない（Read・画像表示・OCR の結果表示を含む）。開くと機密がモデルの文脈と会話ログに入る。判断は標準出力（種類・位置だけ）と終了コードで行う
- 画像を見て確かめる必要があるときは、マスク済みの出力だけを見る。`--preview` の画像の目視は人間に任せる
- 終了コード 1 は「検出してマスクした」という意味。失敗として再実行しない
- 検出 0 件は安全の証明ではない（OCR の見落としがある）。公開前に人間が目視するよう伝える
- Claude Code では `.claude/settings.json` が `*_preview/` 配下の読み取りを拒否する。Codex など他のエージェントにはこの制限が効かないので、上の規律を自分で守る

## 規約

- コメント・docstring・利用者向けメッセージは日本語。コミットメッセージは日本語の Conventional Commits
- ruff の `allowed-confusables` で全角の `（`・`）`・`：` を許可している
- 利用者から見える挙動（オプション・設定項目・検出する種類・出力形式・終了コード）を変えたら README も更新する
- ライセンスは Apache-2.0（`LICENSE`）。依存を足すときは、Apache-2.0 と組み合わせられるライセンスか確かめる
