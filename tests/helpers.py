"""テスト用の補助関数。"""

from __future__ import annotations

from screenshot_masker.models import Box, Word

CHAR_WIDTH = 10
LINE_HEIGHT = 20
SPACE_WIDTH = 10


def words_from_lines(*lines: str) -> list[Word]:
    """空白区切りの文字列から、等幅フォントで並べたような Word のリストを作る。"""
    words: list[Word] = []
    for line_number, line in enumerate(lines):
        left = 0
        for token in line.split(" "):
            if token:
                width = len(token) * CHAR_WIDTH
                box = Box(left, line_number * LINE_HEIGHT * 2, width, LINE_HEIGHT)
                words.append(Word(token, box, (1, 1, line_number)))
                left += width
            left += SPACE_WIDTH
    return words
