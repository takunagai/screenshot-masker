from __future__ import annotations

import pytest

from screenshot_masker.detect import (
    DEFAULT_KINDS,
    OPTIONAL_KINDS,
    build_rules,
    detect,
    extract_host,
    group_into_lines,
    is_allowed_domain,
)
from screenshot_masker.models import Box, Word
from tests.helpers import CHAR_WIDTH, LINE_HEIGHT, words_from_lines

# 架空の値だが、秘密の形式そのものをソースに書くと公開前の検査（秘密の形式の検出）で
# 実在の秘密と区別できないため、実行時に組み立てる
FAKE_GITHUB_TOKEN = "ghp" + "_ABCDEFGHIJKLMNOPQRSTUVWX1234"
FAKE_PRIVATE_KEY_HEADER = "-" * 5 + "BEGIN OPENSSH PRIVATE KEY" + "-" * 5
FAKE_JWT = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0In0", "c2lnbmF0dXJl"])


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
        (FAKE_GITHUB_TOKEN, ["token"]),
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


# 値はすべて例示用（RFC・AWS 文書・カード会社のテスト番号）か、0 を並べた架空のもの
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (FAKE_PRIVATE_KEY_HEADER, ["private_key"]),
        ("DATABASE_URL=postgres://app:pa55word@localhost/app", ["connection_string"]),
        ("arn:aws:iam::123456789012:role/demo", ["aws_arn"]),
        ("inet6 2001:db8::8a2e:370:7334 scope", ["ipv6"]),
        ("inet6 2001 :db8::8a2e:370:7334", ["ipv6"]),  # OCR がコロンの前に空白を入れた形
        ("arn:aws:iam:: 12345678901 2:role/demo", ["aws_arn"]),  # OCR が数字を割った形
        ("ether 00:1A:2B:3C:4D:5E", ["mac_address"]),
        ("ether 00-1a-2b-3c-4d-5e", ["mac_address"]),
        (r"cd C:\Users\taro\Documents", ["home_path"]),
        ("C:¥Users¥taro¥Desktop", ["home_path"]),
        ("card 4111 1111 1111 1111", ["credit_card"]),
        ("card 4111-1111-1111-1111", ["credit_card"]),
        ("個人番号 0000 0000 0019", ["my_number"]),
        ("000000000019", ["my_number"]),
        ("TEL 03-0000-1234", ["jp_phone"]),
        ("090-0000-1234", ["jp_phone"]),
        ("09000001234", ["jp_phone"]),
        ("0120-000-000", ["jp_phone"]),
        ("03(0000)1234", ["jp_phone"]),
        ("(03) 0000-1234", ["jp_phone"]),
        ("+81 90-0000-1234", ["jp_phone"]),
        ("０３ー００００ー１２３４", ["jp_phone"]),
        ("〒100-0000", ["jp_postal_code"]),
        ("住所 000-0000 東京都", ["jp_postal_code"]),
        ("DB_PASSWORD=hunter2", ["secret_assignment"]),
        ("DB_PASSWORD=$ecret123", ["secret_assignment"]),  # $ で始まる本物のパスワード
        ("api_key=<abc>def", ["secret_assignment"]),  # < で始まるだけでプレースホルダーではない
        ("REDIS_URL=redis://:pa55word@localhost:6379", ["connection_string"]),
        ("mongodb://app:pa/ss@word@localhost/db", ["connection_string"]),
        ("api_key: abc123", ["secret_assignment"]),
        ('"client_secret": "abc123"', ["secret_assignment"]),
        ("glpat-AbCdEfGhIjKlMnOpQrSt", ["token"]),
        ("rk_test_AbCdEfGhIj01", ["token"]),
        ("hf_AbCdEfGhIjKlMnOpQrStUv", ["token"]),
        (FAKE_JWT, ["token"]),
    ],
)
def test_added_default_kinds_are_detected(line: str, expected: list[str]) -> None:
    assert kinds_of(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "会議は 12:34:56 に開始",
        "公開日 2026-11-08",
        "std::vector と ::1 と ::",
        "00:00:00:00:00:00",
        "注文番号 123456789012",
        "card 4111 1111 1111 1112",
        "注文 ORD-123-4567",
        "00-1234-5678",
        "password=****",
        "password=${DB_PASSWORD}",
        "password=$DB_PASSWORD",
        "password={{ db_password }}",
        "password=%DB_PASSWORD%",
        "token: string",
        "api_key=<your-api-key>",
        "Account: 123456789012",
        "123e4567-e89b-12d3-a456-426614174000",
        "旅券 AB0000000",
        "年金 0000-000000",
    ],
)
def test_added_kinds_avoid_false_positives(line: str) -> None:
    assert kinds_of(line) == []


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("123e4567-e89b-12d3-a456-426614174000", "uuid"),
        ("旅券 AB0000000", "jp_passport"),
        ("年金 0000-000000", "jp_pension"),
    ],
)
def test_optional_kinds_need_enabling(line: str, kind: str) -> None:
    assert kinds_of(line) == []
    assert kinds_of(line, enabled_kinds=[kind]) == [kind]
    assert kinds_of(line, enabled_kinds=[kind], disabled_kinds=[kind]) == []


def test_rule_order_matches_default_kinds() -> None:
    assert [rule.kind for rule in build_rules()] == list(DEFAULT_KINDS)
    enabled = [rule.kind for rule in build_rules(enabled_kinds=OPTIONAL_KINDS)]
    assert enabled == [*DEFAULT_KINDS, *OPTIONAL_KINDS]


def test_fullwidth_characters_are_matched() -> None:
    # 日本語の OCR が全角で返した英数字も、半角にそろえてから照合する
    to_fullwidth = {code: code + 0xFEE0 for code in range(0x21, 0x7F)}
    assert kinds_of("連絡先 " + "alice@example.com".translate(to_fullwidth)) == ["email"]


def test_connection_string_covers_whole_credential() -> None:
    # 接続文字列全体を 1 つの検出にする（メールアドレスの一部としてではなく）
    assert kinds_of("postgres://app:pa55word@db.example.com:5432/app") == ["connection_string"]


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
