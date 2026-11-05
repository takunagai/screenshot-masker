"""annotate サブコマンドのテスト。OCR はフェイクに差し替える（test_cli.py と同じ作り）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from screenshot_masker.cli import EXIT_DETECTED, EXIT_ERROR, EXIT_NO_DETECTION, main
from screenshot_masker.models import Word
from tests.helpers import words_from_lines
from tests.image_helpers import WHITE, changed_box

SECRET_EMAIL = "alice@example.com"
RED = (229, 72, 77)
SPEC = "annotations:\n  - {type: rect, box: [300, 100, 50, 40], radius: 0}\n"


def no_ocr(image: Image.Image, lang: str) -> list[Word]:
    raise AssertionError("--mask なしでは OCR を呼ばない")


def email_ocr(image: Image.Image, lang: str) -> list[Word]:
    # 1 行目（y=0〜20）の x=50 以降にメールアドレスがある
    return words_from_lines(f"mail {SECRET_EMAIL}")


def make_image(path: Path, width: int = 400) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, 200), "white").save(path)
    return path


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", ())


@pytest.fixture
def spec_path(tmp_path: Path) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def test_annotate_writes_to_output_dir_and_keeps_source(tmp_path: Path, spec_path: Path) -> None:
    source = make_image(tmp_path / "in" / "shot.png")
    original = source.read_bytes()

    code = main(["annotate", str(source), "-s", str(spec_path)], ocr=no_ocr)

    assert code == EXIT_NO_DETECTION
    assert source.read_bytes() == original
    with Image.open(tmp_path / "annotated" / "shot.png") as output:
        assert changed_box(Image.new("RGB", (400, 200), WHITE), output) == (296, 96, 354, 144)


def test_annotate_refuses_to_overwrite_source(
    tmp_path: Path, spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "shot.png")
    original = source.read_bytes()

    code = main(["annotate", str(source), "-s", str(spec_path), "-o", str(tmp_path)], ocr=no_ocr)

    assert code == EXIT_ERROR
    assert "元画像と同じ" in capsys.readouterr().err
    assert source.read_bytes() == original


def test_annotate_folder_keeps_structure_and_jpeg(tmp_path: Path, spec_path: Path) -> None:
    make_image(tmp_path / "shots" / "a.png")
    make_image(tmp_path / "shots" / "sub" / "b.jpg")

    code = main(
        ["annotate", str(tmp_path / "shots"), "-s", str(spec_path), "-o", "out"], ocr=no_ocr
    )

    assert code == EXIT_NO_DETECTION
    assert (tmp_path / "out" / "a.png").is_file()
    with Image.open(tmp_path / "out" / "sub" / "b.jpg") as output:
        assert output.format == "JPEG"


def test_mask_then_annotate(
    tmp_path: Path, spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--mask: OCR の検出をマスクしてから注釈を描く。注釈はマスクで消えない。"""
    source = make_image(tmp_path / "shot.png")
    spec_path.write_text(
        "annotations:\n  - {type: rect, box: [60, 2, 100, 16], radius: 0}\n", encoding="utf-8"
    )

    code = main(
        ["annotate", str(source), "-s", str(spec_path), "--mask", "--method", "fill"],
        ocr=email_ocr,
    )

    assert code == EXIT_DETECTED
    output_text = capsys.readouterr()
    assert "email" in output_text.out
    assert SECRET_EMAIL not in output_text.out + output_text.err
    with Image.open(tmp_path / "annotated" / "shot.png") as output:
        assert output.getpixel((100, 10)) == (0, 0, 0)  # 検出範囲は塗りつぶし済み
        stroke = output.getpixel((58, 10))  # 枠の線はマスクの上に描かれている
        assert isinstance(stroke, tuple)
        assert all(abs(a - b) <= 8 for a, b in zip(stroke, RED, strict=True))


def test_annotate_style_comes_from_config_file(tmp_path: Path, spec_path: Path) -> None:
    source = make_image(tmp_path / "shot.png")
    config = tmp_path / "article.toml"
    config.write_text('[annotate.rect]\ncolor = "#0000FF"\nwidth = 6\n', encoding="utf-8")

    code = main(["annotate", str(source), "-s", str(spec_path), "-c", str(config)], ocr=no_ocr)

    assert code == EXIT_NO_DETECTION
    with Image.open(tmp_path / "annotated" / "shot.png") as output:
        assert output.getpixel((295, 120)) == (0, 0, 255)  # 太さ 6 なので x=294〜299


def test_annotate_scale_option(
    tmp_path: Path, spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "shot.png")
    code = main(["annotate", str(source), "-s", str(spec_path), "--scale", "2"], ocr=no_ocr)
    assert code == EXIT_NO_DETECTION
    with Image.open(tmp_path / "annotated" / "shot.png") as output:
        assert output.getpixel((293, 120)) != WHITE  # 太さ 4 * 2 = 8 なので x=292〜299


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--method", "fill"], "--mask と一緒に"),
        (["--scale", "zero"], "--scale"),
    ],
)
def test_annotate_option_errors(
    tmp_path: Path,
    spec_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    source = make_image(tmp_path / "shot.png")
    code = main(["annotate", str(source), "-s", str(spec_path), *arguments], ocr=no_ocr)
    error = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert message in error
    assert "Traceback" not in error


def test_invalid_spec_is_short_error(
    tmp_path: Path, spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "shot.png")
    spec_path.write_text("annotations:\n  - {type: rect}\n", encoding="utf-8")
    code = main(["annotate", str(source), "-s", str(spec_path)], ocr=no_ocr)
    error = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert error.startswith("エラー: ")
    assert "必須の項目 box" in error


def test_invalid_annotate_config_is_reported(
    tmp_path: Path, spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "shot.png")
    config = tmp_path / "bad.toml"
    config.write_text("[annotate.rect]\nthickness = 3\n", encoding="utf-8")
    code = main(["annotate", str(source), "-s", str(spec_path), "-c", str(config)], ocr=no_ocr)
    assert code == EXIT_ERROR
    assert "thickness" in capsys.readouterr().err
