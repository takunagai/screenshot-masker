"""見た目の既定値（スタイル）と、設定ファイルの読み込み・合成。

スタイルは注釈の種類ごとの項目を持つ。長さ（太さ・半径・文字の大きさなど）は
「論理ピクセル」で書き、描画時に画像の倍率（Retina なら 2）を掛ける。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

from screenshot_masker.errors import SpecError

StyleOptions = dict[str, Any]
Style = dict[str, Any]

ANNOTATION_TYPES = ("rect", "badge", "arrow", "blur", "fill", "label", "spotlight")
GLOBAL_KEYS = ("font", "reference_width")

DEFAULT_STYLE: Style = {
    # 画像幅をこの値で割って四捨五入した整数を倍率にする（1600 → 1 倍、3200 → 2 倍）
    "reference_width": 1600,
    # None のときは日本語を表示できるフォントを自動で探す
    "font": None,
    "rect": {"color": "#E5484D", "width": 4, "radius": 6},
    "badge": {
        "color": "#E5484D",
        "text_color": "#FFFFFF",
        "radius": 16,
        "font_size": 18,
        "outline_color": "#FFFFFF",
        "outline_width": 2,
    },
    "arrow": {"color": "#E5484D", "width": 4, "head_size": 18},
    "blur": {"radius": 12},
    "fill": {"color": "#000000"},
    "label": {
        "text_color": "#FFFFFF",
        "background": "#1F2937E6",
        "font_size": 18,
        "padding": 8,
        "radius": 6,
    },
    "spotlight": {"color": "#000000", "opacity": 0.55, "radius": 8},
}


def load_data_file(path: Path) -> Any:
    """YAML / JSON のファイルを読む。拡張子が .json なら JSON、それ以外は YAML。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecError(f"ファイルを読めません: {path}（{error.strerror}）") from error
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise SpecError(f"{path} の書式が正しくありません: {error}") from error


def merge_style(base: Style, override: object, where: str) -> Style:
    """base に override を重ねた新しいスタイルを返す（base は変更しない）。"""
    if override is None:
        return copy.deepcopy(base)
    if not isinstance(override, dict):
        raise SpecError(f"{where}: スタイルはキーと値の組（マッピング）で書いてください")
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in GLOBAL_KEYS:
            merged[key] = value
            continue
        if key not in ANNOTATION_TYPES:
            allowed = ", ".join((*GLOBAL_KEYS, *ANNOTATION_TYPES))
            raise SpecError(f"{where}: 不明なスタイル項目 {key!r}（使える項目: {allowed}）")
        if not isinstance(value, dict):
            raise SpecError(f"{where}: {key} はキーと値の組で書いてください")
        known = DEFAULT_STYLE[key]
        for option in value:
            if option not in known:
                allowed = ", ".join(known)
                raise SpecError(f"{where}: {key} に不明な項目 {option!r}（使える項目: {allowed}）")
        merged[key] = {**merged[key], **value}
    return merged


def load_style_file(path: Path, base: Style) -> Style:
    return merge_style(base, load_data_file(path), str(path))
