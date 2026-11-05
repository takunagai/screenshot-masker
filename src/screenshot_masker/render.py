"""注釈の描画。

線や円のふちが粗くならないよう、図形は小さな作業用レイヤーに拡大して描き、
縮小してから元画像に重ねる（スーパーサンプリング）。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from screenshot_masker.config import MaskSettings
from screenshot_masker.errors import SpecError
from screenshot_masker.geometry import Region, resolve_box, resolve_point
from screenshot_masker.mask import apply_mask, normalize_mode
from screenshot_masker.models import Detection
from screenshot_masker.spec import Operation, Spec

RGBA = tuple[int, int, int, int]
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont
ToLayer = Callable[[float, float], tuple[float, float]]
Painter = Callable[[ImageDraw.ImageDraw, ToLayer, int], None]

# 日本語を表示できるフォントの候補（上から順に探す）
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
)
# 作業用レイヤーの画素数がこの値を超えたら拡大率を下げ、メモリの使いすぎを防ぐ
MAX_LAYER_PIXELS = 16_000_000
SUPERSAMPLE = 4
ARROW_HEAD_HALF_WIDTH_RATIO = 0.6


@dataclass
class RenderContext:
    image_size: tuple[int, int]
    scale: float
    font_path: str | None
    badge_counter: int = 0
    warnings: list[str] = field(default_factory=list)


def decide_scale(image_width: int, reference_width: object, override: float | None) -> float:
    """線の太さなどに掛ける倍率。override が無ければ画像の幅から整数倍率を決める。"""
    if override is not None:
        return override
    is_number = isinstance(reference_width, int | float) and not isinstance(reference_width, bool)
    if not is_number or reference_width <= 0:  # type: ignore[operator]
        raise SpecError(f"reference_width は正の数値にしてください（指定値: {reference_width!r}）")
    # round() は 2.5 → 2 の偶数丸めになるため、0.5 を足して切り捨てる（普通の四捨五入）
    ratio = image_width / reference_width  # type: ignore[operator]
    return float(max(1, math.floor(ratio + 0.5)))


def resolve_font_path(configured: object) -> str | None:
    if configured is not None:
        if not isinstance(configured, str):
            raise SpecError("font はフォントファイルのパスを文字列で指定してください")
        path = Path(configured).expanduser()
        if not path.is_file():
            raise SpecError(f"フォントファイルが見つかりません: {configured}")
        return str(path)
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


@lru_cache(maxsize=64)
def _load_font(font_path: str | None, size: int) -> FontType:
    if font_path is None:
        return ImageFont.load_default(size)
    return ImageFont.truetype(font_path, size)


def _font(context: RenderContext, size: float) -> FontType:
    if context.font_path is None and not context.warnings:
        context.warnings.append(
            "日本語フォントが見つからないため既定のフォントで描きます。"
            "日本語が表示されない場合はスタイルの font にフォントファイルを指定してください"
        )
    return _load_font(context.font_path, max(1, round(size)))


# ---- 値の取り出し ---------------------------------------------------------


def _color(value: object, where: str, name: str) -> RGBA:
    if not isinstance(value, str):
        raise SpecError(f"{where}: {name} は '#RRGGBB' などの文字列で指定してください")
    try:
        red, green, blue, alpha = ImageColor.getcolor(value, "RGBA")  # type: ignore[misc]
    except ValueError as error:
        raise SpecError(f"{where}: {name} の色 {value!r} を解釈できません") from error
    return (red, green, blue, alpha)


def _number(value: object, where: str, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"{where}: {name} は数値で指定してください（指定値: {value!r}）")
    if value < 0 or (value == 0 and not allow_zero):
        condition = "0 以上" if allow_zero else "正の値"
        raise SpecError(f"{where}: {name} は{condition}にしてください（指定値: {value}）")
    return float(value)


def _length(
    options: dict[str, Any], name: str, op: Operation, context: RenderContext, *, allow_zero: bool
) -> float:
    return _number(options[name], op.where, name, allow_zero=allow_zero) * context.scale


def _box(op: Operation, context: RenderContext, name: str = "box") -> Region:
    return resolve_box(op.item[name], context.image_size, op.units, op.where, name)


def _point(op: Operation, context: RenderContext, name: str) -> tuple[float, float]:
    return resolve_point(op.item[name], context.image_size, op.units, op.where, name)


# ---- 合成 -----------------------------------------------------------------


def _composite(
    image: Image.Image, bounds: tuple[float, float, float, float], paint: Painter
) -> None:
    """bounds の範囲だけの作業用レイヤーを拡大して描き、縮小して image に重ねる。"""
    left, top = math.floor(bounds[0]) - 1, math.floor(bounds[1]) - 1
    right, bottom = math.ceil(bounds[2]) + 1, math.ceil(bounds[3]) + 1
    width, height = right - left, bottom - top
    clip_left, clip_top = max(0, left), max(0, top)
    clip_right, clip_bottom = min(image.width, right), min(image.height, bottom)
    if clip_right <= clip_left or clip_bottom <= clip_top:
        return

    factor = SUPERSAMPLE
    while factor > 1 and width * height * factor * factor > MAX_LAYER_PIXELS:
        factor -= 1
    layer = Image.new("RGBA", (width * factor, height * factor), (0, 0, 0, 0))

    def to_layer(x: float, y: float) -> tuple[float, float]:
        return ((x - left) * factor, (y - top) * factor)

    paint(ImageDraw.Draw(layer), to_layer, factor)
    # 透明部分の色がにじまないよう、乗算済みアルファで縮小する
    layer = layer.convert("RGBa").resize((width, height), Image.Resampling.BOX).convert("RGBA")
    layer = layer.crop((clip_left - left, clip_top - top, clip_right - left, clip_bottom - top))
    image.alpha_composite(layer, (clip_left, clip_top))


# ---- 各注釈 ---------------------------------------------------------------


def draw_rect(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """枠。線は box の外側に描き、囲んだ中身を隠さない。"""
    box = _box(op, context)
    color = _color(options["color"], op.where, "color")
    stroke = _length(options, "width", op, context, allow_zero=False)
    radius = _length(options, "radius", op, context, allow_zero=True)
    outer = (box.left - stroke, box.top - stroke, box.right + stroke, box.bottom + stroke)

    def paint(draw: ImageDraw.ImageDraw, to_layer: ToLayer, factor: int) -> None:
        x0, y0 = to_layer(outer[0], outer[1])
        x1, y1 = to_layer(outer[2], outer[3])
        draw.rounded_rectangle(
            (x0, y0, x1 - 1, y1 - 1),
            radius=(radius + stroke) * factor if radius > 0 else 0,
            outline=color,
            width=max(1, round(stroke * factor)),
        )

    _composite(image, outer, paint)


def draw_badge(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """番号バッジ。number を省くと 1, 2, 3… と自動で振る。"""
    center_x, center_y = _point(op, context, "at")
    if "number" in op.item:
        number = op.item["number"]
        if isinstance(number, bool) or not isinstance(number, int | str):
            raise SpecError(f"{op.where}: number は整数か短い文字列で指定してください")
        if isinstance(number, int):
            context.badge_counter = number
        text = str(number)
    else:
        context.badge_counter += 1
        text = str(context.badge_counter)

    color = _color(options["color"], op.where, "color")
    text_color = _color(options["text_color"], op.where, "text_color")
    outline_color = _color(options["outline_color"], op.where, "outline_color")
    radius = _length(options, "radius", op, context, allow_zero=False)
    outline = _length(options, "outline_width", op, context, allow_zero=True)
    font_size = _length(options, "font_size", op, context, allow_zero=False)
    outer_radius = radius + outline
    bounds = (
        center_x - outer_radius,
        center_y - outer_radius,
        center_x + outer_radius,
        center_y + outer_radius,
    )

    def paint(draw: ImageDraw.ImageDraw, to_layer: ToLayer, factor: int) -> None:
        cx, cy = to_layer(center_x, center_y)
        if outline > 0:
            r = outer_radius * factor
            draw.ellipse((cx - r, cy - r, cx + r - 1, cy + r - 1), fill=outline_color)
        r = radius * factor
        draw.ellipse((cx - r, cy - r, cx + r - 1, cy + r - 1), fill=color)
        font = _font(context, font_size * factor)
        draw.text((cx, cy), text, fill=text_color, font=font, anchor="mm")

    _composite(image, bounds, paint)


def draw_arrow(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """矢印。to の側に矢じりを付ける。"""
    start = _point(op, context, "from")
    end = _point(op, context, "to")
    color = _color(options["color"], op.where, "color")
    stroke = _length(options, "width", op, context, allow_zero=False)
    head = _length(options, "head_size", op, context, allow_zero=False)

    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length == 0:
        raise SpecError(f"{op.where}: from と to が同じ位置です")
    head = min(head, length)
    unit_x, unit_y = delta_x / length, delta_y / length
    normal_x, normal_y = -unit_y, unit_x
    half_width = max(head * ARROW_HEAD_HALF_WIDTH_RATIO, stroke)
    base = (end[0] - unit_x * head, end[1] - unit_y * head)
    head_points = [
        end,
        (base[0] + normal_x * half_width, base[1] + normal_y * half_width),
        (base[0] - normal_x * half_width, base[1] - normal_y * half_width),
    ]
    # 線の先端が矢じりの先からはみ出さないよう、矢じりの途中で止める
    line_end = (end[0] - unit_x * head * 0.5, end[1] - unit_y * head * 0.5)
    xs = [start[0], *(point[0] for point in head_points)]
    ys = [start[1], *(point[1] for point in head_points)]
    bounds = (min(xs) - stroke, min(ys) - stroke, max(xs) + stroke, max(ys) + stroke)

    def paint(draw: ImageDraw.ImageDraw, to_layer: ToLayer, factor: int) -> None:
        width = max(1, round(stroke * factor))
        line_start_layer = to_layer(*start)
        draw.line([line_start_layer, to_layer(*line_end)], fill=color, width=width)
        cap = stroke * factor / 2
        draw.ellipse(
            (
                line_start_layer[0] - cap,
                line_start_layer[1] - cap,
                line_start_layer[0] + cap,
                line_start_layer[1] + cap,
            ),
            fill=color,
        )
        draw.polygon([to_layer(*point) for point in head_points], fill=color)

    _composite(image, bounds, paint)


def draw_label(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """背景つきの文字。at は背景の左上。改行（\\n）で複数行にできる。"""
    left, top = _point(op, context, "at")
    text = op.item["text"]
    if not isinstance(text, str) or not text:
        raise SpecError(f"{op.where}: text は空でない文字列で指定してください")
    text_color = _color(options["text_color"], op.where, "text_color")
    background = _color(options["background"], op.where, "background")
    font_size = _length(options, "font_size", op, context, allow_zero=False)
    padding = _length(options, "padding", op, context, allow_zero=True)
    radius = _length(options, "radius", op, context, allow_zero=True)

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_box = measure.multiline_textbbox((0, 0), text, font=_font(context, font_size))
    width = text_box[2] - text_box[0] + padding * 2
    height = text_box[3] - text_box[1] + padding * 2
    bounds = (left, top, left + width, top + height)

    def paint(draw: ImageDraw.ImageDraw, to_layer: ToLayer, factor: int) -> None:
        x0, y0 = to_layer(left, top)
        x1, y1 = to_layer(left + width, top + height)
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius * factor, fill=background)
        font = _font(context, font_size * factor)
        scaled_box = draw.multiline_textbbox((0, 0), text, font=font)
        draw.multiline_text(
            (x0 + padding * factor - scaled_box[0], y0 + padding * factor - scaled_box[1]),
            text,
            fill=text_color,
            font=font,
        )

    _composite(image, bounds, paint)


def draw_spotlight(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """box の外側を暗くして、box を目立たせる。"""
    box = _box(op, context)
    red, green, blue, _ = _color(options["color"], op.where, "color")
    opacity = _number(options["opacity"], op.where, "opacity", allow_zero=True)
    if opacity > 1:
        raise SpecError(f"{op.where}: opacity は 0〜1 で指定してください（指定値: {opacity}）")
    radius = _length(options, "radius", op, context, allow_zero=True)
    dim_alpha = round(255 * opacity)

    alpha = Image.new("L", image.size, dim_alpha)
    # 穴の部分だけを拡大して描き、ふちを滑らかにする
    margin = 2
    left = max(0, math.floor(box.left) - margin)
    top = max(0, math.floor(box.top) - margin)
    right = min(image.width, math.ceil(box.right) + margin)
    bottom = min(image.height, math.ceil(box.bottom) + margin)
    if right > left and bottom > top:
        factor = SUPERSAMPLE
        while factor > 1 and (right - left) * (bottom - top) * factor * factor > MAX_LAYER_PIXELS:
            factor -= 1
        hole = Image.new("L", ((right - left) * factor, (bottom - top) * factor), dim_alpha)
        ImageDraw.Draw(hole).rounded_rectangle(
            (
                (box.left - left) * factor,
                (box.top - top) * factor,
                (box.right - left) * factor - 1,
                (box.bottom - top) * factor - 1,
            ),
            radius=radius * factor,
            fill=0,
        )
        alpha.paste(hole.resize((right - left, bottom - top), Image.Resampling.BOX), (left, top))
    overlay = Image.new("RGBA", image.size, (red, green, blue, 0))
    overlay.putalpha(alpha)
    image.alpha_composite(overlay)


def _apply_existing_mask(
    image: Image.Image, op: Operation, context: RenderContext, settings: MaskSettings
) -> None:
    """既存のマスク処理（mask.apply_mask）を box の範囲にかけ、結果を image に戻す。"""
    box = _box(op, context).to_mask_box(image.width, image.height)
    if box is None:
        return
    masked = apply_mask(image, [Detection(op.kind, box)], settings)
    bounds = (box.left, box.top, box.right, box.bottom)
    image.paste(masked.crop(bounds), bounds[:2])


def apply_blur(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    """ぼかし。OCR マスクと同じく、モザイクにしてからぼかす。

    強さは OCR マスクと同じ扱い（倍率は掛けず、範囲の高さの半分より小さければ自動で引き上げ）。
    """
    radius = options["radius"]
    if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
        raise SpecError(
            f"{op.where}: radius は 0 以上の整数で指定してください（指定値: {radius!r}）"
        )
    _apply_existing_mask(
        image, op, context, MaskSettings(method="blur", padding=0, blur_radius=radius)
    )


def apply_fill(
    image: Image.Image, op: Operation, options: dict[str, Any], context: RenderContext
) -> None:
    color = options["color"]
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise SpecError(
            f'{op.where}: color は "#RRGGBB" 形式で指定してください（指定値: {color!r}）'
        )
    _apply_existing_mask(
        image, op, context, MaskSettings(method="fill", padding=0, fill_color=color)
    )


Renderer = Callable[[Image.Image, Operation, dict[str, Any], RenderContext], None]
RENDERERS: dict[str, Renderer] = {
    "rect": draw_rect,
    "badge": draw_badge,
    "arrow": draw_arrow,
    "label": draw_label,
    "spotlight": draw_spotlight,
    "blur": apply_blur,
    "fill": apply_fill,
}


@dataclass
class RenderResult:
    image: Image.Image
    scale: float
    warnings: list[str]


def render(source: Image.Image, spec: Spec, scale_override: float | None = None) -> RenderResult:
    """source を変更せず、指示ファイルの masks → annotations の順に処理した新しい画像を返す。"""
    output_mode = normalize_mode(source).mode
    image = source.convert("RGBA")
    scale_value = scale_override if scale_override is not None else spec.scale
    context = RenderContext(
        image_size=image.size,
        scale=decide_scale(image.width, spec.style["reference_width"], scale_value),
        font_path=resolve_font_path(spec.style["font"]),
    )
    for op in spec.operations:
        options = {
            **spec.style[op.kind],
            **{k: v for k, v in op.item.items() if k in spec.style[op.kind]},
        }
        RENDERERS[op.kind](image, op, options, context)
    output = image.convert(output_mode)
    return RenderResult(image=output, scale=context.scale, warnings=context.warnings)
