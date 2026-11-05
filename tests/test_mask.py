from __future__ import annotations

from PIL import Image, ImageDraw

from screenshot_masker.config import MaskSettings
from screenshot_masker.mask import apply_mask, draw_preview, normalize_mode
from screenshot_masker.models import Box, Detection


def striped_image() -> Image.Image:
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 200, 4):
        draw.line((x, 0, x, 100), fill="black")
    return image


DETECTION = Detection("email", Box(50, 40, 60, 20))


def test_box_expand_is_clamped() -> None:
    assert Box(5, 5, 10, 10).expand(10, 20, 18) == Box(0, 0, 20, 18)


def test_fill_covers_padded_box_only() -> None:
    image = striped_image()
    settings = MaskSettings(method="fill", padding=4, fill_color="#ff0000")
    masked = apply_mask(image, [DETECTION], settings)
    assert masked.getpixel((46, 36)) == (255, 0, 0)
    assert masked.getpixel((113, 63)) == (255, 0, 0)
    assert masked.getpixel((45, 36)) == image.getpixel((45, 36))
    assert masked.getpixel((150, 10)) == image.getpixel((150, 10))


def test_blur_changes_region_and_keeps_outside() -> None:
    image = striped_image()
    masked = apply_mask(image, [DETECTION], MaskSettings(padding=2))
    region = (48, 38, 112, 62)
    masked_pixels = list(masked.crop(region).get_flattened_data())
    assert masked_pixels != list(image.crop(region).get_flattened_data())
    # ぼかし後は縞模様が消え、白と黒の両極端な画素がほぼ残らない
    extremes = [pixel for pixel in masked_pixels if pixel in ((0, 0, 0), (255, 255, 255))]
    assert len(extremes) < 10
    assert masked.crop((0, 0, 40, 100)).tobytes() == image.crop((0, 0, 40, 100)).tobytes()


def test_apply_mask_does_not_modify_original() -> None:
    image = striped_image()
    before = image.tobytes()
    apply_mask(image, [DETECTION], MaskSettings(method="fill"))
    assert image.tobytes() == before


def test_rgba_and_palette_images() -> None:
    rgba = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    assert apply_mask(rgba, [Detection("x", Box(0, 0, 10, 10))], MaskSettings()).mode == "RGBA"
    palette = Image.new("P", (50, 50))
    assert normalize_mode(palette).mode == "RGB"


def test_preview_draws_red_frame() -> None:
    image = Image.new("RGB", (200, 100), "white")
    preview = draw_preview(image, [DETECTION], MaskSettings(padding=0))
    assert preview.getpixel((50, 50)) == (255, 0, 0)
    assert preview.getpixel((80, 50)) == (255, 255, 255)
