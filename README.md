# screenshot-masker

ブログ記事（Zenn・note など）に載せるスクリーンショットから、公開してはいけない文字列を OCR で見つけてぼかす CLI です。注釈（枠・番号バッジ・矢印など）を描き込む `annotate` サブコマンドもあります（[注釈を付ける](#注釈を付けるannotate)）。

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

## 注釈を付ける（annotate）

記事や操作マニュアル用に、矢印・番号バッジ・枠・ぼかし・短い文字ラベル・スポットライトを、指示ファイル（YAML / JSON）から機械的に描き込みます。見た目の既定値を設定ファイルにまとめれば、何枚でも同じ見た目の注釈を揃えられます。

- 元画像は上書きしません。出力先フォルダの扱い（フォルダ指定でサブフォルダの構成を保つ、元画像と重なる出力先はエラー）は、マスクと同じです
- `--mask` を付けると、OCR で検出した機密情報をマスクしてから注釈を描きます（マスク → 注釈の順）

```sh
# 1 枚に注釈を描いて annotated/ に出力
uv run screenshot-masker annotate shot.png --spec annotate.yaml

# 機密情報をマスクしてから注釈を描く。見た目は記事ごとの設定ファイルから
uv run screenshot-masker annotate shot.png --spec annotate.yaml --mask -c article.toml -o out

# フォルダごと（すべての画像に同じ指示を適用）
uv run screenshot-masker annotate ~/Desktop/screenshots --spec annotate.yaml -o ~/Desktop/annotated
```

### オプション（annotate）

| オプション | 内容 |
| --- | --- |
| `-s, --spec FILE` | 指示ファイル（`.yaml` / `.yml` / `.json`）。必須 |
| `-o, --output DIR` | 出力先（既定: `annotated`） |
| `-c, --config FILE` | 設定ファイル（TOML）。`[annotate]` に見た目の既定値、`[mask]` に `--mask` の設定 |
| `--mask` | 注釈の前に、OCR で検出した機密情報をマスクする |
| `--method blur\|fill` | `--mask` のマスク方法（`--mask` と一緒に指定） |
| `--scale auto\|数値` | 線の太さなどの倍率（既定: 画像の幅から自動。後述） |
| `--debug` | エラー時に詳細（トレースバック）を表示する |

終了コードはマスクと同じです（成功 0 / `--mask` で検出あり 1 / エラー 2）。`--mask` のときは、検出結果をマスクと同じ形式で標準出力に出します。

### 例

[`examples/`](examples/) に架空の設定画面・指示ファイル・設定ファイルがあります。

```sh
uv run screenshot-masker annotate examples/sample.png --spec examples/annotate.yaml -c examples/article.toml
```

`examples/annotate.yaml`:

```yaml
masks:                     # 先に処理する（既存のマスクと同じぼかし・塗りつぶし）
  - {type: blur, box: [640, 120, 260, 36]}     # メールアドレス欄（架空）をぼかす
  - {type: fill, box: [640, 180, 260, 36]}     # API キー欄（架空）を塗りつぶす
annotations:               # masks の後に、書いた順に描く
  - {type: spotlight, box: [40, 100, 560, 160]}
  - {type: rect, box: [40, 100, 560, 160]}
  - {type: badge, at: [40, 100]}               # 1
  - {type: arrow, from: [420, 360], to: [300, 270]}
  - {type: label, at: [380, 365], text: "ここで「保存」を押します"}
  - {type: badge, at: [0.95, 0.9], units: ratio}   # 2（割合で指定）
```

出力（[`examples/sample-annotated.png`](examples/sample-annotated.png)）では、メール欄がぼかされ、API キー欄が黒く塗られ、カードの外側が暗くなり、カードを赤い角丸の枠が囲みます。枠の左上に「1」、右下の隅に「2」の番号バッジが付き、ラベル「ここで「保存」を押します」から保存ボタンへ矢印が伸びます。

![注釈を付けた例](examples/sample-annotated.png)

### 指示ファイルの形

| 最上位の項目 | 内容 |
| --- | --- |
| `units` | 座標の単位。`px`（既定）か `ratio`（画像の幅・高さに対する 0〜1 の割合）。各指示の `units` で個別に上書きできます |
| `scale` | 倍率。`auto`（既定）か数値。`--scale` が優先 |
| `style` | この画像だけの見た目。その場で書いたマッピングか、YAML / JSON ファイルへのパス（指示ファイルからの相対パス） |
| `masks` | 先に処理するマスク（`blur` / `fill` のみ） |
| `annotations` | 注釈。書いた順に重ねて描きます |

範囲は `box: [x, y, 幅, 高さ]`、点は `[x, y]` で書きます。

| type | 位置の項目 | 見た目の項目（既定値を上書き） |
| --- | --- | --- |
| `rect` 枠 | `box` | `color`, `width`（太さ）, `radius`（角丸） |
| `badge` 番号バッジ | `at`（中心）, `number`（省略時 1, 2, 3… と自動） | `color`, `text_color`, `radius`, `font_size`, `outline_color`, `outline_width` |
| `arrow` 矢印 | `from`, `to`（矢じり側） | `color`, `width`, `head_size`（矢じりの長さ） |
| `blur` ぼかし | `box` | `radius`（0 以上の整数） |
| `fill` 塗りつぶし | `box` | `color`（`#RRGGBB`） |
| `label` 文字ラベル | `at`（背景の左上）, `text`（`\n` で改行。日本語可） | `text_color`, `background`, `font_size`, `padding`, `radius` |
| `spotlight` スポットライト | `box`（明るく残す範囲） | `color`, `opacity`（0〜1）, `radius` |

- `blur` / `fill` は既存のマスクと同じ処理です（ぼかしはモザイクにしてからぼかし、強さが範囲の高さの半分より小さければ自動で引き上げます）
- `rect` の線は `box` の外側に描くため、囲んだ中身を隠しません
- `badge` の `number` に整数を書くと、以降の自動の番号はその続きになります
- 注釈の色は `#RRGGBB`、`#RRGGBBAA`（半透明）、`red` などの色名で書けます
- 画像からはみ出した部分は切り取って描きます。綴りの誤りなど不明な項目はエラーにします

処理の順序は「`--mask` の OCR マスク → `masks` → `annotations`」です。`masks` はファイル内で後ろに書いても先に処理します。

### 見た目の既定値（設定ファイルの `[annotate]`）

色・太さ・フォントの既定値を、マスクと同じ設定ファイル（TOML）の `[annotate]` にまとめます。記事ごとにファイルを分けて `-c` で切り替えると、見た目を揃えられます（例: [`examples/article.toml`](examples/article.toml)）。

```toml
[annotate]
reference_width = 1600                 # 倍率の基準になる画像の幅
# font = "/path/to/NotoSansCJK-Bold.ttc" # 省略時は日本語フォントを自動で探す

[annotate.rect]
color = "#E5484D"
width = 4
radius = 6

[annotate.badge]
color = "#E5484D"
text_color = "#FFFFFF"
radius = 16
font_size = 18

[annotate.arrow]
color = "#E5484D"
width = 4
head_size = 18

[annotate.label]
background = "#1F2937E6"
text_color = "#FFFFFF"
font_size = 18
padding = 8

[annotate.spotlight]
color = "#000000"
opacity = 0.55
```

`blur` の `radius` と `fill` の `color` の既定値は、`[mask]` の `blur_radius` / `fill_color` を引き継ぎます（`[annotate.blur]` / `[annotate.fill]` で別の値にもできます）。

重なり順: 組み込みの既定値 < 設定ファイル < 指示ファイルの `style` < 各指示に書いた項目

日本語のラベルには日本語フォントが要ります。Noto Sans CJK、IPA ゴシック、ヒラギノ、メイリオなどを自動で探し、見つからなければ注意を表示して既定のフォントで描きます。

### Retina（2 倍）画像の倍率

見た目の長さ（太さ・半径・文字の大きさ・矢じり）は 1 倍の画像での見た目で書き、描画時に倍率を掛けます。倍率は `画像の幅 ÷ reference_width` を四捨五入した整数（最小 1）です。`reference_width = 1600` の場合、幅 2399px 以下は 1 倍、2400〜3999px は 2 倍、4000〜5599px は 3 倍です。自動の判定が合わない画像（スマートフォンの 3 倍画像など）は `--scale 3` か、指示ファイルの `scale: 3` で指定してください。座標（`box` など）は画像の実際のピクセルで書きます。

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
