"""描画結果を、特定の画素の色と変化した範囲で確かめる。"""

from __future__ import annotations

import pytest
from helpers import WHITE, changed_box, checker_image, is_close, pixel, run, white_image
from PIL import Image

from screenshot_masker.errors import SpecError
from screenshot_masker.render import decide_scale

RED = (229, 72, 77)


def test_source_image_is_not_modified() -> None:
    source = white_image()
    before = source.copy()
    run(source, {"annotations": [{"type": "rect", "box": [10, 10, 50, 30]}]})
    assert changed_box(before, source) is None


def test_rect_draws_outside_the_box_and_keeps_inside() -> None:
    source = white_image()
    result = run(source, {"annotations": [{"type": "rect", "box": [50, 30, 80, 40], "radius": 0}]})
    # 既定の太さ 4: 線は box の外側 46〜49 に乗る
    assert is_close(pixel(result.image, 47, 50), RED)
    assert pixel(result.image, 52, 50) == WHITE  # box の内側は変えない
    assert pixel(result.image, 70, 50) == WHITE
    assert changed_box(source, result.image) == (46, 26, 134, 74)


def test_rect_color_and_width_can_be_overridden_per_item() -> None:
    result = run(
        white_image(),
        {
            "annotations": [
                {"type": "rect", "box": [50, 30, 80, 40], "color": "#00FF00", "width": 8}
            ]
        },
    )
    assert is_close(pixel(result.image, 44, 50), (0, 255, 0))


def test_ratio_and_pixel_coordinates_give_the_same_result() -> None:
    source = white_image(200, 100)
    by_pixel = run(source, {"annotations": [{"type": "rect", "box": [20, 10, 100, 50]}]})
    by_ratio = run(
        source,
        {"units": "ratio", "annotations": [{"type": "rect", "box": [0.1, 0.1, 0.5, 0.5]}]},
    )
    assert changed_box(by_pixel.image, by_ratio.image) is None


def test_units_can_be_set_per_item() -> None:
    source = white_image(200, 100)
    result = run(source, {"annotations": [{"type": "badge", "at": [0.5, 0.5], "units": "ratio"}]})
    # 中心 (100, 50)、半径 16（白いふちは白背景では変化に出ない）
    assert changed_box(source, result.image) == (84, 34, 116, 66)


def test_badge_is_centered_and_numbered_automatically() -> None:
    source = white_image(300, 100, color=(0, 0, 0))
    result = run(
        source,
        {
            "annotations": [
                {"type": "badge", "at": [50, 50]},
                {"type": "badge", "at": [150, 50]},
            ]
        },
    )
    # 既定の半径 16 + ふち 2 = 18
    assert changed_box(source, result.image) == (32, 32, 168, 68)
    # 円の内側（数字にかからない位置）はバッジの色
    assert is_close(pixel(result.image, 50, 38), RED)
    assert is_close(pixel(result.image, 50 - 17, 50), WHITE)  # ふちは白
    assert pixel(result.image, 50 - 19, 50) == (0, 0, 0)


def test_badge_numbers_continue_from_explicit_number() -> None:
    base = {"annotations": [{"type": "badge", "at": [50, 50], "number": 5}]}
    explicit_six = run(
        white_image(), {"annotations": [{"type": "badge", "at": [50, 50], "number": 6}]}
    )
    auto_after_five = run(
        white_image(),
        {
            "annotations": [
                *base["annotations"],
                {"type": "fill", "box": [0, 0, 200, 100], "color": "#FFFFFF"},
                {"type": "badge", "at": [50, 50]},
            ]
        },
    )
    assert changed_box(explicit_six.image, auto_after_five.image) is None


def test_arrow_head_is_at_the_end_point() -> None:
    source = white_image(200, 100)
    result = run(source, {"annotations": [{"type": "arrow", "from": [20, 50], "to": [180, 50]}]})
    assert is_close(pixel(result.image, 100, 50), RED)  # 線の途中
    assert is_close(pixel(result.image, 165, 56), RED)  # 矢じりは線より太い
    assert pixel(result.image, 100, 56) == WHITE
    assert pixel(result.image, 185, 50) == WHITE  # 終点より先には描かない
    box = changed_box(source, result.image)
    assert box is not None
    assert box[2] <= 181


def test_arrow_with_same_points_is_an_error() -> None:
    with pytest.raises(SpecError, match="同じ位置"):
        run(white_image(), {"annotations": [{"type": "arrow", "from": [5, 5], "to": [5, 5]}]})


def test_label_draws_background_with_text() -> None:
    source = white_image(300, 100)
    result = run(
        source,
        {
            "annotations": [
                {
                    "type": "label",
                    "at": [20, 20],
                    "text": "保存を押す",
                    "background": "#0000FF",
                    "radius": 0,
                }
            ]
        },
    )
    box = changed_box(source, result.image)
    assert box is not None
    left, top, right, bottom = box
    assert (left, top) == (20, 20)
    assert right > 60  # 5 文字ぶんの幅がある
    assert is_close(pixel(result.image, 22, 22), (0, 0, 255))  # 余白は背景色
    # 文字の色（白）の画素が背景の中にある
    colors = {pixel(result.image, x, y)[:3] for x in range(left, right) for y in range(top, bottom)}
    assert any(is_close(color, WHITE, tolerance=20) for color in colors)


def test_spotlight_dims_outside_only() -> None:
    source = white_image(200, 100)
    result = run(
        source,
        {
            "annotations": [
                {"type": "spotlight", "box": [50, 25, 100, 50], "opacity": 0.5, "radius": 0}
            ]
        },
    )
    assert is_close(pixel(result.image, 10, 10), (127, 127, 127), tolerance=2)
    assert pixel(result.image, 100, 50) == WHITE
    assert pixel(result.image, 51, 26) == WHITE


def test_blur_changes_only_the_region() -> None:
    source = checker_image(200, 100)
    result = run(source, {"annotations": [{"type": "blur", "box": [50, 20, 60, 40]}]})
    assert changed_box(source, result.image) == (50, 20, 110, 60)
    # 市松模様がならされて中間の灰色になる
    red, green, blue = pixel(result.image, 80, 40)[:3]
    assert 60 < red < 200 and red == green == blue


def test_fill_paints_region_with_color() -> None:
    source = white_image()
    result = run(source, {"masks": [{"type": "fill", "box": [10, 10, 20, 20], "color": "#000000"}]})
    assert pixel(result.image, 15, 15) == (0, 0, 0)
    assert changed_box(source, result.image) == (10, 10, 30, 30)


def test_masks_are_applied_before_annotations() -> None:
    """masks を後ろに書いても、注釈を塗りつぶさない（マスク → 注釈の順）。"""
    data = {
        "annotations": [{"type": "rect", "box": [20, 20, 40, 40], "radius": 0}],
        "masks": [{"type": "fill", "box": [0, 0, 100, 100], "color": "#000000"}],
    }
    result = run(white_image(), data)
    assert is_close(pixel(result.image, 17, 40), RED)


def test_masks_section_accepts_only_blur_and_fill() -> None:
    with pytest.raises(SpecError, match="masks"):
        run(white_image(), {"masks": [{"type": "rect", "box": [0, 0, 10, 10]}]})


def test_retina_image_doubles_line_width() -> None:
    """同じ割合の指示なら、2 倍の画像は 2 倍の太さで描かれ、縮小すると 1 倍とほぼ同じになる。"""
    data = {
        "units": "ratio",
        "annotations": [{"type": "rect", "box": [0.25, 0.25, 0.5, 0.5], "radius": 0}],
    }
    normal = run(Image.new("RGB", (1600, 800), WHITE), data)
    retina = run(Image.new("RGB", (3200, 1600), WHITE), data)
    assert (normal.scale, retina.scale) == (1, 2)
    # 1 倍: 線は x=396〜399、2 倍: x=792〜799
    assert is_close(pixel(normal.image, 396, 600), RED)
    assert pixel(normal.image, 395, 600) == WHITE
    assert is_close(pixel(retina.image, 792, 1200), RED)
    assert pixel(retina.image, 791, 1200) == WHITE


def test_scale_override_takes_priority() -> None:
    data = {"scale": 3, "annotations": [{"type": "rect", "box": [50, 30, 80, 40], "radius": 0}]}
    assert run(white_image(), data).scale == 3
    assert run(white_image(), data, scale=1.5).scale == 1.5


def test_alpha_channel_is_kept_only_when_source_has_one() -> None:
    data = {"annotations": [{"type": "rect", "box": [10, 10, 20, 20]}]}
    assert run(white_image(), data).image.mode == "RGB"
    assert run(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), data).image.mode == "RGBA"


def test_shapes_partly_outside_the_image_are_clipped() -> None:
    source = white_image(100, 100)
    result = run(
        source,
        {
            "annotations": [
                {"type": "badge", "at": [0, 0]},
                {"type": "rect", "box": [80, 80, 50, 50]},
                {"type": "spotlight", "box": [-10, -10, 30, 30]},
            ]
        },
    )
    assert result.image.size == (100, 100)


@pytest.mark.parametrize(
    ("width", "expected"),
    [(640, 1), (1920, 1), (2399, 1), (2400, 2), (2880, 2), (3999, 2), (4000, 3)],
)
def test_auto_scale_is_decided_from_image_width(width: int, expected: float) -> None:
    assert decide_scale(width, 1600, None) == expected


def test_reference_width_must_be_positive() -> None:
    with pytest.raises(SpecError, match="reference_width"):
        decide_scale(1000, 0, None)
