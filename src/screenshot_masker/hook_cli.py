"""hook サブコマンド。Claude Code のフックから呼び、画像がモデルに渡る前に機密を調べる。

    screenshot-masker hook [-c 設定] [--on-detect block|mask]

標準入力でフックの入力（JSON）を受け取り、次の 2 つの場面で画像を調べる。

- PreToolUse（Read）: エージェントが画像ファイルを開くとき。検出したら開かせない。
  --on-detect mask のときは、マスクした写しに差し替えて開かせる
- UserPromptSubmit: 送信するプロンプトに書かれた画像のパス（@ 付き・引用符付きを含む）。
  検出したら送信を止める（プロンプトは差し替えられないので、mask でも止める）

画像を調べられない（OCR が無い・画像を開けない・設定や入力が不正）ときも止める（安全側に倒す）。
止めた理由には、ファイル名と検出の種類・件数だけを出し、一致した文字列は出さない。
クリップボードから貼り付けた画像はフックの入力に含まれないため、調べられない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import UnidentifiedImageError

from screenshot_masker.cli import EXIT_ERROR, OcrFunction, _load_image
from screenshot_masker.config import Config, ConfigError, load_config
from screenshot_masker.detect import detect
from screenshot_masker.mask import apply_mask
from screenshot_masker.models import Detection
from screenshot_masker.ocr import OcrUnavailableError

ON_DETECT_BLOCK = "block"
ON_DETECT_MASK = "mask"
# Read ツールが画像として扱う拡張子。Pillow で開けないもの（HEIC など）は調べられないので止める
HOOK_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"})
# --on-detect mask で作るマスク済みの写しの置き場（OS の一時フォルダの下。名前に利用者 ID を付ける）
MASKED_COPY_DIR_NAME = "screenshot-masker-hook"

_IMAGE_EXTENSION = r"\.(?:png|jpe?g|gif|webp|bmp|tiff?)"
# プロンプト中の画像のパス: "引用符付き"・'引用符付き'・空白を \ でエスケープしたもの・@ 付き
_PROMPT_PATH_PATTERN = re.compile(
    rf"\"([^\"\n]+?{_IMAGE_EXTENSION})\""
    rf"|'([^'\n]+?{_IMAGE_EXTENSION})'"
    rf"|((?:\\ |[^\s\"'<>(),])+?{_IMAGE_EXTENSION})(?![\w.])",
    re.IGNORECASE,
)

HookOutput = dict[str, Any]


class HookInputError(Exception):
    """フックの入力（JSON）が読めないとき。"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-masker hook",
        description="Claude Code のフック（PreToolUse の Read・UserPromptSubmit）から呼び、"
        "画像がモデルに渡る前に機密を調べます。フックの入力（JSON）を標準入力から読みます。",
    )
    parser.add_argument(
        "-c", "--config", type=Path, help="設定ファイル（TOML）。検出する種類などを調整する"
    )
    parser.add_argument(
        "--on-detect",
        choices=(ON_DETECT_BLOCK, ON_DETECT_MASK),
        default=ON_DETECT_BLOCK,
        help="機密を見つけたとき: block（既定）は止める。mask は画像を開くときに限り、"
        "マスクした写しに差し替える",
    )
    return parser


def read_hook_input(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise HookInputError("フックの入力（JSON）を読めませんでした") from error
    if not isinstance(data, dict):
        raise HookInputError("フックの入力が JSON のオブジェクトではありません")
    return data


def find_image_paths(prompt: str, cwd: Path) -> list[Path]:
    """プロンプトに書かれた画像のパスのうち、実在するファイルを返す（重複は除く）。"""
    found: list[Path] = []
    for match in _PROMPT_PATH_PATTERN.finditer(prompt):
        raw = next(group for group in match.groups() if group)
        candidate = Path(raw.removeprefix("@").replace("\\ ", " ")).expanduser()
        path = candidate if candidate.is_absolute() else cwd / candidate
        if path.is_file() and path not in found:
            found.append(path)
    return found


def inspect_image(path: Path, config: Config, ocr: OcrFunction) -> list[Detection]:
    return detect(ocr(_load_image(path), config.ocr_lang), config.rules())


def describe(path: Path, detections: Sequence[Detection]) -> str:
    """理由に出す 1 行。種類と件数だけで、一致した文字列は出さない。"""
    kinds = ", ".join(sorted({detection.kind for detection in detections}))
    return f"{path}: {len(detections)} 件（{kinds}）"


def masked_copy_directory() -> Path:
    """マスク済みの写しを置く、利用者専用のフォルダを用意して返す。

    共有の一時フォルダ（Linux の /tmp など）で、他の利用者が先に作ったフォルダや
    シンボリックリンクを使わないよう、名前に利用者 ID を付け、持ち主と権限を確かめる。
    確かめられないときは OSError を送出し、フックは安全側（止める）に倒れる。
    """
    base = Path(tempfile.gettempdir())
    if not hasattr(os, "getuid"):
        # Windows には POSIX の持ち主・権限が無い。利用者ごとの一時フォルダに任せる
        directory = base / MASKED_COPY_DIR_NAME
        directory.mkdir(exist_ok=True)
        return directory
    uid = os.getuid()
    directory = base / f"{MASKED_COPY_DIR_NAME}-{uid}"
    directory.mkdir(mode=0o700, exist_ok=True)
    status = directory.lstat()
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != uid or status.st_mode & 0o077:
        raise OSError(f"マスク済みの写しの置き場が安全ではありません: {directory}")
    return directory


def write_masked_copy(path: Path, detections: Sequence[Detection], config: Config) -> Path:
    """マスクした写しを利用者専用の一時フォルダに PNG で書き、そのパスを返す（元画像は変えない）。

    所有者だけが読める一時ファイルに書いてから目的の名前に置き換えるので、
    目的の名前にシンボリックリンクがあっても辿らない。
    """
    directory = masked_copy_directory()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:32]
    target = directory / f"{digest}.png"
    masked = apply_mask(_load_image(path), detections, config.mask)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".png", delete=False) as file:
        temporary = Path(file.name)
        try:
            masked.save(file, format="PNG")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(target)
    return target


def _is_within(path: Path, directory: Path) -> bool:
    return path.resolve().is_relative_to(directory.resolve())


def pre_tool_use_deny(reason: str) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def handle_read(
    data: dict[str, Any], config: Config, ocr: OcrFunction, on_detect: str
) -> HookOutput | None:
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or Path(file_path).suffix.lower() not in HOOK_IMAGE_SUFFIXES:
        return None
    path = Path(file_path)
    if not path.is_file():
        # 存在しないファイルは Read 自体が失敗するので、渡る中身が無い
        return None
    detections = inspect_image(path, config, ocr)
    if not detections:
        return None
    summary = describe(path, detections)
    if on_detect == ON_DETECT_MASK:
        masked = write_masked_copy(path, detections, config)
        cwd = Path(str(data.get("cwd") or "."))
        # 作業フォルダの中の画像なら確認なしで開かせ、外の画像なら利用者に確認させる
        # （元の画像を開くときと同じ扱いにするため）
        decision = "allow" if _is_within(path, cwd) else "ask"
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": (
                    f"screenshot-masker がマスクした写しに差し替えました: {summary}"
                ),
                "updatedInput": {**tool_input, "file_path": str(masked)},
                "additionalContext": (
                    "この画像は screenshot-masker が機密らしい文字列をマスクした写しです"
                    f"（{summary}）。"
                    "マスクされていない元の画像を別の方法で開こうとしないでください。"
                    "OCR が見落とした機密が写っている可能性があるので、"
                    "公開前の目視は利用者に頼んでください。"
                ),
            }
        }
    return pre_tool_use_deny(
        "screenshot-masker が画像に機密らしい文字列を見つけたため、開くのを止めました: "
        f"{summary}。別の方法でこの画像を開こうとしないでください。"
        "必要なら利用者に、マスクしてから渡すよう頼んでください"
        "（screenshot-masker <画像> -o <出力先>）。"
    )


def handle_prompt(data: dict[str, Any], config: Config, ocr: OcrFunction) -> HookOutput | None:
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return None
    cwd = Path(str(data.get("cwd") or "."))
    findings = [(path, inspect_image(path, config, ocr)) for path in find_image_paths(prompt, cwd)]
    hits = [describe(path, detections) for path, detections in findings if detections]
    if not hits:
        return None
    return {
        "decision": "block",
        "reason": "screenshot-masker が送信前の画像に機密らしい文字列を見つけたため、"
        "送信を止めました。\n"
        + "\n".join(f"- {hit}" for hit in hits)
        + "\nマスクしてから、マスク済みの画像でもう一度送ってください"
        "（screenshot-masker <画像> -o <出力先>）。",
    }


def failure_output(event: object, message: str) -> HookOutput | None:
    reason = f"screenshot-masker が画像を調べられなかったため、止めました: {message}"
    if event == "PreToolUse":
        return pre_tool_use_deny(reason)
    if event == "UserPromptSubmit":
        return {"decision": "block", "reason": reason}
    return None


def main(argv: Sequence[str], ocr: OcrFunction) -> int:
    args = build_parser().parse_args(argv)
    on_detect: str = args.on_detect
    try:
        data = read_hook_input(sys.stdin.read())
    except HookInputError as error:
        # 終了コード 2 はフックでは「止める」の意味になる
        print(f"エラー: {error}", file=sys.stderr)
        return EXIT_ERROR

    event = data.get("hook_event_name")
    output: HookOutput | None
    try:
        config = load_config(args.config)
        if event == "PreToolUse" and data.get("tool_name") == "Read":
            output = handle_read(data, config, ocr, on_detect)
        elif event == "UserPromptSubmit":
            output = handle_prompt(data, config, ocr)
        else:
            output = None
    except (ConfigError, OcrUnavailableError) as error:
        output = failure_output(event, str(error))
    except (OSError, UnidentifiedImageError):
        output = failure_output(event, "画像を開けませんでした")

    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0
