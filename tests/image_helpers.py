"""テスト用の小さな道具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from screenshot_masker.render import RenderResult, render
from screenshot_masker.spec import parse_spec

WHITE = (255, 255, 255)


def white_image(
    width: int = 200, height: int = 100, color: tuple[int, int, int] = WHITE
) -> Image.Image:
    return Image.new("RGB", (width, height), color)


def checker_image(width: int = 200, height: int = 100, cell: int = 2) -> Image.Image:
    """ぼかすと値が大きく変わる、細かい市松模様。"""
    image = Image.new("RGB", (width, height), WHITE)
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            if (x // cell + y // cell) % 2:
                pixels[x, y] = (0, 0, 0)
    return image


def run(image: Image.Image, data: dict[str, Any], scale: float | None = None) -> RenderResult:
    return render(image, parse_spec(data, Path()), scale)


def changed_box(before: Image.Image, after: Image.Image) -> tuple[int, int, int, int] | None:
    """変化した画素を囲む範囲（left, top, right, bottom）。変化が無ければ None。"""
    return ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()


def is_close(actual: tuple[int, ...], expected: tuple[int, ...], tolerance: int = 8) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=False))


def pixel(image: Image.Image, x: int, y: int) -> tuple[int, ...]:
    value = image.getpixel((x, y))
    assert isinstance(value, tuple)
    return value
