"""OCR 前処理のテスト（Tesseract 不要）。"""

from __future__ import annotations

from PIL import Image

from screenshot_masker.ocr import prepare_for_ocr


def luminance(image: Image.Image, xy: tuple[int, int]) -> int:
    """グレースケール画像の 1 画素の輝度を返す。"""
    value = image.getpixel(xy)
    assert isinstance(value, int)
    return value


def test_dark_background_is_inverted_to_light() -> None:
    image = Image.new("RGB", (40, 20), "#1e1e1e")
    image.paste((221, 221, 221), (10, 5, 20, 15))

    prepared = prepare_for_ocr(image)

    assert prepared.mode == "L"
    # autocontrast の丸めで 255 / 0 ちょうどにはならないため幅を持たせる
    assert luminance(prepared, (0, 0)) >= 250  # 背景は白
    assert luminance(prepared, (15, 10)) <= 5  # 文字は黒


def test_light_background_is_not_inverted() -> None:
    image = Image.new("RGB", (40, 20), "white")
    image.paste((0, 0, 0), (10, 5, 20, 15))

    prepared = prepare_for_ocr(image)

    assert luminance(prepared, (0, 0)) >= 250
    assert luminance(prepared, (15, 10)) <= 5


def test_size_is_unchanged() -> None:
    image = Image.new("RGBA", (123, 45), (30, 30, 30, 255))

    assert prepare_for_ocr(image).size == (123, 45)
