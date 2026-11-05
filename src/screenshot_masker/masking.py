"""範囲のぼかし・塗りつぶし。マスクと注釈の両方から使う共通処理。"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from .geometry import Box

RGBA = tuple[int, int, int, int]


def blur_region(image: Image.Image, box: Box, radius: float) -> None:
    """image（RGBA）の box の範囲をガウスぼかしする。画像はその場で書き換える。"""
    bounds = box.clipped(image.width, image.height)
    if bounds is None:
        return
    region = image.crop(bounds)
    # 1 回のぼかしだと文字の輪郭が読めることがあるため、2 回かけて確実に潰す
    for _ in range(2):
        region = region.filter(ImageFilter.GaussianBlur(radius))
    image.paste(region, bounds[:2])


def fill_region(image: Image.Image, box: Box, color: RGBA) -> None:
    """image（RGBA）の box の範囲を color で塗る。半透明の色は重ねて合成する。"""
    bounds = box.clipped(image.width, image.height)
    if bounds is None:
        return
    left, top, right, bottom = bounds
    if color[3] == 255:
        ImageDraw.Draw(image).rectangle((left, top, right - 1, bottom - 1), fill=color)
        return
    layer = Image.new("RGBA", (right - left, bottom - top), color)
    image.alpha_composite(layer, (left, top))
