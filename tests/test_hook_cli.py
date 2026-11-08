"""hook サブコマンドのテスト。OCR はフェイクに差し替え、フックの入力は標準入力で渡す。"""

from __future__ import annotations

import io
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from screenshot_masker.cli import EXIT_ERROR, main
from screenshot_masker.models import Word
from screenshot_masker.ocr import OcrUnavailableError
from tests.helpers import words_from_lines

SECRET_EMAIL = "alice@example.com"


def email_ocr(image: Image.Image, lang: str) -> list[Word]:
    return words_from_lines(f"mail {SECRET_EMAIL}")


def clean_ocr(image: Image.Image, lang: str) -> list[Word]:
    return words_from_lines("これは普通の文章です")


def no_ocr(image: Image.Image, lang: str) -> list[Word]:
    raise AssertionError("画像以外では OCR を呼ばない")


def missing_ocr(image: Image.Image, lang: str) -> list[Word]:
    raise OcrUnavailableError("Tesseract が見つかりません")


def make_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 200), "white").save(path)
    return path


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", ())
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))


def run_hook(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, Any] | str,
    ocr: Any,
    *options: str,
) -> tuple[int, dict[str, Any] | None, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    code = main(["hook", *options], ocr=ocr)
    captured = capsys.readouterr()
    output = json.loads(captured.out) if captured.out.strip() else None
    return code, output, captured.out + captured.err


def read_payload(path: Path, cwd: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(path)},
        "cwd": str(cwd),
    }


def prompt_payload(prompt: str, cwd: Path) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(cwd)}


# ---- PreToolUse（Read） ----------------------------------------------------------


def test_read_image_with_secret_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    code, output, raw = run_hook(monkeypatch, capsys, read_payload(image, tmp_path), email_ocr)
    assert code == 0
    assert output is not None
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    assert "email" in specific["permissionDecisionReason"]
    assert SECRET_EMAIL not in raw


def test_read_clean_image_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    code, output, _ = run_hook(monkeypatch, capsys, read_payload(image, tmp_path), clean_ocr)
    assert (code, output) == (0, None)


def test_read_non_image_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("alice@example.com", encoding="utf-8")
    code, output, _ = run_hook(monkeypatch, capsys, read_payload(text_file, tmp_path), no_ocr)
    assert (code, output) == (0, None)


def test_read_missing_image_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = read_payload(tmp_path / "none.png", tmp_path)
    assert run_hook(monkeypatch, capsys, payload, no_ocr)[:2] == (0, None)


def test_mask_mode_substitutes_masked_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    Image.new("RGB", (400, 200), "black").save(image)
    original = image.read_bytes()
    payload = read_payload(image, tmp_path)
    payload["tool_input"]["limit"] = 10
    code, output, raw = run_hook(monkeypatch, capsys, payload, email_ocr, "--on-detect", "mask")
    assert code == 0
    assert output is not None
    specific = output["hookSpecificOutput"]
    # 差し替えると元の画像に掛けた権限の規則が効かなくなるので、毎回利用者に確認する
    assert specific["permissionDecision"] == "ask"
    masked = Path(specific["updatedInput"]["file_path"])
    assert specific["updatedInput"]["limit"] == 10  # 変えない項目もそのまま渡す
    assert masked != image
    assert masked.is_file()
    assert masked.parent == tmp_path / "tmp" / f"screenshot-masker-hook-{os.getuid()}"
    assert stat.S_IMODE(masked.stat().st_mode) == 0o600  # 所有者だけが読める
    assert stat.S_IMODE(masked.parent.stat().st_mode) == 0o700
    assert image.read_bytes() == original
    assert SECRET_EMAIL not in raw


@pytest.mark.parametrize("unsafe", ["shared", "symlink"])
def test_mask_mode_refuses_unsafe_directory(
    unsafe: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 他の利用者が先に作ったような、誰でも書けるフォルダやシンボリックリンクは使わない
    directory = tmp_path / "tmp" / f"screenshot-masker-hook-{os.getuid()}"
    if unsafe == "shared":
        directory.mkdir()
        directory.chmod(0o777)
    else:
        elsewhere = tmp_path / "elsewhere-dir"
        elsewhere.mkdir(mode=0o700)
        directory.symlink_to(elsewhere)
    image = make_image(tmp_path / "shot.png")
    payload = read_payload(image, tmp_path)
    _, output, _ = run_hook(monkeypatch, capsys, payload, email_ocr, "--on-detect", "mask")
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "updatedInput" not in output["hookSpecificOutput"]


def test_mask_mode_asks_for_image_outside_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "elsewhere" / "shot.png")
    project = tmp_path / "project"
    project.mkdir()
    payload = read_payload(image, project)
    _, output, _ = run_hook(monkeypatch, capsys, payload, email_ocr, "--on-detect", "mask")
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_read_is_denied_when_ocr_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    _, output, _ = run_hook(monkeypatch, capsys, read_payload(image, tmp_path), missing_ocr)
    assert output is not None
    specific = output["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    assert "調べられなかった" in specific["permissionDecisionReason"]


def test_read_is_denied_when_image_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    _, output, _ = run_hook(monkeypatch, capsys, read_payload(broken, tmp_path), email_ocr)
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_read_is_denied_on_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 想定外の例外で終了すると、フックでは「止めない」扱いになるため、止める出力を返す
    def broken_ocr(image: Image.Image, lang: str) -> list[Word]:
        raise RuntimeError("boom")

    image = make_image(tmp_path / "shot.png")
    code, output, _ = run_hook(monkeypatch, capsys, read_payload(image, tmp_path), broken_ocr)
    assert code == 0
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_read_is_denied_for_decompression_bomb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # 400x200 を巨大な画像として扱わせる
    _, output, _ = run_hook(monkeypatch, capsys, read_payload(image, tmp_path), email_ocr)
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_read_is_denied_when_config_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    config = tmp_path / "bad.toml"
    config.write_text("[mask]\nmethod = 'erase'\n", encoding="utf-8")
    payload = read_payload(image, tmp_path)
    _, output, _ = run_hook(monkeypatch, capsys, payload, email_ocr, "-c", str(config))
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---- UserPromptSubmit ------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "この画像を見て @shots/shot.png",
        "見て {path}",
        'これ "{path}" を説明して',
        "見て shots/shot.png です",
    ],
)
def test_prompt_with_secret_image_is_blocked(
    prompt: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image = make_image(tmp_path / "shots" / "shot.png")
    payload = prompt_payload(prompt.format(path=image), tmp_path)
    code, output, raw = run_hook(monkeypatch, capsys, payload, email_ocr)
    assert code == 0
    assert output is not None
    assert output["decision"] == "block"
    assert "email" in output["reason"]
    assert SECRET_EMAIL not in raw


def test_prompt_path_with_escaped_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "my shots" / "shot one.png")
    escaped = str(image).replace(" ", "\\ ")
    _, output, _ = run_hook(
        monkeypatch, capsys, prompt_payload(f"見て {escaped}", tmp_path), email_ocr
    )
    assert output is not None
    assert output["decision"] == "block"


@pytest.mark.parametrize(
    ("name", "prompt"),
    [
        # macOS のスクリーンショットの既定名のように、空白をエスケープせずに書いたパス
        ("スクリーンショット 2026-11-08 10.15.30.png", "見て {path} の内容"),
        # macOS が名前に使う特殊な空白（U+202F）
        ("Screenshot 2026-11-08 at 10.15.30" + chr(0x202F) + "AM.png", "これ {path}"),
        ("Screenshot (1).png", "見て {path}"),
        ("shot.png", "見て「{path}」を説明して"),
        ("shot.png", "{path}を説明して"),  # 拡張子の直後に日本語が続く
        ("shot.png", "これを見て: {path}."),  # 拡張子の直後が句点
        ("shot.jpeg", "見て {path}"),  # .jpg の途中で切らない
    ],
)
def test_prompt_paths_with_spaces_and_brackets(
    name: str,
    prompt: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image = make_image(tmp_path / "Desktop" / name)
    payload = prompt_payload(prompt.format(path=image), tmp_path)
    _, output, _ = run_hook(monkeypatch, capsys, payload, email_ocr)
    assert output is not None
    assert output["decision"] == "block"


@pytest.mark.parametrize(
    "prompt",
    ["画像の話はしていません", "見て missing.png", "設定は config.png.txt にある"],
)
def test_prompt_without_existing_images_passes(
    prompt: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _ = run_hook(monkeypatch, capsys, prompt_payload(prompt, tmp_path), no_ocr)
    assert (code, output) == (0, None)


def test_prompt_with_clean_image_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    payload = prompt_payload(f"見て {image}", tmp_path)
    assert run_hook(monkeypatch, capsys, payload, clean_ocr)[:2] == (0, None)


def test_prompt_is_blocked_when_ocr_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = make_image(tmp_path / "shot.png")
    payload = prompt_payload(f"見て {image}", tmp_path)
    _, output, _ = run_hook(monkeypatch, capsys, payload, missing_ocr)
    assert output is not None
    assert output["decision"] == "block"


# ---- そのほか --------------------------------------------------------------------


def test_invalid_input_exits_with_blocking_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, raw = run_hook(monkeypatch, capsys, "not json", no_ocr)
    assert code == EXIT_ERROR  # フックでは終了コード 2 が「止める」
    assert output is None
    assert "JSON" in raw


def test_other_events_are_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Read"}
    assert run_hook(monkeypatch, capsys, payload, no_ocr)[:2] == (0, None)
