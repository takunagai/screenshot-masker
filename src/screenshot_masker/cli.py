"""screenshot-masker のコマンドライン入口。

終了コード: 検出あり 1 / 検出なし 0 / エラー 2

最初の引数が annotate のときは注釈のサブコマンド（annotate_cli）に、
hook のときは Claude Code のフック用のサブコマンド（hook_cli）に処理を渡す。
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from screenshot_masker.config import Config, ConfigError, load_config
from screenshot_masker.detect import detect
from screenshot_masker.mask import apply_mask, draw_preview
from screenshot_masker.models import Detection, Word
from screenshot_masker.ocr import OcrUnavailableError, run_ocr

EXIT_NO_DETECTION = 0
EXIT_DETECTED = 1
EXIT_ERROR = 2

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
JPEG_QUALITY = 95
DEFAULT_OUTPUT_DIR = Path("masked")
PREVIEW_DIR_SUFFIX = "_preview"
ANNOTATE_COMMAND = "annotate"
HOOK_COMMAND = "hook"

OcrFunction = Callable[[Image.Image, str], list[Word]]


class UsageError(Exception):
    """入力や出力先の指定が正しくないとき。メッセージは利用者向け。"""


@dataclass(frozen=True)
class Job:
    source: Path
    output: Path
    preview: Path | None


def _is_within(path: Path, directory: Path) -> bool:
    return path.resolve().is_relative_to(directory.resolve())


def _iter_images(directory: Path, excluded: Sequence[Path]) -> list[Path]:
    images = [
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and not any(_is_within(path, folder) for folder in excluded)
    ]
    return sorted(images)


def plan_jobs(
    inputs: Sequence[Path], output_dir: Path, preview_dir: Path | None, *, is_dry_run: bool
) -> list[Job]:
    """入力から処理対象と出力先を決める。元画像を上書きする組み合わせは拒否する。"""
    excluded = [output_dir] + ([preview_dir] if preview_dir is not None else [])
    jobs: list[Job] = []
    for source in inputs:
        if source.is_dir():
            for image_path in _iter_images(source, excluded):
                relative = image_path.relative_to(source)
                jobs.append(
                    Job(
                        image_path,
                        output_dir / relative,
                        preview_dir / relative.with_suffix(".png") if preview_dir else None,
                    )
                )
        elif source.is_file():
            if source.suffix.lower() not in IMAGE_SUFFIXES:
                raise UsageError(f"対応していない形式です（png / jpg のみ）: {source}")
            jobs.append(
                Job(
                    source,
                    output_dir / source.name,
                    preview_dir / Path(source.name).with_suffix(".png") if preview_dir else None,
                )
            )
        else:
            raise UsageError(f"入力が見つかりません: {source}")

    if not jobs:
        raise UsageError("処理できる画像（png / jpg）がありません")

    source_paths = {job.source.resolve() for job in jobs}
    written: set[Path] = set()
    for job in jobs:
        targets = [] if is_dry_run else [job.output]
        if job.preview is not None:
            targets.append(job.preview)
        for target in targets:
            resolved = target.resolve()
            if resolved in source_paths or (resolved.exists() and resolved.samefile(job.source)):
                raise UsageError(
                    f"出力先が元画像と同じになるため中止しました: {target}"
                    "（-o で別のフォルダを指定してください）"
                )
            if resolved in written:
                raise UsageError(f"出力先のファイル名が重複しています: {target}")
            written.add(resolved)
    return jobs


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        # EXIF の向きを反映してから扱う（OCR の座標と保存する画像を一致させる）
        transposed = ImageOps.exif_transpose(opened)
        transposed.load()
        return transposed


def _save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        image.convert("RGB").save(path, quality=JPEG_QUALITY)
    else:
        image.save(path)


def process_job(job: Job, config: Config, ocr: OcrFunction, *, is_dry_run: bool) -> list[Detection]:
    image = _load_image(job.source)
    words = ocr(image, config.ocr_lang)
    detections = detect(words, config.rules())
    if not is_dry_run:
        _save_image(apply_mask(image, detections, config.mask), job.output)
    if job.preview is not None:
        _save_image(draw_preview(image, detections, config.mask), job.preview)
    return detections


def format_detection(source: Path, detection: Detection) -> str:
    """検出結果の 1 行。種類・位置・ファイル名だけを出し、一致した文字列は出さない。"""
    box = detection.box
    return f"{source}\t{detection.kind}\tx={box.left} y={box.top} w={box.width} h={box.height}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-masker",
        description="スクリーンショット内の機密情報を OCR で見つけてぼかします。"
        "終了コード: 検出あり 1 / なし 0 / エラー 2",
        epilog=f"注釈を描くときは「screenshot-masker {ANNOTATE_COMMAND} --help」、"
        f"Claude Code のフックで使うときは「screenshot-masker {HOOK_COMMAND} --help」を参照。",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="画像ファイルまたはフォルダ")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"マスク済み画像の出力先フォルダ（既定: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument("-c", "--config", type=Path, help="設定ファイル（TOML）")
    parser.add_argument(
        "--method", choices=("blur", "fill"), help="マスク方法（既定: 設定ファイル、なければ blur）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="画像を書かず、検出結果（種類・位置）だけを出す"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help=f"検出範囲を枠で囲んだ確認用画像を <出力先>{PREVIEW_DIR_SUFFIX} に出す",
    )
    parser.add_argument("--debug", action="store_true", help="エラー時に詳細を表示する")
    return parser


def _report_error(message: str, error: BaseException, *, is_debug: bool) -> None:
    print(f"エラー: {message}", file=sys.stderr)
    if is_debug:
        traceback.print_exception(error, file=sys.stderr)


def main(argv: Sequence[str] | None = None, ocr: OcrFunction = run_ocr) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == [ANNOTATE_COMMAND]:
        # annotate_cli はこのモジュールの関数を使うため、循環しないようここで読み込む
        from screenshot_masker import annotate_cli

        return annotate_cli.main(arguments[1:], ocr)
    if arguments[:1] == [HOOK_COMMAND]:
        from screenshot_masker import hook_cli

        return hook_cli.main(arguments[1:], ocr)
    argv = arguments
    parser = build_parser()
    args = parser.parse_args(argv)
    is_debug: bool = args.debug
    is_dry_run: bool = args.dry_run

    if is_dry_run and args.preview:
        print("エラー: --dry-run と --preview は同時に指定できません", file=sys.stderr)
        return EXIT_ERROR

    output_dir: Path = args.output
    preview_dir = (
        output_dir.with_name(output_dir.name + PREVIEW_DIR_SUFFIX) if args.preview else None
    )
    try:
        config = load_config(args.config)
        if args.method is not None:
            config = replace(config, mask=replace(config.mask, method=args.method))
        jobs = plan_jobs(args.inputs, output_dir, preview_dir, is_dry_run=is_dry_run)
    except (ConfigError, UsageError) as error:
        _report_error(str(error), error, is_debug=is_debug)
        return EXIT_ERROR

    has_error = False
    detection_count = 0
    detected_files = 0
    for job in jobs:
        try:
            detections = process_job(job, config, ocr, is_dry_run=is_dry_run)
        except OcrUnavailableError as error:
            _report_error(str(error), error, is_debug=is_debug)
            return EXIT_ERROR
        except (OSError, UnidentifiedImageError) as error:
            _report_error(f"画像を処理できませんでした: {job.source}", error, is_debug=is_debug)
            has_error = True
            continue
        for detection in detections:
            print(format_detection(job.source, detection))
        detection_count += len(detections)
        detected_files += 1 if detections else 0

    summary = f"{len(jobs)} ファイル中 {detected_files} ファイルで {detection_count} 件検出"
    if not is_dry_run:
        summary += f"。マスク済み画像: {output_dir}"
    if preview_dir is not None:
        summary += f"。確認用画像（マスク前の文字が残るので公開しないこと）: {preview_dir}"
    print(summary, file=sys.stderr)

    if has_error:
        return EXIT_ERROR
    return EXIT_DETECTED if detection_count else EXIT_NO_DETECTION


if __name__ == "__main__":
    sys.exit(main())
