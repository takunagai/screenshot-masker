from __future__ import annotations

from pathlib import Path

import pytest

from screenshot_masker.config import Config, ConfigError, load_config, parse_config


def test_defaults() -> None:
    config = parse_config({})
    assert config == Config()
    assert [rule.kind for rule in config.rules()] == [
        "claude",
        "url",
        "email",
        "ipv4",
        "home_path",
        "token",
    ]


def test_load_full_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[ocr]
lang = "eng"

[mask]
method = "fill"
padding = 10
fill_color = "#112233"

[detect]
disabled = ["ipv4", "project_code"]
allowed_domains = ["example.com"]

[[detect.custom]]
name = "project_code"
pattern = 'PRJ-\\d{4}'

[[detect.custom]]
name = "staff_id"
pattern = 'EMP\\d{6}'
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.ocr_lang == "eng"
    assert config.mask.method == "fill"
    assert config.mask.padding == 10
    assert config.allowed_domains == ("example.com",)
    assert [rule.kind for rule in config.rules()] == [
        "claude",
        "url",
        "email",
        "home_path",
        "token",
        "staff_id",
    ]


def test_missing_default_config_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("screenshot_masker.config.DEFAULT_CONFIG_PATHS", (tmp_path / "none",))
    assert load_config(None) == Config()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"mask": {"method": "erase"}}, "method"),
        ({"mask": {"padding": -1}}, "padding"),
        ({"mask": {"fill_color": "black"}}, "fill_color"),
        ({"detect": {"disabled": ["unknown"]}}, "未知の種類"),
        ({"detect": {"allowed_domains": "example.com"}}, "allowed_domains"),
        ({"detect": {"custom": [{"name": "x", "pattern": "("}]}}, "正規表現"),
        ({"detect": {"custom": [{"pattern": "x"}]}}, "name"),
        ({"ocr": "jpn"}, "[ocr]"),
    ],
)
def test_invalid_config(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_config(data)


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[mask\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="書式"):
        load_config(path)


def test_missing_explicit_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="見つかりません"):
        load_config(tmp_path / "missing.toml")


def test_example_config_is_valid() -> None:
    example = Path(__file__).parent.parent / "screenshot-masker.example.toml"
    config = load_config(example)
    assert config.allowed_domains == ("zenn.dev", "note.com")
    assert config.rules()[-1].kind == "project_code"
