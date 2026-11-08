# screenshot-masker

ブログ記事（Zenn・note など）に載せるスクリーンショットから、公開してはいけない文字列（メールアドレス・API キー・URL・ホームディレクトリのパスなど）を OCR で見つけてぼかす CLI です。注釈（枠・番号バッジ・矢印など）を描き込む `annotate` サブコマンドもあります。

- **見つけた機密を、どこにも書き残しません。** 画面に出すのはファイル名・種類・位置だけで、一致した文字列は表示しません。ログファイルも作りません
- 元画像は上書きしません。マスク済み画像は別フォルダに書き出します（出力先が元画像と重なる指定はエラーで止まります）
- 書き出す画像は再エンコードされるため、EXIF などのメタデータは引き継がれません

機密が残りうる場所は、次の 2 つだけです。どちらもお使いのパソコンの中だけで、外部に送られることはありません（文字の読み取りもパソコンの中で行い、インターネットには接続しません）。

- **確認用画像（`--preview` を付けたときだけ作られます）** ─ 見落としを確かめるために、わざとマスク前の文字を残した画像です。マスク済みの画像とは別のフォルダ（`<出力先>_preview/`）に出すので混ざりません。確認が済んだら消してください
- **文字を読み取るときの一時ファイル** ─ 読み取りのあいだだけパソコンの一時フォルダに作られ、1 枚終わるごとに自動で消えます。途中で Ctrl+C で止めた場合も消えます。残るのは、強制終了や電源断で処理が急に切れたときだけです。気になる場合は、一時フォルダ（`$TMPDIR`）の `tess_` で始まるファイルを消してください

> [!IMPORTANT]
> OCR は文字を見落とすことがあります。検出が 0 件でも安全とは限りません。公開する前に、必ず人の目で確認してください（[公開までの流れ](#公開までの流れ)）。

## 目次

- [必要なもの](#必要なもの)
- [導入](#導入)
- [公開までの流れ](#公開までの流れ)
- [使い方](#使い方)
- [検出する種類](#検出する種類)
- [設定ファイル](#設定ファイル)
- [注釈を付ける（annotate）](#注釈を付けるannotate)
- [AI エージェントから使う](#ai-エージェントから使う)
- [困ったとき](#困ったとき)
- [限界](#限界)
- [開発](#開発)
- [ライセンス](#ライセンス)

## 必要なもの

- macOS（動作確認済みの環境）。他の OS でも Tesseract と日本語の言語データがあれば動く想定ですが、確認していません
- [Homebrew](https://brew.sh/)
- Git
- Python 3.12 以上（手元に無ければ、`uv` が `.python-version` に従って自動で用意します）

## 導入

### 1. Tesseract と uv を入れる

```sh
brew install tesseract tesseract-lang uv
```

`tesseract-lang` は日本語（`jpn`）などの言語データです。入ったかどうかは次のコマンドで確かめます。一覧に `jpn` と `eng` があれば準備できています。

```sh
tesseract --list-langs
```

### 2. リポジトリを取得して依存を入れる

```sh
git clone https://github.com/takunagai/screenshot-masker.git
cd screenshot-masker
uv sync
```
### 3. 動作を確かめる

架空の設定画面の画像（[`examples/sample.png`](examples/sample.png)）で、画像を書き出さずに検出だけを試します。

```sh
uv run screenshot-masker examples/sample.png --dry-run
```

次のように 2 件（架空のメールアドレスと API キー）が表示されれば成功です。数値は環境によって少しずれることがあります。このとき終了コードは `1`（検出あり）になりますが、エラーではありません（[終了コード](#終了コード)）。

```
examples/sample.png	email	x=641 y=129 w=177 h=19
examples/sample.png	token	x=641 y=189 w=179 h=15
1 ファイル中 1 ファイルで 2 件検出
```

### コマンドとして入れる（任意）

`uv run` を付けずに `screenshot-masker` と打てるようにします。以降の例の `uv run screenshot-masker` は `screenshot-masker` に読み替えてください。

```sh
# クローンしたフォルダで
uv tool install .

# クローンせずに入れる場合
uv tool install git+https://github.com/takunagai/screenshot-masker
```

| 操作 | コマンド |
| --- | --- |
| 更新（クローンした場合は先に `git pull`） | `uv tool install --reinstall .` または `uv tool install --reinstall git+https://github.com/takunagai/screenshot-masker` |
| 削除 | `uv tool uninstall screenshot-masker` |

## 公開までの流れ

初めて使うときは、この順に進めると見落としを防げます。

1. **何が見つかるか確かめる。** 画像は書き出さず、検出結果だけを見ます

   ```sh
   uv run screenshot-masker ~/Desktop/screenshots --dry-run
   ```

2. **見落としを目で確かめる。** 検出した範囲を赤枠で囲んだ確認用画像を出し、隠すべき文字が枠の外に残っていないかを見ます。確認用画像は `<出力先>_preview/`（この例では `~/Desktop/masked_preview/`）に出ます

   ```sh
   uv run screenshot-masker ~/Desktop/screenshots -o ~/Desktop/masked --preview
   ```

3. **見落としがあれば足す。** 決まった形の文字列なら設定ファイルの `[[detect.custom]]` に正規表現を足して 2 からやり直します（[設定ファイル](#設定ファイル)）。形が決まらないものは、指示ファイルの `masks` で範囲を指定して隠します（[注釈を付ける](#注釈を付けるannotate)）
4. **マスク済み画像を確かめる。** 出力先（この例では `~/Desktop/masked/`）の画像を開き、隠れていることを目で確かめます
5. **確認用画像を消す。** `<出力先>_preview/` をゴミ箱に入れます。マスク前の文字が残っているため、公開用のフォルダに混ぜたり、記事のリポジトリにコミットしたりしないでください

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

対応する画像は PNG と JPEG（`.png` / `.jpg` / `.jpeg`）です。フォルダを指定したときは、出力先と確認用のフォルダを除いた中の画像をすべて処理します。

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
| 1 | 検出あり（マスクした。エラーではない） |
| 2 | エラー（入力が無い、設定が不正、Tesseract が無い、画像が読めない など） |

複数の画像のうち一部だけ読めなかった場合も、残りは処理したうえで 2 を返します。

シェルスクリプトや `set -e` の中で使うと、検出あり（1）で止まってしまいます。2 だけを失敗として扱うには次のように書きます。

```sh
uv run screenshot-masker shots -o masked || [ $? -eq 1 ]
```

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

`-c` で指定するか、次の順に探した最初のファイルを使います（見つからなければ既定値で動きます）。

1. カレントディレクトリの `screenshot-masker.toml`
2. `~/.config/screenshot-masker/config.toml`

例は [`screenshot-masker.example.toml`](screenshot-masker.example.toml) を参照してください。コピーして使うのが手早い方法です。

```sh
cp screenshot-masker.example.toml screenshot-masker.toml
```

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

- `allowed_domains` は `url` にだけ効きます。`claude.ai/code` の URL は `claude` として別に検出されるため、`claude.ai` を許可しても隠れます（残したい場合は `disabled = ["claude"]`）
- `[[detect.custom]]` の `pattern` は Python の正規表現です。TOML ではシングルクォートで囲むと `\` をそのまま書けます
- 知らない項目名や不正な値（`method` の綴り、色の形式、負の数など）はエラーで止まります（綴りの誤りで設定が効かないまま進むのを防ぐため）

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

OCR が見落とした箇所を手で隠すだけなら、`masks` だけを書いた指示ファイルでも使えます（`annotations` は省略できます）。

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

## AI エージェントから使う

Claude Code や Codex などの AI エージェントにスクリーンショットの処理を任せるときは、エージェントが**マスク前の画像を見ない**ようにしてください。エージェントが画像を開くと、写っている機密情報がモデルへの入力と会話ログに残ります。

- 結果の判断は、標準出力（種類と位置だけ）と終了コードで足ります。画像を開く必要はありません
- 終了コード `1` は「検出してマスクした」という意味です。失敗として再実行させないでください
- 画像を目で確かめるのは人間の役目です。マスク済みの画像でも、OCR が見落とした機密はそのまま写っているため、エージェントには必要が無い限り開かせないでください

### スキルを入れる（おすすめ）

この使い方をエージェントに教えるスキル（[`skills/mask-screenshots/SKILL.md`](skills/mask-screenshots/SKILL.md)）を同梱しています。入れておくと、「記事に載せるスクショの個人情報を隠して」のような依頼で自動的に読み込まれ、上の規律に沿って処理します。ツール本体（[導入](#導入)）とは別に入れてください。

**Claude Code**（プラグインとして配布しています。ターミナルで実行）

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
**Codex**（スキルのフォルダを `~/.agents/skills/` に置く）

```sh
git clone https://github.com/takunagai/screenshot-masker.git
mkdir -p ~/.agents/skills
cp -R screenshot-masker/skills/mask-screenshots ~/.agents/skills/
```

スキルが認識されない場合は Codex を再起動してください。更新するときは、`git pull` してから同じ `cp` をやり直します。

### スキルを使わない場合

記事を書くリポジトリなど、このツールを使う側の指示ファイル（`AGENTS.md` / `CLAUDE.md`）に、次のように書いておくと伝わります。

```markdown
## スクリーンショットのマスク（screenshot-masker）

- 公開する画像は `screenshot-masker <画像またはフォルダ> -o <出力先>` でマスクしてから使う
- マスク前の画像と `*_preview/` の画像は開かない。結果は標準出力（種類・位置）と終了コードで判断する
- 終了コード: 0 検出なし / 1 検出してマスクした（エラーではない）/ 2 エラー
- 検出 0 件でも安全とは限らない。公開前に人間が目視で確認する
```

Claude Code では、設定ファイルで確認用画像の読み取りを禁止できます。このリポジトリでは [`.claude/settings.json`](.claude/settings.json) で設定済みです。ほかのリポジトリでも同じ制限を掛けるには、そのリポジトリの `.claude/settings.json` に次を加えます。

```json
{
  "permissions": {
    "deny": ["Read(//**/*_preview/**)"]
  }
}
```

この設定は Claude Code にだけ効き、スクリプト経由の読み取りなど防げない経路もあります。効く範囲と確認結果は [docs/AIエージェントの読み取り制限.md](docs/AIエージェントの読み取り制限.md) にまとめています。

このリポジトリのコードをエージェントに変更させるときの指示は [AGENTS.md](AGENTS.md) にあります（Claude Code・Codex が自動で読みます）。

## 困ったとき

| 症状 | 対処 |
| --- | --- |
| `エラー: Tesseract が見つかりません` | `brew install tesseract tesseract-lang` で入れます |
| `エラー: Tesseract の実行に失敗しました（言語データ … が入っているか確認してください）` | `tesseract --list-langs` に `jpn` と `eng` があるか確かめます。無ければ `brew install tesseract-lang`。設定ファイルの `[ocr] lang` の綴りも確かめます |
| `エラー: 出力先が元画像と同じになるため中止しました` | `-o` で元画像と別のフォルダを指定します |
| `エラー: 処理できる画像（png / jpg）がありません` | 入力のパスと拡張子を確かめます。対応は `.png` / `.jpg` / `.jpeg` だけです |
| 隠したい文字が検出されない | `--preview` で確かめ、形が決まっていれば `[[detect.custom]]` に正規表現を足します。形が決まらなければ annotate の `masks` で範囲を指定して隠します |
| 隠さなくてよいものまで隠れる | `url` なら `allowed_domains` に残してよいドメインを足します。種類ごと不要なら `disabled` に書きます |
| `注意: 日本語フォントが見つからないため…` | 設定ファイルの `[annotate]` の `font` に、日本語フォントのファイルのパスを書きます |
| スクリプトが検出ありで止まる | 終了コード 1 は検出ありの意味です（[終了コード](#終了コード)） |
| 原因が分からないエラー | `--debug` を付けて実行すると詳細が表示されます |

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

同梱のスキルは、Claude Code のプラグインの eval で確かめます（実行のたびにモデルを呼ぶため、プランの利用枠か API の料金を消費します）。

```sh
claude plugin validate .
claude plugin eval . --trust-plugin --no-publish
```

構成・テストの書き方・壊してはいけない性質は [AGENTS.md](AGENTS.md) を、公開範囲と公開前に確認したことは [docs/リポジトリの公開設定.md](docs/リポジトリの公開設定.md) を参照してください。テストや例には、実在のメールアドレスやトークン、実際のスクリーンショットを使わないでください。

## ライセンス

[Apache License 2.0](LICENSE) で公開しています。Copyright 2026 Taku Nagai

OCR には別途インストールする [Tesseract](https://github.com/tesseract-ocr/tesseract)（Apache License 2.0）を使います。
