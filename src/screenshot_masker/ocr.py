"""Tesseract（pytesseract 経由）で単語ごとの位置を取る。"""

from __future__ import annotations

import shutil

import pytesseract
from PIL import Image

from screenshot_masker.models import Box, Word


class OcrUnavailableError(Exception):
    """Tesseract が使えないとき。メッセージは利用者向け。"""


def is_tesseract_available(lang: str = "jpn+eng") -> bool:
    """Tesseract 本体と、指定した言語データがそろっていれば True。"""
    if shutil.which("tesseract") is None:
        return False
    try:
        installed = set(pytesseract.get_languages(config=""))
    except pytesseract.TesseractError:
        return False
    return set(lang.split("+")) <= installed


def run_ocr(image: Image.Image, lang: str) -> list[Word]:
    """画像を OCR し、空でない単語を Word のリストで返す。"""
    try:
        data = pytesseract.image_to_data(
            image.convert("RGB"), lang=lang, output_type=pytesseract.Output.DICT
        )
    except pytesseract.TesseractNotFoundError as error:
        raise OcrUnavailableError(
            "Tesseract が見つかりません。macOS では `brew install tesseract tesseract-lang` "
            "で導入してください"
        ) from error
    except pytesseract.TesseractError as error:
        raise OcrUnavailableError(
            f"Tesseract の実行に失敗しました（言語データ {lang} が入っているか確認してください）"
        ) from error

    words: list[Word] = []
    for index, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        box = Box(
            int(data["left"][index]),
            int(data["top"][index]),
            int(data["width"][index]),
            int(data["height"][index]),
        )
        line_key = (
            int(data["page_num"][index]),
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        words.append(Word(str(text), box, line_key))
    return words
