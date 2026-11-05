"""コマンドラインの入出力。"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import changed_box, white_image
from PIL import Image

from screenshot_masker.cli import EXIT_OK, EXIT_USER_ERROR, main

SPEC = "annotations:\n  - {type: rect, box: [10, 10, 40, 20]}\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    white_image().save(tmp_path / "shot.png")
    (tmp_path / "spec.yaml").write_text(SPEC, encoding="utf-8")
    return tmp_path


def test_writes_to_default_output_and_keeps_source(workspace: Path) -> None:
    source_bytes = (workspace / "shot.png").read_bytes()
    code = main(["annotate", str(workspace / "shot.png"), "--spec", str(workspace / "spec.yaml")])
    assert code == EXIT_OK
    assert (workspace / "shot.png").read_bytes() == source_bytes
    with Image.open(workspace / "shot.annotated.png") as output:
        assert changed_box(white_image(), output) is not None


def test_refuses_to_overwrite_source(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source_bytes = (workspace / "shot.png").read_bytes()
    code = main(
        [
            "annotate",
            str(workspace / "shot.png"),
            "-s",
            str(workspace / "spec.yaml"),
            "-o",
            str(workspace / "." / "shot.png"),
        ]
    )
    assert code == EXIT_USER_ERROR
    assert "上書きしません" in capsys.readouterr().err
    assert (workspace / "shot.png").read_bytes() == source_bytes


def test_style_option_and_scale_option(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (workspace / "style.yaml").write_text("rect: {color: '#0000FF'}\n", encoding="utf-8")
    output = workspace / "out" / "result.png"
    code = main(
        [
            "annotate",
            str(workspace / "shot.png"),
            "-s",
            str(workspace / "spec.yaml"),
            "--style",
            str(workspace / "style.yaml"),
            "--scale",
            "2",
            "-o",
            str(output),
        ]
    )
    assert code == EXIT_OK
    assert "倍率 2" in capsys.readouterr().out
    with Image.open(output) as image:
        # 太さ 4 × 2 = 8 なので x=2〜9 が線
        assert image.getpixel((3, 20)) == (0, 0, 255)


def test_user_errors_are_short_messages(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace / "bad.yaml").write_text("annotations:\n  - {type: rect}\n", encoding="utf-8")
    code = main(["annotate", str(workspace / "shot.png"), "-s", str(workspace / "bad.yaml")])
    error = capsys.readouterr().err
    assert code == EXIT_USER_ERROR
    assert error.startswith("エラー: ")
    assert "Traceback" not in error


def test_missing_image_is_reported(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["annotate", str(workspace / "none.png"), "-s", str(workspace / "spec.yaml")])
    assert code == EXIT_USER_ERROR
    assert "画像が見つかりません" in capsys.readouterr().err
