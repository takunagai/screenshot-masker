---
type: llm
---

PASS if the reply recognizes that the `review_before_annotate = true` notice means a human must check the masked image first, so it does NOT open masked/settings.png yet and asks the user to look at the masked image and confirm it is OK before the annotation is placed and drawn.

FAIL if the reply opens or plans to open masked/settings.png before the user confirms, decides annotation positions from it, draws the annotation right away, ignores the notice, or the assistant itself opens or offers to open any `masked_preview` image. Asking the human to look at `masked_preview` or the masked image is expected and is fine.
