"""指示ファイル（YAML / JSON）の読み込みと検査。

指示ファイルの形:

    units: px            # 省略時 px。ratio にすると 0〜1 の割合で書ける
    scale: auto          # 省略時 auto。数値で倍率を固定できる
    style: style.yaml    # スタイル設定ファイルへのパス、またはその場で書いたマッピング
    masks:               # 先に処理する（ぼかし・塗りつぶしのみ）
      - {type: blur, box: [x, y, width, height]}
    annotations:         # masks の後に、書いた順に描く
      - {type: rect, box: [x, y, width, height]}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from screenshot_masker.errors import SpecError
from screenshot_masker.geometry import Units, parse_units
from screenshot_masker.style import (
    DEFAULT_STYLE,
    Style,
    load_data_file,
    load_style_file,
    merge_style,
)

GEOMETRY_KEYS: dict[str, tuple[str, ...]] = {
    "rect": ("box",),
    "badge": ("at", "number"),
    "arrow": ("from", "to"),
    "blur": ("box",),
    "fill": ("box",),
    "label": ("at", "text"),
    "spotlight": ("box",),
}
REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "rect": ("box",),
    "badge": ("at",),
    "arrow": ("from", "to"),
    "blur": ("box",),
    "fill": ("box",),
    "label": ("at", "text"),
    "spotlight": ("box",),
}
MASK_TYPES = ("blur", "fill")
TOP_LEVEL_KEYS = ("units", "scale", "style", "masks", "annotations")


@dataclass
class Operation:
    """1 件の指示（マスクまたは注釈）。"""

    kind: str
    item: dict[str, Any]
    units: Units
    where: str


@dataclass
class Spec:
    style: Style
    scale: float | None
    operations: list[Operation] = field(default_factory=list)


def parse_scale(value: object, where: str) -> float | None:
    if value is None or value == "auto":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise SpecError(f"{where}: scale は auto か正の数値を指定してください（指定値: {value!r}）")
    return float(value)


def _parse_items(
    raw_items: object, section: str, default_units: Units, allowed_types: tuple[str, ...]
) -> list[Operation]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise SpecError(f"{section} は配列で書いてください")
    operations: list[Operation] = []
    for index, raw in enumerate(raw_items):
        where = f"{section}[{index}]"
        if not isinstance(raw, dict):
            raise SpecError(f"{where}: キーと値の組（マッピング）で書いてください")
        kind = raw.get("type")
        if kind not in allowed_types:
            raise SpecError(
                f"{where}: type は {', '.join(allowed_types)} のいずれかです（指定値: {kind!r}）"
            )
        where = f"{where}({kind})"
        allowed_keys = {"type", "units", *GEOMETRY_KEYS[kind], *DEFAULT_STYLE[kind]}
        unknown = sorted(set(raw) - allowed_keys)
        if unknown:
            allowed = ", ".join(sorted(allowed_keys))
            raise SpecError(f"{where}: 不明な項目 {', '.join(unknown)}（使える項目: {allowed}）")
        missing = [key for key in REQUIRED_KEYS[kind] if key not in raw]
        if missing:
            raise SpecError(f"{where}: 必須の項目 {', '.join(missing)} がありません")
        units = parse_units(raw["units"], where) if "units" in raw else default_units
        operations.append(Operation(kind=kind, item=dict(raw), units=units, where=where))
    return operations


def parse_spec(data: object, base_dir: Path, base_style: Style | None = None) -> Spec:
    """読み込んだ指示データを検査して Spec にする。

    スタイルの重なり順: 既定値 < base_style（--style）< 指示ファイルの style < 各指示の項目
    """
    if not isinstance(data, dict):
        raise SpecError("指示ファイルの最上位はキーと値の組（マッピング）で書いてください")
    unknown = sorted(set(data) - set(TOP_LEVEL_KEYS))
    if unknown:
        allowed = ", ".join(TOP_LEVEL_KEYS)
        raise SpecError(f"指示ファイルに不明な項目 {', '.join(unknown)}（使える項目: {allowed}）")
    if "annotations" not in data and "masks" not in data:
        raise SpecError("指示ファイルに annotations も masks もありません")

    style = merge_style(DEFAULT_STYLE, None, "既定値") if base_style is None else base_style
    raw_style = data.get("style")
    if isinstance(raw_style, str):
        style_path = Path(raw_style)
        if not style_path.is_absolute():
            style_path = base_dir / style_path
        style = load_style_file(style_path, style)
    else:
        style = merge_style(style, raw_style, "style")

    units = parse_units(data.get("units", "px"), "units")
    operations = [
        *_parse_items(data.get("masks"), "masks", units, MASK_TYPES),
        *_parse_items(data.get("annotations"), "annotations", units, tuple(GEOMETRY_KEYS)),
    ]
    return Spec(style=style, scale=parse_scale(data.get("scale"), "scale"), operations=operations)


def load_spec(path: Path, base_style: Style | None = None) -> Spec:
    return parse_spec(load_data_file(path), path.parent, base_style)
