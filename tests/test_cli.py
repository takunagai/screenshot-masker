"""CLI のテスト。OCR はフェイクに差し替える。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from screenshot_masker.cli import (
    EXIT_DETECTED,
    EXIT_ERROR,
    EXIT_NO_DETECTION,
    OcrFunction,
    main,
)
from screenshot_masker.models import Word
from tests.helpers import words_from_lines

SECRET_EMAIL = "alice@example.com"
SECRET_TOKEN = "sk-test-abcdefghijklmnop"


def fake_ocr_for(lines_by_width: dict[int, list[str]]) -> OcrFunction:
    """画像の幅ごとに、OCR 結果として返す行を決めるフェイク。"""

    def fake_ocr(image: Image.Image, lang: str) -> list[Word]:
        return words_from_lines(*lines_by_width.get(image.width, []))

    return fake_ocr


def make_image(path: Path, width: int = 400) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, 200), "white").save(path)
    return path


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", ())


def test_detected_file_is_masked_and_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "in" / "shot.png")
    original = source.read_bytes()
    ocr = fake_ocr_for({400: [f"mail {SECRET_EMAIL}"]})

    code = main([str(source), "-o", str(tmp_path / "out")], ocr=ocr)

    assert code == EXIT_DETECTED
    assert (tmp_path / "out" / "shot.png").is_file()
    assert source.read_bytes() == original
    output = capsys.readouterr()
    assert "email" in output.out
    assert SECRET_EMAIL not in output.out + output.err


def test_no_detection_exit_0_and_still_writes(tmp_path: Path) -> None:
    source = make_image(tmp_path / "shot.jpg")
    code = main([str(source), "-o", str(tmp_path / "out")], ocr=fake_ocr_for({400: ["hello"]}))
    assert code == EXIT_NO_DETECTION
    assert (tmp_path / "out" / "shot.jpg").is_file()


def test_dry_run_writes_nothing_and_hides_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_image(tmp_path / "shot.png")
    ocr = fake_ocr_for({400: [f"key {SECRET_TOKEN}", f"to {SECRET_EMAIL}"]})

    code = main([str(source), "-o", str(tmp_path / "out"), "--dry-run"], ocr=ocr)

    assert code == EXIT_DETECTED
    assert not (tmp_path / "out").exists()
    output = capsys.readouterr()
    lines = output.out.strip().splitlines()
    assert [line.split("\t")[1] for line in lines] == ["token", "email"]
    assert all(line.startswith(str(source)) and "x=" in line for line in lines)
    combined = output.out + output.err
    for secret in (SECRET_TOKEN, SECRET_EMAIL):
        assert secret not in combined
        assert secret[:4] not in combined


def test_folder_input_keeps_structure(tmp_path: Path) -> None:
    make_image(tmp_path / "shots" / "a.png", width=400)
    make_image(tmp_path / "shots" / "sub" / "b.jpg", width=500)
    (tmp_path / "shots" / "note.txt").write_text("x", encoding="utf-8")
    ocr = fake_ocr_for({500: ["ip 192.0.2.1"]})

    code = main([str(tmp_path / "shots"), "-o", str(tmp_path / "out")], ocr=ocr)

    assert code == EXIT_DETECTED
    assert (tmp_path / "out" / "a.png").is_file()
    assert (tmp_path / "out" / "sub" / "b.jpg").is_file()
    assert not (tmp_path / "out" / "note.txt").exists()


def test_output_inside_input_folder_is_skipped(tmp_path: Path) -> None:
    make_image(tmp_path / "shots" / "a.png")
    out = tmp_path / "shots" / "masked"
    assert main([str(tmp_path / "shots"), "-o", str(out)], ocr=fake_ocr_for({})) == 0
    # 2 回目も出力先の画像を入力として拾わない
    assert main([str(tmp_path / "shots"), "-o", str(out)], ocr=fake_ocr_for({})) == 0
    assert not (out / "masked").exists()


def test_refuses_to_overwrite_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = make_image(tmp_path / "shot.png")
    original = source.read_bytes()
    ocr = fake_ocr_for({400: [SECRET_EMAIL]})

    code = main([str(source), "-o", str(tmp_path)], ocr=ocr)

    assert code == EXIT_ERROR
    assert source.read_bytes() == original
    assert "元画像" in capsys.readouterr().err


def test_refuses_duplicate_output_names(tmp_path: Path) -> None:
    first = make_image(tmp_path / "a" / "shot.png")
    second = make_image(tmp_path / "b" / "shot.png")
    code = main([str(first), str(second), "-o", str(tmp_path / "out")], ocr=fake_ocr_for({}))
    assert code == EXIT_ERROR
    assert not (tmp_path / "out").exists()


def test_preview_writes_separate_folder(tmp_path: Path) -> None:
    source = make_image(tmp_path / "shot.jpg")
    ocr = fake_ocr_for({400: [SECRET_EMAIL]})
    code = main([str(source), "-o", str(tmp_path / "out"), "--preview"], ocr=ocr)
    assert code == EXIT_DETECTED
    assert (tmp_path / "out" / "shot.jpg").is_file()
    preview = tmp_path / "out_preview" / "shot.png"
    with Image.open(preview) as image:
        assert (255, 0, 0) in {pixel for pixel in image.convert("RGB").get_flattened_data()}


def test_dry_run_and_preview_conflict(tmp_path: Path) -> None:
    source = make_image(tmp_path / "shot.png")
    assert main([str(source), "--dry-run", "--preview"], ocr=fake_ocr_for({})) == EXIT_ERROR


def test_missing_input_exit_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope.png")], ocr=fake_ocr_for({})) == EXIT_ERROR


def test_unsupported_suffix_exit_2(tmp_path: Path) -> None:
    path = tmp_path / "a.gif"
    Image.new("RGB", (10, 10)).save(path)
    assert main([str(path)], ocr=fake_ocr_for({})) == EXIT_ERROR


def test_broken_image_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    good = make_image(tmp_path / "good.png")
    code = main([str(broken), str(good), "-o", str(tmp_path / "out")], ocr=fake_ocr_for({}))
    assert code == EXIT_ERROR
    assert (tmp_path / "out" / "good.png").is_file()
    assert "broken.png" in capsys.readouterr().err


def test_invalid_config_exit_2(tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text('[mask]\nmethod = "erase"\n', encoding="utf-8")
    source = make_image(tmp_path / "shot.png")
    assert main([str(source), "-c", str(config)], ocr=fake_ocr_for({})) == EXIT_ERROR


def test_config_allowed_domain_and_method_override(tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text('[detect]\nallowed_domains = ["example.com"]\n', encoding="utf-8")
    source = make_image(tmp_path / "shot.png")
    ocr = fake_ocr_for({400: ["https://example.com/docs"]})
    code = main(
        [str(source), "-c", str(config), "--method", "fill", "-o", str(tmp_path / "out")], ocr=ocr
    )
    assert code == EXIT_NO_DETECTION


def test_fill_method_paints_region(tmp_path: Path) -> None:
    source = make_image(tmp_path / "shot.png")
    ocr = fake_ocr_for({400: [SECRET_EMAIL]})
    main([str(source), "--method", "fill", "-o", str(tmp_path / "out")], ocr=ocr)
    with Image.open(tmp_path / "out" / "shot.png") as image:
        assert image.convert("RGB").getpixel((5, 5)) == (0, 0, 0)
