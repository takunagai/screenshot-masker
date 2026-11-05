"""検出範囲のマスク（ぼかし・塗りつぶし）と確認用画像の描画。"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFilter

from screenshot_masker.config import MaskSettings
from screenshot_masker.models import Box, Detection

# ぼかす前に、この大きさ（ピクセル）のモザイクにして元の文字を復元しにくくする
PIXELATE_BLOCK = 6
PREVIEW_COLOR = (255, 0, 0)


def normalize_mode(image: Image.Image) -> Image.Image:
    """描画しやすいよう RGB か RGBA にそろえる。"""
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    return image.convert("RGBA" if has_alpha else "RGB")


def _blur_region(image: Image.Image, box: Box, radius: int) -> None:
    region = image.crop((box.left, box.top, box.right, box.bottom))
    small = region.resize(
        (max(1, box.width // PIXELATE_BLOCK), max(1, box.height // PIXELATE_BLOCK)),
        Image.Resampling.BILINEAR,
    )
    pixelated = small.resize(region.size, Image.Resampling.NEAREST)
    effective_radius = max(radius, box.height // 2)
    image.paste(pixelated.filter(ImageFilter.GaussianBlur(effective_radius)), (box.left, box.top))


def _fill_region(image: Image.Image, box: Box, color: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.rectangle((box.left, box.top, box.right - 1, box.bottom - 1), fill=color)


def padded_boxes(
    detections: Sequence[Detection], padding: int, image_size: tuple[int, int]
) -> list[Box]:
    width, height = image_size
    boxes = [detection.box.expand(padding, width, height) for detection in detections]
    return [box for box in boxes if box.width > 0 and box.height > 0]


def apply_mask(
    image: Image.Image, detections: Sequence[Detection], settings: MaskSettings
) -> Image.Image:
    """マスクを施した新しい画像を返す（引数の画像は変更しない）。"""
    masked = normalize_mode(image).copy()
    for box in padded_boxes(detections, settings.padding, masked.size):
        if settings.method == "fill":
            _fill_region(masked, box, settings.fill_color)
        else:
            _blur_region(masked, box, settings.blur_radius)
    return masked


def draw_preview(
    image: Image.Image, detections: Sequence[Detection], settings: MaskSettings
) -> Image.Image:
    """検出範囲を枠で囲み、種類名を添えた確認用画像を返す（元の文字は残る）。"""
    preview = normalize_mode(image).convert("RGB")
    draw = ImageDraw.Draw(preview)
    line_width = max(2, min(preview.size) // 400)
    for detection in detections:
        box = detection.box.expand(settings.padding, *preview.size)
        if box.width == 0 or box.height == 0:
            continue
        draw.rectangle(
            (box.left, box.top, box.right - 1, box.bottom - 1),
            outline=PREVIEW_COLOR,
            width=line_width,
        )
        label_top = max(0, box.top - 12)
        draw.text((box.left, label_top), detection.kind, fill=PREVIEW_COLOR)
    return preview
