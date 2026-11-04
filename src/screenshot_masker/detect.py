"""OCR 結果（単語と位置のリスト）から機密情報の位置を見つける純関数群。

OCR には依存しない。入力は Word のリスト、出力は Detection のリスト。
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from screenshot_masker.models import Detection, Word

# 単語間の隙間が行の高さに対してこの比率未満なら、OCR が 1 語を分割したものとみなして詰めて連結する
TIGHT_GAP_RATIO = 0.2


@dataclass(frozen=True)
class Rule:
    """1 種類の検出ルール。validator が False を返した一致は捨てる。"""

    kind: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None


@dataclass(frozen=True)
class Line:
    """行単位に組み立てた単語列。"""

    words: tuple[Word, ...]


@dataclass(frozen=True)
class _LineText:
    text: str
    # text の各文字がどの単語に属するか（区切りの空白は -1）
    char_to_word: tuple[int, ...]


@dataclass
class _Candidate:
    kind: str
    rule_index: int
    line_index: int
    word_indices: frozenset[int] = field(default_factory=frozenset)


# ── 既定ルール ─────────────────────────────────────────

DEFAULT_KINDS: tuple[str, ...] = (
    "claude",
    "url",
    "email",
    "ipv4",
    "home_path",
    "token",
)

_CLAUDE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:session|cse)_[A-Za-z0-9]{6,}"
    r"|(?:https?://)?claude\.ai/code\S*",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(
    r"(?:https?|ftp)://[^\s<>\"'「」（）]+"
    r"|(?<![\w@.])www\.[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s<>\"'「」（）]*"
    r"|(?<![\w@./])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/[^\s<>\"'「」（）]*",
    re.IGNORECASE,
)
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
)
_IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.]*\d)")
_HOME_PATH_PATTERN = re.compile(r"(?:/Users|/home)/[^/\s]+(?:/\S*)?")
_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-[A-Za-z0-9_-]{8,}"
    r"|gh[po]_[A-Za-z0-9]{8,}"
    r"|xox[a-z]-[A-Za-z0-9-]{6,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|[0-9a-fA-F]{32,}"
    r"|[A-Za-z0-9+/_-]{32,}={0,2}"
    r")"
)


def _is_valid_ipv4(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def _looks_like_token(text: str) -> bool:
    """長い英数字列のうち、ただの長い単語やパスを除く。"""
    prefixes = ("sk-", "ghp_", "gho_", "xox", "AKIA")
    if text.startswith(prefixes):
        return True
    core = text.rstrip("=")
    if re.fullmatch(r"[0-9a-fA-F]+", core):
        return True
    has_digit = any(character.isdigit() for character in core)
    has_upper = any(character.isupper() for character in core)
    has_lower = any(character.islower() for character in core)
    # base64 らしさ: 数字と大小英字が混ざる。パス区切りだらけのものは除く
    return has_digit and has_upper and has_lower and core.count("/") <= len(core) // 8


def extract_host(url: str) -> str:
    """URL らしき文字列からホスト名（小文字）を取り出す。"""
    without_scheme = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", url)
    host = re.split(r"[/:?#]", without_scheme, maxsplit=1)[0]
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    return host.lower().rstrip(".")


def is_allowed_domain(host: str, allowed_domains: Iterable[str]) -> bool:
    """host が allowed_domains のいずれか、またはそのサブドメインなら True。"""
    for domain in allowed_domains:
        normalized = domain.lower().strip().lstrip(".")
        if normalized and (host == normalized or host.endswith("." + normalized)):
            return True
    return False


def build_rules(
    *,
    disabled_kinds: Iterable[str] = (),
    allowed_domains: Sequence[str] = (),
    custom_patterns: Sequence[tuple[str, str]] = (),
) -> list[Rule]:
    """既定ルールと利用者の正規表現からルール一覧を作る。並び順が優先順位になる。"""
    allowed = tuple(allowed_domains)

    def url_validator(text: str) -> bool:
        return not is_allowed_domain(extract_host(text), allowed)

    defaults: list[Rule] = [
        Rule("claude", _CLAUDE_PATTERN),
        Rule("url", _URL_PATTERN, url_validator),
        Rule("email", _EMAIL_PATTERN),
        Rule("ipv4", _IPV4_PATTERN, _is_valid_ipv4),
        Rule("home_path", _HOME_PATH_PATTERN),
        Rule("token", _TOKEN_PATTERN, _looks_like_token),
    ]
    disabled = set(disabled_kinds)
    rules = [rule for rule in defaults if rule.kind not in disabled]
    for name, pattern in custom_patterns:
        if name in disabled:
            continue
        rules.append(Rule(name, re.compile(pattern)))
    return rules


# ── 行の組み立て ───────────────────────────────────────


def group_into_lines(words: Iterable[Word]) -> list[Line]:
    """line_key ごとに単語をまとめ、行内は左から右へ並べる。空の単語は捨てる。"""
    grouped: dict[tuple[int, ...], list[Word]] = {}
    for word in words:
        if not word.text.strip():
            continue
        grouped.setdefault(word.line_key, []).append(word)
    lines = [
        Line(tuple(sorted(line_words, key=lambda word: word.box.left)))
        for line_words in grouped.values()
    ]
    lines.sort(key=lambda line: (min(word.box.top for word in line.words), line.words[0].box.left))
    return lines


def _join_words(words: Sequence[Word], *, is_gap_aware: bool) -> _LineText:
    """単語を連結した行テキストと、文字 → 単語番号の対応を作る。

    is_gap_aware が True のときは、隙間の狭い単語同士を空白なしで連結する
    （OCR が 1 つの URL やトークンを複数語に割った場合への対策）。
    """
    heights = sorted(word.box.height for word in words)
    line_height = heights[len(heights) // 2] if heights else 0
    parts: list[str] = []
    mapping: list[int] = []
    for index, word in enumerate(words):
        text = word.text.strip()
        if index > 0:
            gap = word.box.left - words[index - 1].box.right
            is_tight = is_gap_aware and gap < line_height * TIGHT_GAP_RATIO
            if not is_tight:
                parts.append(" ")
                mapping.append(-1)
        parts.append(text)
        mapping.extend([index] * len(text))
    return _LineText("".join(parts), tuple(mapping))


def _match_line(line: Line, line_index: int, rules: Sequence[Rule]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    variants = {
        _join_words(line.words, is_gap_aware=False),
        _join_words(line.words, is_gap_aware=True),
    }
    for variant in variants:
        for rule_index, rule in enumerate(rules):
            for match in rule.pattern.finditer(variant.text):
                matched = match.group(0)
                if not matched or (rule.validator is not None and not rule.validator(matched)):
                    continue
                indices = frozenset(
                    word_index
                    for word_index in variant.char_to_word[match.start() : match.end()]
                    if word_index >= 0
                )
                if indices:
                    candidates.append(_Candidate(rule.kind, rule_index, line_index, indices))
    return candidates


def _deduplicate(candidates: list[_Candidate]) -> list[_Candidate]:
    """同じ行で、既に採用した検出の単語集合に含まれる候補を捨てる。

    広い範囲を先に、同じ広さならルールの優先順位が高いものを先に採用する。
    """
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.line_index,
            -len(candidate.word_indices),
            candidate.rule_index,
            min(candidate.word_indices),
        ),
    )
    kept: list[_Candidate] = []
    for candidate in ordered:
        is_covered = any(
            existing.line_index == candidate.line_index
            and candidate.word_indices <= existing.word_indices
            for existing in kept
        )
        if not is_covered:
            kept.append(candidate)
    return kept


def detect(words: Iterable[Word], rules: Sequence[Rule]) -> list[Detection]:
    """単語リストから検出結果を返す。結果には一致した文字列を含めない。"""
    lines = group_into_lines(words)
    candidates: list[_Candidate] = []
    for line_index, line in enumerate(lines):
        candidates.extend(_match_line(line, line_index, rules))
    detections: list[Detection] = []
    for candidate in _deduplicate(candidates):
        line_words = lines[candidate.line_index].words
        boxes = [line_words[index].box for index in sorted(candidate.word_indices)]
        box = boxes[0]
        for other in boxes[1:]:
            box = box.union(other)
        detections.append(Detection(candidate.kind, box))
    detections.sort(key=lambda detection: (detection.box.top, detection.box.left))
    return detections
