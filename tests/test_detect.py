from __future__ import annotations

import pytest

from screenshot_masker.detect import (
    build_rules,
    detect,
    extract_host,
    group_into_lines,
    is_allowed_domain,
)
from screenshot_masker.models import Box, Word
from tests.helpers import CHAR_WIDTH, LINE_HEIGHT, words_from_lines


def kinds_of(*lines: str, **rule_options: object) -> list[str]:
    rules = build_rules(**rule_options)  # type: ignore[arg-type]
    return [detection.kind for detection in detect(words_from_lines(*lines), rules)]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("id: session_01AbCdEf23GhIj", ["claude"]),
        ("cse_0123456789abcdef を開く", ["claude"]),
        ("https://claude.ai/code/session_abcDEF123456", ["claude"]),
        ("see https://example.com/docs now", ["url"]),
        ("www.example.org", ["url"]),
        ("example.net/path/to", ["url"]),
        ("mail me at alice@example.com please", ["email"]),
        ("server 192.0.2.10 is up", ["ipv4"]),
        ("cd /Users/taro/Projects", ["home_path"]),
        ("ls /home/hanako/", ["home_path"]),
        ("key=sk-ant-abcdefghijklmnop", ["token"]),
        ("ghp_ABCDEFGHIJKLMNOPQRSTUVWX1234", ["token"]),
        ("gho_abcdefgh12345678", ["token"]),
        ("xoxb-1234567890-abcdef", ["token"]),
        ("AKIAIOSFODNN7EXAMPLE", ["token"]),
        ("commit 0123456789abcdef0123456789abcdef01234567", ["token"]),
        ("dGhpcyBpcyBhIHRlc3QgdmFsdWUgZm9yIGJhc2U2NA==", ["token"]),
    ],
)
def test_default_kinds_are_detected(line: str, expected: list[str]) -> None:
    assert kinds_of(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "これは普通の文章です",
        "version 1.2.3 released",
        "999.1.1.1 is not an address",
        "1.2.3.4.5 is a version",
        "internationalizationlocalizationsupport",
        "/usr/local/bin/python",
        "session_ab",
    ],
)
def test_ordinary_text_is_not_detected(line: str) -> None:
    assert kinds_of(line) == []


def test_allowed_domain_is_kept() -> None:
    assert kinds_of("https://example.com/a", allowed_domains=["example.com"]) == []
    assert kinds_of("https://docs.example.com/a", allowed_domains=["example.com"]) == []
    assert kinds_of("https://notexample.com/a", allowed_domains=["example.com"]) == ["url"]


def test_allowed_domain_does_not_unmask_claude_url() -> None:
    assert kinds_of("https://claude.ai/code/x", allowed_domains=["claude.ai"]) == ["claude"]


def test_disabled_kind_is_skipped() -> None:
    assert kinds_of("alice@example.com", disabled_kinds=["email"]) == []


def test_custom_pattern() -> None:
    options = {"custom_patterns": [("project_code", r"PRJ-\d{4}")]}
    assert kinds_of("ticket PRJ-1234 done", **options) == ["project_code"]


def test_claude_url_wins_over_generic_url() -> None:
    # 同じ範囲が複数の種類に一致したら、優先順位の高いものだけを残す
    assert kinds_of("https://claude.ai/code/session_abcdef123") == ["claude"]


def test_multiple_detections_on_separate_lines() -> None:
    assert kinds_of("alice@example.com", "nothing here", "10.0.0.1") == ["email", "ipv4"]


def test_detection_box_covers_only_matched_words() -> None:
    words = words_from_lines("contact: alice@example.com today")
    [detection] = detect(words, build_rules())
    email_word = words[1]
    assert detection.box == email_word.box


def test_match_across_tight_split_words() -> None:
    # OCR が 1 つのメールアドレスを隙間なしの 2 語に割った場合
    words = [
        Word("alice@exam", Box(0, 0, 100, LINE_HEIGHT), (1, 1, 1)),
        Word("ple.com", Box(101, 0, 70, LINE_HEIGHT), (1, 1, 1)),
    ]
    [detection] = detect(words, build_rules())
    assert detection.kind == "email"
    assert detection.box == Box(0, 0, 171, LINE_HEIGHT)


def test_spaced_variant_catches_match_broken_by_tight_join() -> None:
    # 詰めて連結すると "v1192.0.2.10" になり IPv4 と見なせないが、空白版では拾える
    words = [
        Word("v1", Box(0, 0, 20, LINE_HEIGHT), (1, 1, 1)),
        Word("192.0.2.10", Box(21, 0, 100, LINE_HEIGHT), (1, 1, 1)),
    ]
    [detection] = detect(words, build_rules())
    assert detection.kind == "ipv4"
    assert detection.box == words[1].box


def test_detection_does_not_hold_matched_text() -> None:
    [detection] = detect(words_from_lines("alice@example.com"), build_rules())
    assert "alice" not in repr(detection)


def test_group_into_lines_orders_words() -> None:
    words = [
        Word("b", Box(50, 0, CHAR_WIDTH, LINE_HEIGHT), (1, 1, 1)),
        Word("a", Box(0, 0, CHAR_WIDTH, LINE_HEIGHT), (1, 1, 1)),
        Word("c", Box(0, 40, CHAR_WIDTH, LINE_HEIGHT), (1, 1, 2)),
        Word("  ", Box(0, 80, CHAR_WIDTH, LINE_HEIGHT), (1, 1, 3)),
    ]
    lines = group_into_lines(words)
    assert [[word.text for word in line.words] for line in lines] == [["a", "b"], ["c"]]


def test_extract_host_and_allowed_domain() -> None:
    assert extract_host("https://user@Sub.Example.com:8080/x?y") == "sub.example.com"
    assert extract_host("example.com/path") == "example.com"
    assert is_allowed_domain("sub.example.com", [".example.com"])
    assert not is_allowed_domain("example.com.evil.test", ["example.com"])
