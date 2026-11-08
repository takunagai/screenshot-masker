"""設定ファイル（TOML）の読み込みと検証。"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from screenshot_masker.detect import DEFAULT_KINDS, Rule, build_rules
from screenshot_masker.errors import SpecError
from screenshot_masker.style import DEFAULT_STYLE, Style, merge_style

MaskMethod = Literal["blur", "fill"]

DEFAULT_CONFIG_PATHS: tuple[Path, ...] = (
    Path("screenshot-masker.toml"),
    Path.home() / ".config" / "screenshot-masker" / "config.toml",
)

# 各テーブルで使える項目。綴りの誤りで設定が効かないまま進むのを防ぐため、これ以外はエラーにする
# （[annotate] は style.merge_style が同じ検査をする）
TOP_LEVEL_KEYS = ("ocr", "mask", "detect", "annotate")
OCR_KEYS = ("lang",)
MASK_KEYS = ("method", "padding", "blur_radius", "fill_color")
DETECT_KEYS = ("disabled", "allowed_domains", "custom")
CUSTOM_KEYS = ("name", "pattern")


class ConfigError(Exception):
    """設定ファイルの内容が正しくないとき。メッセージは利用者向け。"""


@dataclass(frozen=True)
class MaskSettings:
    method: MaskMethod = "blur"
    padding: int = 6
    blur_radius: int = 12
    fill_color: str = "#000000"


@dataclass(frozen=True)
class Config:
    ocr_lang: str = "jpn+eng"
    mask: MaskSettings = field(default_factory=MaskSettings)
    disabled_kinds: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    custom_patterns: tuple[tuple[str, str], ...] = ()
    # annotate サブコマンドの見た目の既定値（[annotate] テーブル）
    annotate_style: Style = field(default_factory=lambda: merge_style(DEFAULT_STYLE, None, ""))

    def rules(self) -> list[Rule]:
        return build_rules(
            disabled_kinds=self.disabled_kinds,
            allowed_domains=self.allowed_domains,
            custom_patterns=self.custom_patterns,
        )


def _expect_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] はテーブルで指定してください")
    return value


def _reject_unknown_keys(table: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise ConfigError(
            f"{where} に不明な項目 {', '.join(unknown)}（使える項目: {', '.join(allowed)}）"
        )


def _expect_string_list(table: dict[str, Any], key: str, section: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"[{section}] {key} は文字列の配列で指定してください")
    return tuple(value)


def _parse_mask(table: dict[str, Any]) -> MaskSettings:
    _reject_unknown_keys(table, MASK_KEYS, "[mask]")
    defaults = MaskSettings()
    method = table.get("method", defaults.method)
    if method not in ("blur", "fill"):
        raise ConfigError('[mask] method は "blur" か "fill" を指定してください')
    padding = table.get("padding", defaults.padding)
    blur_radius = table.get("blur_radius", defaults.blur_radius)
    for name, number in (("padding", padding), ("blur_radius", blur_radius)):
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ConfigError(f"[mask] {name} は 0 以上の整数で指定してください")
    fill_color = table.get("fill_color", defaults.fill_color)
    if not isinstance(fill_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", fill_color):
        raise ConfigError('[mask] fill_color は "#RRGGBB" 形式で指定してください')
    return MaskSettings(method, padding, blur_radius, fill_color)


def _parse_custom(table: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    entries = table.get("custom", [])
    if not isinstance(entries, list):
        raise ConfigError("[[detect.custom]] は配列テーブルで指定してください")
    patterns: list[tuple[str, str]] = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"[[detect.custom]] の {position} 番目がテーブルではありません")
        _reject_unknown_keys(entry, CUSTOM_KEYS, f"[[detect.custom]] の {position} 番目")
        name = entry.get("name")
        pattern = entry.get("pattern")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"[[detect.custom]] の {position} 番目に name がありません")
        if not isinstance(pattern, str) or not pattern:
            raise ConfigError(f"[[detect.custom]] {name} に pattern がありません")
        try:
            re.compile(pattern)
        except re.error as error:
            raise ConfigError(f"[[detect.custom]] {name} の正規表現が不正です: {error}") from error
        patterns.append((name, pattern))
    return tuple(patterns)


def _parse_annotate(data: dict[str, Any], mask: MaskSettings) -> Style:
    """[annotate] テーブルを読む。ぼかし・塗りつぶしの既定値は [mask] の値を引き継ぐ。"""
    table = _expect_table(data, "annotate")
    base = merge_style(
        DEFAULT_STYLE,
        {"blur": {"radius": mask.blur_radius}, "fill": {"color": mask.fill_color}},
        "[mask]",
    )
    try:
        return merge_style(base, table, "[annotate]")
    except SpecError as error:
        raise ConfigError(str(error)) from error


def parse_config(data: dict[str, Any]) -> Config:
    """TOML を読み込んだ辞書から Config を作る。"""
    _reject_unknown_keys(data, TOP_LEVEL_KEYS, "設定ファイル")
    ocr = _expect_table(data, "ocr")
    _reject_unknown_keys(ocr, OCR_KEYS, "[ocr]")
    lang = ocr.get("lang", Config.ocr_lang)
    if not isinstance(lang, str) or not lang:
        raise ConfigError("[ocr] lang は文字列で指定してください（例: jpn+eng）")
    detect_table = _expect_table(data, "detect")
    _reject_unknown_keys(detect_table, DETECT_KEYS, "[detect]")
    custom_patterns = _parse_custom(detect_table)
    disabled = _expect_string_list(detect_table, "disabled", "detect")
    known_kinds = set(DEFAULT_KINDS) | {name for name, _ in custom_patterns}
    unknown = sorted(set(disabled) - known_kinds)
    if unknown:
        raise ConfigError(
            f"[detect] disabled に未知の種類があります: {', '.join(unknown)}"
            f"（指定できる種類: {', '.join(sorted(known_kinds))}）"
        )
    mask = _parse_mask(_expect_table(data, "mask"))
    return Config(
        ocr_lang=lang,
        mask=mask,
        annotate_style=_parse_annotate(data, mask),
        disabled_kinds=disabled,
        allowed_domains=_expect_string_list(detect_table, "allowed_domains", "detect"),
        custom_patterns=custom_patterns,
    )


def load_config(path: Path | None) -> Config:
    """path を読む。None なら既定の場所を探し、無ければ既定値を返す。"""
    candidates = [path] if path is not None else [p for p in DEFAULT_CONFIG_PATHS if p.is_file()]
    if not candidates:
        return Config()
    target = candidates[0]
    try:
        with target.open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError as error:
        raise ConfigError(f"設定ファイルが見つかりません: {target}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"設定ファイルの書式が正しくありません: {target}: {error}") from error
    return parse_config(data)
