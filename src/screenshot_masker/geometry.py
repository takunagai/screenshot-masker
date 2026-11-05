"""座標の解決（ピクセル指定と、画像に対する割合指定）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import SpecError

Units = Literal["px", "ratio"]
VALID_UNITS: tuple[Units, ...] = ("px", "ratio")


@dataclass(frozen=True)
class Box:
    """画像上の矩形（ピクセル単位、右端・下端は含まない）。"""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def to_int(self) -> tuple[int, int, int, int]:
        return (round(self.left), round(self.top), round(self.right), round(self.bottom))

    def clipped(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """画像の範囲に収めた整数座標。画像と重ならなければ None。"""
        left, top, right, bottom = self.to_int()
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)


def parse_units(value: object, where: str) -> Units:
    if value == "px":
        return "px"
    if value == "ratio":
        return "ratio"
    raise SpecError(f"{where}: units は px か ratio を指定してください（指定値: {value!r}）")


def _numbers(value: object, count: int, where: str, name: str) -> list[float]:
    is_sequence = isinstance(value, list | tuple)
    if not is_sequence or len(value) != count:  # type: ignore[arg-type]
        raise SpecError(f"{where}: {name} は {count} 個の数値の配列で指定してください")
    numbers: list[float] = []
    for item in value:  # type: ignore[union-attr]
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise SpecError(f"{where}: {name} に数値以外が含まれています（{item!r}）")
        numbers.append(float(item))
    return numbers


def _check_ratio(numbers: list[float], where: str, name: str) -> None:
    for number in numbers:
        if not 0.0 <= number <= 1.0:
            raise SpecError(f"{where}: units: ratio のとき {name} の値は 0〜1 です（{number}）")


def resolve_point(
    value: object, image_size: tuple[int, int], units: Units, where: str, name: str
) -> tuple[float, float]:
    """[x, y] をピクセル座標にする。"""
    x, y = _numbers(value, 2, where, name)
    if units == "ratio":
        _check_ratio([x, y], where, name)
        return (x * image_size[0], y * image_size[1])
    return (x, y)


def resolve_box(
    value: object, image_size: tuple[int, int], units: Units, where: str, name: str = "box"
) -> Box:
    """[x, y, width, height] をピクセルの Box にする。"""
    x, y, width, height = _numbers(value, 4, where, name)
    if width <= 0 or height <= 0:
        raise SpecError(f"{where}: {name} の幅と高さは正の値にしてください")
    if units == "ratio":
        _check_ratio([x, y, width, height], where, name)
        image_width, image_height = image_size
        x, width = x * image_width, width * image_width
        y, height = y * image_height, height * image_height
    return Box(left=x, top=y, right=x + width, bottom=y + height)
