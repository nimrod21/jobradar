"""HTML sanitiser for description_html (stdlib only).

Allowlist: p br ul ol li strong em b i h1-h4 blockquote a.
Every attribute is dropped except a[href] with http(s) URLs.
Links get target=_blank rel=noopener so nothing navigates the webview.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser

_ALLOWED = {"p", "br", "ul", "ol", "li", "strong", "em", "b", "i",
            "h1", "h2", "h3", "h4", "blockquote", "a"}
_VOID = {"br"}
_DROP_CONTENT = {"script", "style", "iframe", "object", "svg", "head", "title"}


class _Sanitiser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _DROP_CONTENT:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in _ALLOWED:
            return
        if tag == "a":
            href = next((v for k, v in attrs if k == "href"), "") or ""
            if href.startswith(("http://", "https://")):
                self.out.append(
                    f'<a href="{html.escape(href, quote=True)}" '
                    'target="_blank" rel="noopener noreferrer">')
            else:
                self.out.append("<a>")
        else:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth or tag not in _ALLOWED or tag in _VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag == "br" and not self._drop_depth:
            self.out.append("<br>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.out.append(html.escape(data))


def sanitize_html(markup: str | None) -> str | None:
    if not markup:
        return None
    # Greenhouse double-escapes; unescape until stable (max twice) before parsing
    for _ in range(2):
        unescaped = html.unescape(markup)
        if unescaped == markup:
            break
        markup = unescaped
    s = _Sanitiser()
    s.feed(markup)
    s.close()
    return "".join(s.out).strip() or None
