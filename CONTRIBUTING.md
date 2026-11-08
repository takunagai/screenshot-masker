# 開発に参加する

## 開発環境

[Tesseract と uv](docs/使い方.md#1-tesseract-と-uv-を入れる) を入れてから、リポジトリを取得して依存を入れます。

```sh
git clone https://github.com/takunagai/screenshot-masker.git
cd screenshot-masker
uv sync
```

## 検査

変更したら、次の 4 つを通してください。

```sh
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

## 守ること

- テストや例には、実在のメールアドレスやトークン、実際のスクリーンショットを使わないでください
- 利用者から見える挙動（オプション・設定項目・検出する種類・出力形式・終了コード）を変えたら、README と [`docs/`](docs/) の該当ページも更新してください
- 構成・テストの書き方・壊してはいけない性質は [AGENTS.md](AGENTS.md) にあります（AI エージェントにコードを変更させるときの指示も兼ねています。Claude Code・Codex が自動で読みます）
- 公開範囲と公開前に確認したことは [docs/リポジトリの公開設定.md](docs/リポジトリの公開設定.md) にあります
