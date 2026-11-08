---
name: mask-screenshots
description: 公開する前のスクリーンショットから、メールアドレス・API キー・URL・IP アドレス・ホームディレクトリのパスなどの機密情報を OCR で見つけてぼかす（screenshot-masker CLI）。ブログ記事（Zenn・note など）・README・マニュアル・SNS・Issue やバグ報告・資料に画像を載せる前や、スクショを人に共有する前、「スクショの個人情報を隠して」「公開前に画像をマスクして」「スクショに API キーが写っていないか確認して」「スクショに番号や矢印を付けて」と頼まれたときに使う。screenshot-masker の出力（masked/ や *_preview/ の確認用画像）の確認・後片付けを頼まれたときも、画像を開く前に必ず使う（確認用画像にはマスク前の機密が残っている）。画像の撮影・リサイズ・形式変換だけの依頼や、PDF・動画のマスクには使わない。
---

# スクリーンショットの機密情報をマスクする

`screenshot-masker` は、画像の文字を OCR（Tesseract）で読み、機密に見える文字列の範囲をぼかして別フォルダに書き出す CLI。元画像は上書きしない。標準出力には「ファイル名・種類・位置」だけが出て、一致した文字列は出ない。

## 守ること（最優先）

- **元の画像も、`<出力先>_preview/` の確認用画像も開かない。** Read・画像の表示・OCR 結果の表示を含む。開くと、写っている機密がモデルへの入力と会話ログに残る。判断は標準出力と終了コードで足りる
- マスク済みの画像も、必要が無ければ開かない。OCR が見落とした機密はマスク済みの画像にもそのまま写っている。目で確かめるのは人間の役目
- 終了コード `1` は「検出してマスクした」という意味で、エラーではない。失敗として再実行しない
- 検出 0 件は安全の証明ではない。公開前に人間が目視するよう必ず伝える
- 確認用画像は公開用のフォルダに混ぜない。リポジトリにコミットしない
- 確認用画像や出力の削除・ツールのインストールは、ユーザーの確認を取ってから行う
- 画像を開こうとして screenshot-masker のフックに止められたら、別の方法（シェルのコマンドなど）で開こうとしない。止められた理由（種類と件数）をユーザーに伝え、マスクしてから渡すよう頼む

## 1. 使えるか確かめる

```sh
screenshot-masker --help
tesseract --list-langs
```

- `screenshot-masker` が無い、または `tesseract --list-langs` に `jpn` と `eng` が無いときは、マスクを進めずにユーザーへ導入を案内する（勝手に入れない）

  ```sh
  brew install tesseract tesseract-lang uv
  uv tool install git+https://github.com/takunagai/screenshot-masker
  ```

## 2. マスクする

入力（画像ファイルかフォルダ。png / jpg / jpeg）と、元画像と別の出力先を決めて実行する。

```sh
screenshot-masker <入力> -o <出力先> --preview
```

- フォルダを渡すと、サブフォルダの構成を保って `<出力先>/` に書き出す
- `--preview` を付けると、検出範囲を赤枠で囲んだ確認用画像を `<出力先>_preview/` に出す（人間の目視用）
- ぼかしでなく塗りつぶしにするなら `--method fill`
- 結果だけ知りたいときは `--dry-run`（画像を書かない。`--preview` とは併用できない）

標準出力は 1 件 1 行、タブ区切り: `パス<TAB>種類<TAB>x=… y=… w=… h=…`。種類は次のどれかか、設定ファイルで足した名前。

- 開発者向け: `claude`・`private_key`・`connection_string`・`url`・`email`・`aws_arn`・`ipv4`・`ipv6`・`mac_address`・`home_path`・`secret_assignment`・`token`
- 日本の個人情報・決済: `my_number`・`jp_phone`・`jp_postal_code`・`credit_card`
- 設定ファイルの `[detect] enabled` で有効にしたときだけ: `uuid`・`jp_passport`・`jp_pension`

住所・氏名は検出しない。写っていそうなら、人間の目視で確かめるよう特に伝える。

| 終了コード | 意味 | 次にすること |
| --- | --- | --- |
| 0 | 検出なし | 人間に目視を頼む（見落としがありうる） |
| 1 | 検出してマスクした | 件数と種類をユーザーに伝え、目視を頼む |
| 2 | エラー | 標準エラー出力の `エラー: …` をそのまま伝える。原因が分からなければ `--debug` |

シェルスクリプトや `set -e` の中では `screenshot-masker … || [ $? -eq 1 ]` と書くと、2 だけを失敗にできる。

## 3. 人間に確かめてもらう

ユーザーに次を伝える。

1. `<出力先>_preview/` の画像で、隠すべき文字が赤枠の外に残っていないか見てほしい
2. `<出力先>/` のマスク済み画像で、隠れていることを見てほしい
3. 確認が済んだら `<出力先>_preview/` を消してよいか（消すのはユーザーの了承を得てから）

## 4. 見落としや隠しすぎを直す

ユーザーから報告を受けたら、設定ファイル（TOML）を `-c` で渡して再実行する。

```toml
[detect]
allowed_domains = ["zenn.dev", "note.com"]   # url で残してよいドメイン（サブドメインを含む）
disabled = ["ipv4"]                          # 種類ごと検出しない
enabled = ["uuid"]                           # 既定で無効の種類（uuid・jp_passport・jp_pension）を有効にする

[[detect.custom]]                            # 決まった形の文字列を足す（Python の正規表現）
name = "project_code"
pattern = 'PRJ-\d{4}'
```

- 設定ファイルの知らない項目名や不正な値はエラー（終了コード 2）になる
- 形が決まらない見落としは、指示ファイルの `masks` で範囲を指定して隠す（座標はユーザーに聞く。画像を開いて自分で探さない）

  ```yaml
  masks:
    - {type: blur, box: [640, 120, 260, 36]}   # [x, y, 幅, 高さ]（ピクセル）
  ```

  ```sh
  screenshot-masker annotate <入力> -s masks.yaml -o <出力先>
  ```

## 5. 注釈（枠・番号・矢印など）を描くとき

`screenshot-masker annotate <入力> -s <指示ファイル> --mask -o <出力先>` で、OCR のマスクをしてから注釈を描く。指示ファイルの書き方は `screenshot-masker annotate --help` と、リポジトリのドキュメント（https://github.com/takunagai/screenshot-masker/blob/main/docs/注釈を付ける.md）を見る。座標はユーザーに聞くか、`units: ratio`（画像に対する 0〜1 の割合）で書く。
