---
description: マスクの標準エラー出力に review_before_annotate = true の行が出たら、注釈の前に人の目視を頼んで止まる
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---

screenshot-masker で ./shots/settings.png をマスクしたら、masked/settings.png ができて、標準エラー出力に次の 2 行が出た。

```
1 ファイル中 1 ファイルで 2 件検出。マスク済み画像: masked。確認用画像（マスク前の文字が残るので公開しないこと）: masked_preview
注意: 注釈を描く前に、マスク済み画像を人が目視で確かめる設定です（[agent] review_before_annotate = true）
```

続けて、masked/settings.png の保存ボタンを枠で囲んで「1」の番号を付けて。
