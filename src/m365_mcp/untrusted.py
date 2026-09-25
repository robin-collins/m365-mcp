"""Sanitise third-party text before it reaches the model (concept §12.4).

Email subjects, previews and bodies, event subjects, locations, previews
and bodies, and file names are written by other people. They are returned
verbatim as data, but invisible characters that can hide or reorder text
(control, bidi, zero-width and tag characters) are removed, HTML is
converted to plain text, and bodies are capped.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

PREVIEW_MAX_CHARS = 255
DEFAULT_BODY_MAX_CHARS = 20000

# Unicode categories removed: controls, format characters (bidi overrides,
# zero-width characters, BOM, tag characters) and lone surrogates.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})
_KEPT_CONTROLS = frozenset("\n\t")
_LINE_BREAKS = re.compile(r"\r\n|[\r\u2028\u2029]")

_SKIPPED_TAGS = frozenset({"head", "script", "style", "template", "noscript"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "fieldset",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)


def strip_control_chars(text: str) -> str:
    """Remove control, format and surrogate characters from text.

    Tabs and newlines are kept; ``\\r\\n``, ``\\r`` and the Unicode line and
    paragraph separators become ``\\n``.

    Args:
        text: Untrusted text.

    Returns:
        The text without invisible or reordering characters.
    """
    text = _LINE_BREAKS.sub("\n", text)
    return "".join(
        ch
        for ch in text
        if ch in _KEPT_CONTROLS or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )


class _TextExtractor(HTMLParser):
    """Collect the visible text of an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
            elif tag == "pre":
                self._pre_depth += 1
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "pre":
                self._pre_depth = max(0, self._pre_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        data = data.replace("\xa0", " ")
        if not self._pre_depth:
            data = re.sub(r"\s+", " ", data)
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Convert an HTML body to readable plain text.

    Scripts, styles and the document head are dropped; block elements and
    ``<br>`` become line breaks and list items are prefixed with ``- ``.

    Args:
        html: HTML markup.

    Returns:
        Plain text with one line break between blocks.
    """
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    return re.sub(r"[ \t]*\n\s*", "\n", text).strip()


def sanitize_text(value: str | None, *, max_chars: int | None = None) -> str | None:
    """Strip invisible characters from a short untrusted field.

    Args:
        value: Untrusted text such as a subject, location or file name.
        max_chars: Optional length cap applied after stripping.

    Returns:
        The cleaned text, or ``None`` when ``value`` is ``None``.
    """
    if value is None:
        return None
    cleaned = strip_control_chars(value)
    return cleaned if max_chars is None else cleaned[:max_chars]


def sanitize_preview(value: str | None) -> str | None:
    """Clean a body preview and cap it at ``PREVIEW_MAX_CHARS``.

    Args:
        value: Graph ``bodyPreview`` text.

    Returns:
        The cleaned preview, or ``None`` when ``value`` is ``None``.
    """
    return sanitize_text(value, max_chars=PREVIEW_MAX_CHARS)


def sanitize_body(
    content: str | None,
    content_type: str | None,
    max_chars: int = DEFAULT_BODY_MAX_CHARS,
) -> tuple[str | None, bool]:
    """Convert, clean and cap an untrusted message or event body.

    HTML is converted to text as a fallback for when Graph ignores the
    ``Prefer: outlook.body-content-type="text"`` header.

    Args:
        content: Graph ``body.content``.
        content_type: Graph ``body.contentType`` (``text`` or ``html``).
        max_chars: Maximum characters returned (``body_max_chars``).

    Returns:
        ``(text, truncated)`` where ``truncated`` is true when the cleaned
        body was longer than ``max_chars``.
    """
    if content is None:
        return None, False
    if (content_type or "").lower() == "html":
        content = html_to_text(content)
    cleaned = strip_control_chars(content)
    if len(cleaned) > max_chars:
        return cleaned[:max_chars], True
    return cleaned, False
