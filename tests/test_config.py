from __future__ import annotations

from pathlib import Path

import pytest

from screenshot_masker.config import Config, ConfigError, load_config, parse_config
from screenshot_masker.detect import DEFAULT_KINDS


def test_defaults() -> None:
    config = parse_config({})
    assert config == Config()
    assert [rule.kind for rule in config.rules()] == list(DEFAULT_KINDS)


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
        *(kind for kind in DEFAULT_KINDS if kind != "ipv4"),
        "staff_id",
    ]


def test_enabled_optional_kinds() -> None:
    config = parse_config({"detect": {"enabled": ["uuid", "jp_passport"]}})
    assert config.enabled_kinds == ("uuid", "jp_passport")
    assert [rule.kind for rule in config.rules()][-2:] == ["uuid", "jp_passport"]


def test_optional_kind_can_be_listed_in_disabled() -> None:
    # 任意の種類を disabled に書いてもエラーにしない（既定で無効なので結果は変わらない）
    config = parse_config({"detect": {"disabled": ["uuid"]}})
    assert "uuid" not in [rule.kind for rule in config.rules()]


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
        ({"unknown": {"x": 1}}, "設定ファイル に不明な項目 unknown"),
        ({"ocr": {"language": "eng"}}, "[ocr] に不明な項目 language"),
        ({"mask": {"colour": "#000000"}}, "[mask] に不明な項目 colour"),
        ({"detect": {"allowed_domain": ["example.com"]}}, "[detect] に不明な項目 allowed_domain"),
        ({"detect": {"enabled": ["email"]}}, "enabled に指定できない種類があります: email"),
        ({"detect": {"enabled": ["uuid"], "disabled": ["uuid"]}}, "両方に指定されています: uuid"),
        (
            {"detect": {"custom": [{"name": "x", "pattern": "x", "flags": "i"}]}},
            "1 番目 に不明な項目 flags",
        ),
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


def test_article_example_config_is_valid() -> None:
    example = Path(__file__).parent.parent / "examples" / "article.toml"
    config = load_config(example)
    assert config.mask.blur_radius == 12
    assert config.annotate_style["label"]["background"] == "#1F2937E6"


def test_review_before_annotate_defaults_to_false() -> None:
    assert parse_config({}).should_review_before_annotate is False


def test_review_before_annotate_can_be_enabled() -> None:
    config = parse_config({"agent": {"review_before_annotate": True}})
    assert config.should_review_before_annotate is True


@pytest.mark.parametrize(
    "agent",
    [{"review_before_annotate": "yes"}, {"review_before_annotate": 1}, {"review": True}],
)
def test_invalid_agent_table_is_rejected(agent: dict[str, object]) -> None:
    with pytest.raises(ConfigError, match=r"\[agent\]"):
        parse_config({"agent": agent})
