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
# 全角の英数字・記号（U+FF01〜U+FF5E）を半角にする対応表。
# 1 文字ずつ置き換わるので、文字と単語の位置の対応は変わらない
_FULLWIDTH_TO_ASCII = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}


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

# 既定で検出する種類（並び順は build_rules の優先順位と同じ）
DEFAULT_KINDS: tuple[str, ...] = (
    "claude",
    "private_key",
    "connection_string",
    "url",
    "email",
    "aws_arn",
    "ipv4",
    "ipv6",
    "mac_address",
    "home_path",
    "credit_card",
    "my_number",
    "jp_phone",
    "jp_postal_code",
    "secret_assignment",
    "token",
)
# 誤検出が多いため、設定ファイルの [detect] enabled で指定したときだけ検出する種類
OPTIONAL_KINDS: tuple[str, ...] = (
    "uuid",
    "jp_passport",
    "jp_pension",
)

# OCR はハイフンを長音記号や全角のダッシュとして読むことがある。
# 文字クラスに埋め込むため、ASCII のハイフンは末尾に置く（範囲指定と解釈されないように）
# ハイフン類（U+2010〜U+2015）・マイナス記号（U+2212）・長音記号（U+30FC）・全角ハイフン（U+FF0D）
_DASH_CODE_POINTS = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0x30FC, 0xFF0D)
_DASH_CHARS = "".join(chr(code) for code in _DASH_CODE_POINTS) + "-"
_DASH = f"[{_DASH_CHARS}]"
# 数字の区切り（なし・空白・ダッシュ）
_DIGIT_SEPARATOR = rf"(?:{_DASH}|\s)?"

_CLAUDE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:session|cse)_[A-Za-z0-9]{6,}"
    r"|(?:https?://)?claude\.ai/code\S*",
    re.IGNORECASE,
)
_PRIVATE_KEY_PATTERN = re.compile(r"-{3,}\s*BEGIN [A-Z0-9 ]*PRIVATE KEY\s*-{3,}")
# 認証情報入りの接続文字列（scheme://ユーザー:パスワード@ホスト）
_CONNECTION_STRING_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]+://[^\s:@/]+:[^\s@/]+@\S+"
)
# OCR は数字の途中やコロンの前後に空白を入れることがあるので、1 文字分の空白を許す
_AWS_ARN_PATTERN = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\s?(?:\d\s?){11}\d:\S*")
_IPV6_PATTERN = re.compile(
    r"(?<![0-9A-Za-z:.])(?:[0-9A-Fa-f]{0,4}\s?:\s?){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])"
)
_MAC_ADDRESS_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}"
    r"(?![0-9A-Fa-f:-])"
)
# 長い数字の途中（前後が「区切りと数字」で続く）から始まったり終わったりしないようにする
_NUMBER_START = rf"(?<!\d)(?<!\d[\s{_DASH_CHARS}])"
_NUMBER_END = rf"(?!\d)(?![\s{_DASH_CHARS}]\d)"
_CREDIT_CARD_PATTERN = re.compile(
    rf"{_NUMBER_START}(?:\d{_DIGIT_SEPARATOR}){{12,18}}\d{_NUMBER_END}"
)
_MY_NUMBER_PATTERN = re.compile(
    rf"{_NUMBER_START}\d{{4}}{_DIGIT_SEPARATOR}\d{{4}}{_DIGIT_SEPARATOR}\d{{4}}{_NUMBER_END}"
)
# 区切りのある電話番号・括弧付きの市外局番・+81 で始まる国際表記・区切りのない携帯と IP 電話
_JP_PHONE_PATTERN = re.compile(
    rf"(?<![\d{_DASH_CHARS}])(?:"
    rf"0\d{{1,4}}{_DASH}\d{{1,4}}{_DASH}\d{{3,4}}"
    rf"|0\d{{1,4}}\s\d{{1,4}}\s\d{{3,4}}"
    rf"|0\d{{1,4}}[(（]\d{{1,4}}[)）]\d{{3,4}}"
    rf"|[(（]0\d{{1,4}}[)）]\s?\d{{1,4}}{_DASH}\d{{3,4}}"
    rf"|\+81[\s{_DASH_CHARS}]?\d{{1,4}}[\s{_DASH_CHARS}]?\d{{1,4}}[\s{_DASH_CHARS}]?\d{{3,4}}"
    rf"|0[5-9]0\d{{8}}"
    rf")(?![\d{_DASH_CHARS}])"
)
_JP_POSTAL_CODE_PATTERN = re.compile(
    rf"〒\s?\d{{3}}{_DASH}?\d{{4}}"
    rf"|(?<![\d{_DASH_CHARS}])\d{{3}}{_DASH}\d{{4}}(?![\d{_DASH_CHARS}])"
)
# .env や設定ファイルの「キー = 値」で、キーが秘密を表すもの
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[\w.-]*"
    r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
    r"[\w.-]*[\"']?\s*[:=]\s*[\"']?[^\s\"',;]+",
    re.IGNORECASE,
)
_UUID_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
    r"-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])"
)
_JP_PASSPORT_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{7}(?![A-Za-z0-9])")
_JP_PENSION_PATTERN = re.compile(
    rf"(?<![\d{_DASH_CHARS}])\d{{4}}{_DASH}\d{{6}}(?![\d{_DASH_CHARS}])"
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
# macOS・Linux のホームと、Windows の C:\Users\<name>。
# 日本語フォントではバックスラッシュが円記号（U+00A5）や全角（U+FF3C）で認識される
_PATH_SEPARATOR = "[\\\\\u00a5\uff3c]"
_HOME_PATH_PATTERN = re.compile(
    r"(?:/Users|/home)/[^/\s]+(?:/\S*)?"
    rf"|[A-Za-z]:{_PATH_SEPARATOR}Users{_PATH_SEPARATOR}[^\\\u00a5\uff3c\s]+"
    rf"(?:{_PATH_SEPARATOR}\S*)?"
)
# 接頭辞でサービスが分かるトークン（gitleaks の既定規則などを参考にした主要なもの）
_PREFIXED_TOKEN = (
    r"sk-[A-Za-z0-9_-]{8,}"  # OpenAI・Anthropic など
    r"|gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{20,}"  # GitHub
    r"|gl(?:pat|dt|rt|ptt|oas|cbt)-[A-Za-z0-9_-]{16,}"  # GitLab
    r"|[sr]k_(?:live|test|prod)_[A-Za-z0-9]{10,}"  # Stripe
    r"|AIza[0-9A-Za-z_-]{30,}"  # Google
    r"|(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{12,}"  # AWS
    r"|xox[a-z]-[A-Za-z0-9-]{6,}|xapp-[A-Za-z0-9-]{10,}"  # Slack
    r"|hf_[A-Za-z0-9]{20,}"  # Hugging Face
    r"|npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}"  # npm・PyPI
    r"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"  # SendGrid
    r"|pplx-[A-Za-z0-9]{20,}"  # Perplexity
    r"|hvs\.[A-Za-z0-9_-]{20,}"  # HashiCorp Vault
    r"|shpat_[A-Fa-f0-9]{20,}|dop_v1_[a-f0-9]{20,}"  # Shopify・DigitalOcean
    r"|PMAK-[A-Za-z0-9-]{20,}|lin_api_[A-Za-z0-9]{20,}"  # Postman・Linear
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"  # JWT
)
_PREFIXED_TOKEN_PATTERN = re.compile(_PREFIXED_TOKEN)
_TOKEN_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_PREFIXED_TOKEN}|[0-9a-fA-F]{{32,}}|[A-Za-z0-9+/_-]{{32,}}={{0,2}})"
)

# 型の注釈や設定の説明でよく出る、秘密ではない値（secret_assignment で除く）
_NON_SECRET_VALUES = frozenset(
    {
        "string",
        "str",
        "number",
        "int",
        "integer",
        "boolean",
        "bool",
        "null",
        "none",
        "nil",
        "true",
        "false",
        "undefined",
        "required",
        "optional",
    }
)
# 伏せ字（****、••••、xxxx など）だけの値
_MASKED_VALUE_PATTERN = re.compile(r"[*•●・xX.…]+")
_PHONE_PREFIXES_11_DIGITS = ("020", "050", "060", "070", "080", "090", "0800")


def _digits(text: str) -> list[int]:
    """文字列中の数字（全角を含む）を順に取り出す。"""
    return [int(character) for character in text if character.isdigit()]


def _is_valid_ipv4(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def _is_valid_ipv6(text: str) -> bool:
    """IPv6 として正しく、ループバック（::1）や未指定（::）でないもの。数字を含まない語は除く。"""
    text = re.sub(r"\s", "", text)
    if text.count(":") < 2 or not any(character.isdigit() for character in text):
        return False
    try:
        address = ipaddress.IPv6Address(text)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_unspecified)


def _is_meaningful_mac_address(text: str) -> bool:
    """00:00:00:00:00:00 のように全部同じ値のものは除く。"""
    return len(set(re.sub(r"[:-]", "", text).lower())) > 1


def _passes_luhn(text: str) -> bool:
    """クレジットカード番号のチェック（Luhn）。13〜19 桁で、全部同じ数字のものは除く。"""
    digits = _digits(text)
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _is_valid_my_number(text: str) -> bool:
    """マイナンバーの検査用数字（平成 26 年総務省令第 85 号第 5 条の算式）を確かめる。

    11 桁の番号の最下位を 1 桁目とし、n 桁目の数字 Pn に Qn（1≦n≦6 は n+1、7≦n≦11 は n-5）を
    掛けて合計する。合計を 11 で割った余りが 1 以下なら 0、それ以外は 11 - 余り が検査用数字。
    """
    digits = _digits(text)
    if len(digits) != 12 or len(set(digits)) == 1:
        return False
    body, check = digits[:11], digits[11]
    total = sum(
        digit * (position + 1 if position <= 6 else position - 5)
        for position, digit in enumerate(reversed(body), start=1)
    )
    remainder = total % 11
    return check == (0 if remainder <= 1 else 11 - remainder)


def _is_valid_jp_phone(text: str) -> bool:
    """日本の電話番号の桁数と先頭の番号を確かめる（+81 は国内の 0 に直してから判定）。"""
    digits = "".join(str(digit) for digit in _digits(text))
    national = "0" + digits[2:] if text.lstrip().startswith("+81") else digits
    if len(national) == 10:
        # 固定電話（0AB〜J）と 0120。0 の次が 0 のものは国際プレフィックスなので除く
        return national[0] == "0" and national[1] != "0"
    if len(national) == 11:
        return national.startswith(_PHONE_PREFIXES_11_DIGITS)
    return False


def _is_secret_value(text: str) -> bool:
    """「キー = 値」の値が、空・伏せ字・変数の参照・型名などでないこと。"""
    value = re.split(r"[:=]", text, maxsplit=1)[1].strip().strip("\"'")
    if not value or _MASKED_VALUE_PATTERN.fullmatch(value):
        return False
    if value.startswith(("$", "<", "{", "%")):
        return False
    return value.lower() not in _NON_SECRET_VALUES


def _looks_like_token(text: str) -> bool:
    """長い英数字列のうち、ただの長い単語やパスを除く。"""
    if _PREFIXED_TOKEN_PATTERN.match(text):
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
    enabled_kinds: Iterable[str] = (),
    allowed_domains: Sequence[str] = (),
    custom_patterns: Sequence[tuple[str, str]] = (),
) -> list[Rule]:
    """既定ルールと利用者の正規表現からルール一覧を作る。並び順が優先順位になる。

    OPTIONAL_KINDS は enabled_kinds に含まれるときだけ加える。disabled_kinds は常に優先する。
    """
    allowed = tuple(allowed_domains)

    def url_validator(text: str) -> bool:
        return not is_allowed_domain(extract_host(text), allowed)

    # 並び順は DEFAULT_KINDS と同じにする（テストで一致を確かめている）
    defaults: list[Rule] = [
        Rule("claude", _CLAUDE_PATTERN),
        Rule("private_key", _PRIVATE_KEY_PATTERN),
        Rule("connection_string", _CONNECTION_STRING_PATTERN),
        Rule("url", _URL_PATTERN, url_validator),
        Rule("email", _EMAIL_PATTERN),
        Rule("aws_arn", _AWS_ARN_PATTERN),
        Rule("ipv4", _IPV4_PATTERN, _is_valid_ipv4),
        Rule("ipv6", _IPV6_PATTERN, _is_valid_ipv6),
        Rule("mac_address", _MAC_ADDRESS_PATTERN, _is_meaningful_mac_address),
        Rule("home_path", _HOME_PATH_PATTERN),
        Rule("credit_card", _CREDIT_CARD_PATTERN, _passes_luhn),
        Rule("my_number", _MY_NUMBER_PATTERN, _is_valid_my_number),
        Rule("jp_phone", _JP_PHONE_PATTERN, _is_valid_jp_phone),
        Rule("jp_postal_code", _JP_POSTAL_CODE_PATTERN),
        Rule("secret_assignment", _SECRET_ASSIGNMENT_PATTERN, _is_secret_value),
        Rule("token", _TOKEN_PATTERN, _looks_like_token),
    ]
    optional: list[Rule] = [
        Rule("uuid", _UUID_PATTERN),
        Rule("jp_passport", _JP_PASSPORT_PATTERN),
        Rule("jp_pension", _JP_PENSION_PATTERN),
    ]
    disabled = set(disabled_kinds)
    enabled = set(enabled_kinds)
    rules = [rule for rule in defaults if rule.kind not in disabled]
    rules.extend(rule for rule in optional if rule.kind in enabled and rule.kind not in disabled)
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
        # 日本語の OCR は英数字を全角で返すことがあるので、照合の前に半角へそろえる
        text = word.text.strip().translate(_FULLWIDTH_TO_ASCII)
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
