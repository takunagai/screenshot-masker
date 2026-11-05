"""実際の Tesseract を使うテスト。Tesseract（jpn+eng）が無い環境では skip する。

画像は Pillow で文字を描いて作る。値はすべて例示用（example.com、192.0.2.0/24 など）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from screenshot_masker.cli import EXIT_DETECTED, main
from screenshot_masker.detect import build_rules, detect
from screenshot_masker.ocr import is_tesseract_available, run_ocr

pytestmark = [
    pytest.mark.tesseract,
    pytest.mark.skipif(
        not is_tesseract_available("jpn+eng"), reason="Tesseract（jpn+eng）が未インストール"
    ),
]

CJK_FONT_CANDIDATES = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
)
FONT_SIZE = 28
LINE_SPACING = 60

SECRET_LINES = (
    ("email", "連絡先: alice@example.com までどうぞ"),
    ("url", "URL: https://example.com/docs/page"),
    ("claude", "session_01AbCdEf23GhIjKl"),
    ("ipv4", "server 192.0.2.10 port 22"),
    ("home_path", "cd /Users/taro/Projects/app"),
    ("token", "KEY=sk-test-abcdefghijklmnop1234"),
)
PLAIN_LINE = "これは普通の文章です。"


@pytest.fixture(autouse=True)
def ignore_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", ())


def load_font() -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """日本語フォントがあればそれを、無ければ Pillow 既定のフォントを返す。"""
    for path in CJK_FONT_CANDIDATES:
        if path.is_file():
            return ImageFont.truetype(str(path), FONT_SIZE), True
    return ImageFont.load_default(size=FONT_SIZE), False


def render(lines: list[str], *, is_dark: bool) -> Image.Image:
    font, _ = load_font()
    image = Image.new(
        "RGB", (1000, LINE_SPACING * len(lines) + 40), "#1e1e1e" if is_dark else "white"
    )
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text(
            (30, 30 + LINE_SPACING * index), line, font=font, fill="#dddddd" if is_dark else "black"
        )
    return image


def sample_lines() -> list[str]:
    _, has_cjk = load_font()
    lines = [line for _, line in SECRET_LINES]
    if has_cjk:
        lines.append(PLAIN_LINE)
    else:
        lines[0] = "Contact: alice@example.com"
    return lines


@pytest.mark.parametrize("is_dark", [False, True], ids=["light", "dark"])
def test_all_default_kinds_are_found(is_dark: bool) -> None:
    image = render(sample_lines(), is_dark=is_dark)
    detections = detect(run_ocr(image, "jpn+eng"), build_rules())
    assert sorted(detection.kind for detection in detections) == sorted(
        kind for kind, _ in SECRET_LINES
    )


def test_masked_image_has_no_detections(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "shot.png"
    render(sample_lines(), is_dark=False).save(source)
    original = source.read_bytes()

    code = main([str(source), "-o", str(tmp_path / "out")])

    assert code == EXIT_DETECTED
    assert source.read_bytes() == original
    output = capsys.readouterr()
    assert "alice@example.com" not in output.out + output.err

    # マスク後の画像を再度 OCR しても何も見つからない
    rerun_code = main([str(tmp_path / "out" / "shot.png"), "--dry-run"])
    assert rerun_code == 0


def test_dry_run_with_real_ocr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "shot.jpg"
    render(sample_lines(), is_dark=True).save(source, quality=95)
    code = main([str(source), "--dry-run", "-o", str(tmp_path / "out")])
    assert code == EXIT_DETECTED
    assert not (tmp_path / "out").exists()
    output = capsys.readouterr().out
    for _, line in SECRET_LINES:
        for token in line.split():
            if len(token) > 6:
                assert token not in output
