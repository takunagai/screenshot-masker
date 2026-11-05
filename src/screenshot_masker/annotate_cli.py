"""annotate サブコマンド。指示ファイル（YAML / JSON）に従って注釈を描き込む。

    screenshot-masker annotate 入力... -s 指示ファイル [-o フォルダ] [-c 設定] [--mask]

処理の順序: （--mask のとき）OCR で検出した機密情報のマスク → 指示ファイルの masks → annotations
終了コード: 成功 0 / --mask で検出あり 1 / エラー 2（既存のマスク CLI と同じ）
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PIL import UnidentifiedImageError

from screenshot_masker.cli import (
    EXIT_DETECTED,
    EXIT_ERROR,
    EXIT_NO_DETECTION,
    Job,
    OcrFunction,
    UsageError,
    _load_image,
    _report_error,
    _save_image,
    format_detection,
    plan_jobs,
)
from screenshot_masker.config import Config, ConfigError, load_config
from screenshot_masker.detect import detect
from screenshot_masker.errors import SpecError
from screenshot_masker.mask import apply_mask
from screenshot_masker.models import Detection
from screenshot_masker.ocr import OcrUnavailableError
from screenshot_masker.render import render
from screenshot_masker.spec import Spec, load_spec, parse_scale

DEFAULT_ANNOTATED_DIR = Path("annotated")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-masker annotate",
        description="指示ファイル（YAML / JSON）に従って、枠・番号バッジ・矢印・ぼかし・"
        "文字ラベル・スポットライトを描き込みます。"
        "終了コード: 成功 0 / --mask で検出あり 1 / エラー 2",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="画像ファイルまたはフォルダ")
    parser.add_argument(
        "-s", "--spec", type=Path, required=True, help="指示ファイル（.yaml / .yml / .json）"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_ANNOTATED_DIR,
        help=f"注釈を描いた画像の出力先フォルダ（既定: {DEFAULT_ANNOTATED_DIR}）",
    )
    parser.add_argument(
        "-c", "--config", type=Path, help="設定ファイル（TOML）。[annotate] に見た目の既定値"
    )
    parser.add_argument(
        "--mask",
        action="store_true",
        help="注釈の前に、OCR で検出した機密情報をマスクする（既存のマスクと同じ処理）",
    )
    parser.add_argument(
        "--method", choices=("blur", "fill"), help="--mask のマスク方法（既定: 設定ファイルの値）"
    )
    parser.add_argument(
        "--scale", help="線の太さなどの倍率。auto（既定）か数値。指示ファイルの scale より優先"
    )
    parser.add_argument("--debug", action="store_true", help="エラー時に詳細を表示する")
    return parser


def _parse_scale_argument(value: str | None) -> float | None:
    if value is None or value == "auto":
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise SpecError(
            f"--scale は auto か正の数値を指定してください（指定値: {value!r}）"
        ) from error
    return parse_scale(number, "--scale")


def process_annotate_job(
    job: Job,
    config: Config,
    spec: Spec,
    ocr: OcrFunction,
    *,
    should_mask: bool,
    scale_override: float | None,
) -> tuple[list[Detection], list[str]]:
    """1 枚を処理して保存する。検出結果と、利用者向けの注意を返す。"""
    image = _load_image(job.source)
    detections: list[Detection] = []
    if should_mask:
        detections = detect(ocr(image, config.ocr_lang), config.rules())
        image = apply_mask(image, detections, config.mask)
    result = render(image, spec, scale_override)
    _save_image(result.image, job.output)
    return detections, result.warnings


def main(argv: Sequence[str], ocr: OcrFunction) -> int:
    args = build_parser().parse_args(argv)
    is_debug: bool = args.debug
    should_mask: bool = args.mask
    output_dir: Path = args.output

    if args.method is not None and not should_mask:
        print("エラー: --method は --mask と一緒に指定してください", file=sys.stderr)
        return EXIT_ERROR
    try:
        config = load_config(args.config)
        if args.method is not None:
            config = replace(config, mask=replace(config.mask, method=args.method))
        spec = load_spec(args.spec, config.annotate_style)
        scale_override = _parse_scale_argument(args.scale)
        jobs = plan_jobs(args.inputs, output_dir, None, is_dry_run=False)
    except (ConfigError, SpecError, UsageError) as error:
        _report_error(str(error), error, is_debug=is_debug)
        return EXIT_ERROR

    has_error = False
    detection_count = 0
    shown_warnings: set[str] = set()
    for job in jobs:
        try:
            detections, warnings = process_annotate_job(
                job, config, spec, ocr, should_mask=should_mask, scale_override=scale_override
            )
        except (OcrUnavailableError, SpecError) as error:
            # 指示ファイルの誤りや OCR が無いことは、残りの画像でも同じなので中止する
            _report_error(str(error), error, is_debug=is_debug)
            return EXIT_ERROR
        except (OSError, UnidentifiedImageError) as error:
            _report_error(f"画像を処理できませんでした: {job.source}", error, is_debug=is_debug)
            has_error = True
            continue
        for warning in warnings:
            if warning not in shown_warnings:
                print(f"注意: {warning}", file=sys.stderr)
                shown_warnings.add(warning)
        for detection in detections:
            print(format_detection(job.source, detection))
        detection_count += len(detections)

    summary = f"{len(jobs)} ファイルに注釈を描きました。出力先: {output_dir}"
    if should_mask:
        summary += f"。マスクした検出: {detection_count} 件"
    print(summary, file=sys.stderr)

    if has_error:
        return EXIT_ERROR
    return EXIT_DETECTED if detection_count else EXIT_NO_DETECTION
