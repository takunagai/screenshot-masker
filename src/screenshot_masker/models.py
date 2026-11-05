"""OCR 結果と検出結果を表すデータ型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """画像上の矩形（ピクセル単位）。"""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def union(self, other: Box) -> Box:
        left = min(self.left, other.left)
        top = min(self.top, other.top)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return Box(left, top, right - left, bottom - top)

    def expand(self, padding: int, image_width: int, image_height: int) -> Box:
        """四方に padding 広げ、画像の範囲に収める。"""
        left = max(0, self.left - padding)
        top = max(0, self.top - padding)
        right = min(image_width, self.right + padding)
        bottom = min(image_height, self.bottom + padding)
        return Box(left, top, max(0, right - left), max(0, bottom - top))


@dataclass(frozen=True)
class Word:
    """OCR が返した 1 単語。line_key が同じ単語は同じ行とみなす。"""

    text: str
    box: Box
    line_key: tuple[int, ...]


@dataclass(frozen=True)
class Detection:
    """検出結果。一致した文字列そのものは保持しない。"""

    kind: str
    box: Box
