"""Best-effort secret redaction applied to everything sent to a model. (Hardened further in Phase 12.)"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----.{0,6000}?-----END [A-Z ]{0,20}PRIVATE KEY-----", re.S), "<REDACTED:private_key>"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,1500}\.[A-Za-z0-9_-]{8,1500}\.[A-Za-z0-9_-]{8,1500}\b"), "<REDACTED:jwt>"),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<REDACTED:aws_key>"),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,100}\b"), "<REDACTED:github_token>"),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,100}\b"), "<REDACTED:slack_token>"),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,200}\b"), "<REDACTED:api_key>"),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<REDACTED:google_api_key>"),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[0-9A-Za-z]{16,99}\b"), "<REDACTED:stripe_key>"),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"), "<REDACTED:npm_token>"),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,32}\.[A-Za-z0-9_-]{16,64}\b"), "<REDACTED:sendgrid_key>"),
    ("azure_key", re.compile(r"(?i)\b(AccountKey|SharedAccessKey|SharedAccessSignature)\s{0,3}=\s{0,3}[^;\s\"']{8,200}"), r"\1=<REDACTED:azure_key>"),
    ("basic_auth", re.compile(r"(?i)\b(Basic)\s{1,5}[A-Za-z0-9+/]{20,2000}={0,2}"), r"\1 <REDACTED:token>"),
    ("bearer", re.compile(r"(?i)\b(Bearer)\s{1,5}[A-Za-z0-9._~+/=-]{16,2000}"), r"\1 <REDACTED:token>"),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,30}://)[^\s/:@]{1,100}:[^\s/@]{1,200}@"), r"\1<REDACTED:credentials>@"),
    ("secret_assignment", re.compile(
        r"(?i)\b([A-Za-z0-9_.-]{0,40}(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|authorization|credential)"
        r"[A-Za-z0-9_.-]{0,40})([ \t]{0,5}[=:][ \t]{0,5})(\"[^\"]*\"|'[^']*'|(?!<REDACTED)[^\s,;&\"']+)"), r"\1\2<REDACTED:secret>"),
]
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


_EMAIL = re.compile(r"\b[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5}\b")


@dataclass
class RedactionResult:
    text: str
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str, *, redact_emails: bool = True) -> RedactionResult:
    counts: Counter = Counter()
    for name, rx, repl in _PATTERNS:
        text, n = rx.subn(repl, text)
        if n:
            counts[name] += n
    found = 0

    def card(m):
        nonlocal found
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and digits[0] in "3456" and _luhn(digits):
            found += 1
            return "<REDACTED:card>"
        return m.group()

    text = _CARD.sub(card, text)
    if found:
        counts["card"] += found
    if redact_emails:
        text, n = _EMAIL.subn("<REDACTED:email>", text)
        if n:
            counts["email"] += n
    return RedactionResult(text, counts)
