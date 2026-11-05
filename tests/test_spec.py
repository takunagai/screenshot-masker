"""指示ファイル・スタイル設定の読み込みと検査。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screenshot_masker.errors import SpecError
from screenshot_masker.geometry import resolve_box
from screenshot_masker.spec import load_spec, parse_spec
from screenshot_masker.style import DEFAULT_STYLE, load_style_file


def test_yaml_and_json_give_the_same_spec(tmp_path: Path) -> None:
    data = {"units": "ratio", "annotations": [{"type": "rect", "box": [0.1, 0.1, 0.2, 0.2]}]}
    (tmp_path / "spec.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "spec.yaml").write_text(
        "units: ratio\nannotations:\n  - {type: rect, box: [0.1, 0.1, 0.2, 0.2]}\n",
        encoding="utf-8",
    )
    from_json = load_spec(tmp_path / "spec.json")
    from_yaml = load_spec(tmp_path / "spec.yaml")
    assert from_json == from_yaml


def test_style_layers_default_then_cli_then_spec_then_item(tmp_path: Path) -> None:
    (tmp_path / "article.yaml").write_text(
        "rect: {color: '#111111', width: 6}\nbadge: {radius: 20}\n", encoding="utf-8"
    )
    base = load_style_file(tmp_path / "article.yaml", DEFAULT_STYLE)
    spec = parse_spec(
        {"style": {"rect": {"width": 8}}, "annotations": [{"type": "rect", "box": [0, 0, 1, 1]}]},
        tmp_path,
        base,
    )
    assert spec.style["rect"] == {"color": "#111111", "width": 8, "radius": 6}
    assert spec.style["badge"]["radius"] == 20
    assert DEFAULT_STYLE["rect"]["width"] == 4  # 既定値は書き換えない


def test_style_path_in_spec_is_relative_to_spec_file(tmp_path: Path) -> None:
    (tmp_path / "styles").mkdir()
    (tmp_path / "styles" / "s.yaml").write_text("arrow: {head_size: 30}\n", encoding="utf-8")
    (tmp_path / "spec.yaml").write_text(
        "style: styles/s.yaml\nannotations:\n  - {type: arrow, from: [0, 0], to: [9, 9]}\n",
        encoding="utf-8",
    )
    assert load_spec(tmp_path / "spec.yaml").style["arrow"]["head_size"] == 30


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "最上位"),
        ({"annotation": []}, "不明な項目 annotation"),
        ({}, "annotations も masks もありません"),
        ({"annotations": [{"type": "circle"}]}, "type は"),
        ({"annotations": [{"type": "rect"}]}, "必須の項目 box"),
        (
            {"annotations": [{"type": "rect", "box": [0, 0, 1, 1], "colour": "red"}]},
            "不明な項目 colour",
        ),
        ({"units": "cm", "annotations": []}, "units"),
        ({"scale": 0, "annotations": []}, "scale"),
        ({"style": {"rect": {"thickness": 2}}, "annotations": []}, "thickness"),
    ],
)
def test_invalid_spec_is_reported(data: object, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        parse_spec(data, Path("."))


def test_ratio_box_must_be_between_zero_and_one() -> None:
    with pytest.raises(SpecError, match="0〜1"):
        resolve_box([0.5, 0.5, 1.5, 0.1], (100, 100), "ratio", "annotations[0]")


def test_box_requires_four_numbers() -> None:
    with pytest.raises(SpecError, match="4 個"):
        resolve_box([1, 2, 3], (100, 100), "px", "annotations[0]")


def test_broken_yaml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("annotations: [\n", encoding="utf-8")
    with pytest.raises(SpecError, match="書式"):
        load_spec(path)
