"""Tesseract（pytesseract 経由）で単語ごとの位置を取る。"""

from __future__ import annotations

import shutil

import pytesseract
from PIL import Image, ImageOps, ImageStat

from screenshot_masker.models import Box, Word

# 平均輝度がこれ未満の画像は暗い背景（ダークテーマ）とみなして白黒を反転する
DARK_MEAN_LUMINANCE_THRESHOLD = 128


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


def prepare_for_ocr(image: Image.Image) -> Image.Image:
    """OCR 用に、明るい背景に暗い文字のグレースケール画像へ整える。

    Tesseract は暗い背景の文字（ダークテーマ）で `_` などの細い記号を落としやすい。
    寸法は変えないので、OCR の座標は元画像の座標のまま使える。
    """
    grayscale = image.convert("L")
    if ImageStat.Stat(grayscale).mean[0] < DARK_MEAN_LUMINANCE_THRESHOLD:
        grayscale = ImageOps.invert(grayscale)
    return ImageOps.autocontrast(grayscale)


def run_ocr(image: Image.Image, lang: str) -> list[Word]:
    """画像を OCR し、空でない単語を Word のリストで返す。"""
    try:
        data = pytesseract.image_to_data(
            prepare_for_ocr(image), lang=lang, output_type=pytesseract.Output.DICT
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
