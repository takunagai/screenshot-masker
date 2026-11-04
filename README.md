# screenshot-masker

ブログ記事（Zenn・note など）に載せるスクリーンショットから、公開してはいけない文字列を OCR で見つけてぼかす CLI です。

- 元画像は上書きしません。マスク済み画像は別フォルダに書き出します（出力先が元画像と重なる指定はエラーで止まります）
- 検出結果の表示には「ファイル名・種類・位置」だけを出し、一致した文字列そのものは表示しません
- 書き出す画像は再エンコードされるため、EXIF などのメタデータは引き継がれません

## 導入（macOS）

```sh
# Tesseract 本体と言語データ（日本語を含む）
brew install tesseract tesseract-lang

# uv が無ければ
brew install uv

# このリポジトリで依存を入れる
uv sync
```

Tesseract に日本語（`jpn`）と英語（`eng`）が入っているかは `tesseract --list-langs` で確認できます。

## 使い方

```sh
# 1 枚をマスクして masked/ に出力
uv run screenshot-masker shot.png

# フォルダごと（サブフォルダの構成を保って出力）。出力先を指定
uv run screenshot-masker ~/Desktop/screenshots -o ~/Desktop/masked

# 画像を書かずに検出結果だけを見る
uv run screenshot-masker shot.png --dry-run

# 検出範囲を赤枠で囲んだ確認用画像も出す（<出力先>_preview/ に PNG で保存）
uv run screenshot-masker shot.png -o masked --preview

# ぼかしではなく塗りつぶし
uv run screenshot-masker shot.png --method fill
```

`uv tool install .` でインストールすると、`uv run` なしで `screenshot-masker` として使えます。

### オプション

| オプション | 内容 |
| --- | --- |
| `-o, --output DIR` | マスク済み画像の出力先（既定: `masked`） |
| `-c, --config FILE` | 設定ファイル（TOML） |
| `--method blur\|fill` | マスク方法（既定: 設定ファイルの値、無ければ `blur`） |
| `--dry-run` | 画像を書かず、検出結果だけを標準出力に出す |
| `--preview` | 確認用画像を `<出力先>_preview/` に出す。`--dry-run` とは同時に使えません |
| `--debug` | エラー時に詳細（トレースバック）を表示する |

> [!WARNING]
> 確認用画像（`--preview`）にはマスク前の文字がそのまま残ります。公開用のフォルダに混ぜないでください。

### 出力

標準出力に 1 件 1 行、タブ区切りで出します。

```
shots/shot.png	email	x=130 y=40 w=259 h=30
shots/shot.png	url	x=100 y=100 w=414 h=30
```

集計とエラーは標準エラー出力に出します。

### 終了コード

| コード | 意味 |
| --- | --- |
| 0 | 検出なし |
| 1 | 検出あり |
| 2 | エラー（入力が無い、設定が不正、Tesseract が無い、画像が読めない など） |

複数の画像のうち一部だけ読めなかった場合も、残りは処理したうえで 2 を返します。

## 検出する種類

| 種類 | 内容 |
| --- | --- |
| `claude` | `session_` / `cse_` で始まる英数字列、`claude.ai/code` の URL |
| `url` | `http(s)://`・`www.` で始まるもの、`ドメイン/パス` の形のもの（残してよいドメインを設定可） |
| `email` | メールアドレス |
| `ipv4` | IPv4 アドレス（各値 0〜255 のもの） |
| `home_path` | `/Users/<name>/…`、`/home/<name>/…` |
| `token` | `sk-`・`ghp_`・`gho_`・`xox?-`・`AKIA` で始まるもの、32 文字以上の 16 進列、32 文字以上の base64 らしい列 |
| （任意） | 設定ファイルで追加した正規表現 |

OCR の単語を行単位に組み立ててから照合します。OCR が 1 語を隙間なく分割した場合も連結して照合します。一致した単語の範囲全体（例: `KEY=sk-…` なら `KEY=` も含む）を、枠より少し広げてマスクします。

## 設定ファイル

`-c` で指定するか、次の順に探した最初のファイルを使います。

1. カレントディレクトリの `screenshot-masker.toml`
2. `~/.config/screenshot-masker/config.toml`

例は [`screenshot-masker.example.toml`](screenshot-masker.example.toml) を参照してください。

```toml
[ocr]
lang = "jpn+eng"

[mask]
method = "blur"        # "blur" か "fill"
padding = 6            # 文字の枠から広げるピクセル数
blur_radius = 12       # ぼかしの強さ（文字の高さの半分より小さい値は自動で引き上げ）
fill_color = "#000000" # 塗りつぶしの色

[detect]
disabled = ["ipv4"]                      # 無効にする種類
allowed_domains = ["zenn.dev", "note.com"] # url で残してよいドメイン（サブドメインも含む）

[[detect.custom]]
name = "project_code"
pattern = 'PRJ-\d{4}'
```

`allowed_domains` は `url` にだけ効きます。`claude.ai/code` の URL は `claude` として別に検出されるため、`claude.ai` を許可しても隠れます（残したい場合は `disabled = ["claude"]`）。

## 限界

- OCR の精度に依存します。文字が小さい、背景と文字の色が近い、装飾フォントなどは見落とすことがあります。公開前に必ず目視で確認してください（`--preview` が便利です）
- 照合は行単位です。2 行に折り返した URL などは、片方の行だけが検出されることがあります

## 開発

```sh
uv sync
uv run ruff check && uv run ruff format --check
uv run mypy
uv run pytest
```

Tesseract（`jpn+eng`）が入っていない環境では、実際の OCR を使うテスト（`tests/test_ocr_integration.py`）は skip されます。検出ロジック（`src/screenshot_masker/detect.py`）は OCR から切り離した純関数で、単語と位置のリストを入力にテストしています。
