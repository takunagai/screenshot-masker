"""コマンドラインの入口。

    screenshot-masker annotate INPUT --spec SPEC [--style STYLE] [-o OUTPUT] [--scale N]
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import __version__
from .errors import SpecError
from .render import render
from .spec import load_spec, parse_scale
from .style import DEFAULT_STYLE, load_style_file

EXIT_OK = 0
EXIT_USER_ERROR = 2


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.annotated{input_path.suffix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-masker", description="スクリーンショットのマスクと注釈"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--debug", action="store_true", help="エラー時に開発者向けの詳細（トレースバック）を表示する"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    annotate = subcommands.add_parser(
        "annotate",
        help="指示ファイルに従ってマスクと注釈を描き込む",
        description="指示ファイルの masks を先に処理し、続けて annotations を書いた順に描く。",
    )
    annotate.add_argument("input", type=Path, help="元画像（上書きはしない）")
    annotate.add_argument(
        "-s", "--spec", type=Path, required=True, help="指示ファイル（.yaml / .yml / .json）"
    )
    annotate.add_argument(
        "--style", type=Path, help="スタイル設定ファイル。指示ファイル内の style がさらに上書きする"
    )
    annotate.add_argument(
        "-o", "--output", type=Path, help="出力先（省略時: <元の名前>.annotated.<拡張子>）"
    )
    annotate.add_argument(
        "--scale", help="線の太さなどの倍率。auto（既定）または数値。指示ファイルの scale より優先"
    )
    return parser


def _parse_scale_argument(value: str | None) -> float | None:
    if value is None or value == "auto":
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise SpecError(f"--scale は auto か正の数値を指定してください（指定値: {value!r}）") from error
    return parse_scale(number, "--scale")


def run_annotate(args: argparse.Namespace) -> int:
    input_path: Path = args.input
    output_path: Path = args.output or default_output_path(input_path)
    if output_path.resolve() == input_path.resolve():
        raise SpecError("出力先が元画像と同じです。元画像は上書きしません。-o で別のパスを指定してください")

    base_style = load_style_file(args.style, DEFAULT_STYLE) if args.style else None
    spec = load_spec(args.spec, base_style)
    scale_override = _parse_scale_argument(args.scale)

    try:
        with Image.open(input_path) as source:
            source.load()
            image_format = source.format
            result = render(source, spec, scale_override)
    except FileNotFoundError as error:
        raise SpecError(f"画像が見つかりません: {input_path}") from error
    except UnidentifiedImageError as error:
        raise SpecError(f"画像として読めません: {input_path}") from error

    for warning in result.warnings:
        print(f"注意: {warning}", file=sys.stderr)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        save_format = None if output_path.suffix else image_format
        result.image.save(output_path, format=save_format)
    except (OSError, ValueError, KeyError) as error:
        raise SpecError(f"画像を保存できません: {output_path}（{error}）") from error
    print(f"{output_path} を書き出しました（倍率 {result.scale:g}）")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "annotate":
            return run_annotate(args)
    except SpecError as error:
        print(f"エラー: {error}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return EXIT_USER_ERROR
    parser.error(f"不明なコマンド: {args.command}")
    return EXIT_USER_ERROR


if __name__ == "__main__":
    sys.exit(main())
