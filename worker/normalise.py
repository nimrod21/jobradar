"""RawJob -> Job: HTML stripping, whitespace cleanup, salary best-effort,
then dates / geo / fingerprints via their modules.

description gets plain text (feeds search_vec and geo scanning);
description_html keeps the verbatim markup for the app's detail pane.
"""

from __future__ import annotations

import html as html_mod
import re

from selectolax.parser import HTMLParser

from .dates import parse_date
from .fingerprint import fingerprint
from .geo import detect_geo_flags, detect_remote
from .models import Job, RawJob

_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")
# newline after block-level boundaries so <p>/<li> structure survives the strip,
# while inline tags (<strong>, <a>) don't split words
_BLOCK_BREAK = re.compile(r"(?i)</(?:p|div|li|ul|ol|h[1-6]|blockquote|tr|section|article)>|<br\s*/?>")

_SALARY_NUM = re.compile(r"(\d{1,3}(?:[,.]\d{3})*|\d+)\s*([kK])?")
_SALARY_RANGE = re.compile(
    r"(?P<cur>[$€£₾]|USD|EUR|GBP|GEL)?\s*"
    r"(?P<min>\d{1,3}(?:[,.]\d{3})*(?:\s*[kK])?)"
    r"\s*[-–—to]{1,3}\s*"
    r"(?P<cur2>[$€£₾]|USD|EUR|GBP|GEL)?\s*"
    r"(?P<max>\d{1,3}(?:[,.]\d{3})*(?:\s*[kK])?)",
    re.IGNORECASE,
)
_CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "₾": "GEL",
               "usd": "USD", "eur": "EUR", "gbp": "GBP", "gel": "GEL"}
_PERIODS = [("hour", "hour"), ("/hr", "hour"), ("day", "day"),
            ("month", "month"), ("year", "year"), ("/yr", "year"),
            ("annum", "year"), ("annual", "year")]


def _looks_like_html(text: str) -> bool:
    return "<" in text and ">" in text


def strip_html(markup: str) -> str:
    """Entity-unescape (Greenhouse content arrives escaped), then strip tags
    preserving block structure as newlines."""
    text = markup
    # Greenhouse escapes the whole payload: "&lt;p&gt;..." — unescape until stable (max twice)
    for _ in range(2):
        unescaped = html_mod.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    if not _looks_like_html(text):
        return _clean_ws(text)
    text = _BLOCK_BREAK.sub(lambda m: m.group(0) + "\n", text)
    tree = HTMLParser(text)
    for tag in ("script", "style"):
        for node in tree.css(tag):
            node.decompose()
    plain = tree.body.text(separator="") if tree.body else tree.text(separator="")
    return _clean_ws(plain)


def _clean_ws(text: str) -> str:
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _NL.sub("\n\n", text).strip()


def _num(s: str) -> float:
    s = s.strip().lower()
    k = s.endswith("k")
    s = s.rstrip("k").strip().replace(",", "").replace(".", "")
    val = float(s) if s else 0.0
    return val * 1000 if k else val


def parse_salary(raw: str | None) -> tuple[float | None, float | None, str | None, str | None]:
    """Best effort only; the verbatim string is what's stored and shown."""
    if not raw:
        return None, None, None, None
    m = _SALARY_RANGE.search(raw)
    if not m:
        return None, None, None, None
    cur_sym = (m.group("cur") or m.group("cur2") or "").lower()
    currency = _CURRENCIES.get(cur_sym)
    period = next((p for needle, p in _PERIODS if needle in raw.lower()), None)
    lo, hi = _num(m.group("min")), _num(m.group("max"))
    if hi < lo:
        lo, hi = hi, lo
    return (lo or None), (hi or None), currency, period


def normalise(rj: RawJob) -> Job:
    # sources escape entities in scalar fields too (RemoteOK: "Crown &amp; Pearl")
    title = _WS.sub(" ", html_mod.unescape(rj.title)).strip()
    company = _WS.sub(" ", html_mod.unescape(rj.company)).strip() if rj.company else None
    location = _WS.sub(" ", html_mod.unescape(rj.location)).strip() if rj.location else None

    description_html = rj.description_html
    description = strip_html(description_html) if description_html else None
    # keep _html only when there is actual markup worth rendering
    if description_html and not _looks_like_html(html_mod.unescape(description_html)):
        description_html = None

    remote_flag = detect_remote(title, location, rj.remote_hint)
    geo_flags = detect_geo_flags(title, location, description)

    posted_at = parse_date(rj.posted_raw)
    confident = posted_at is not None and not rj.posted_is_modified
    updated_at_src = parse_date(rj.updated_raw)

    url_fp, content_fp = fingerprint(
        company, title, rj.apply_url, location, remote_flag,
        content_fp_override=rj.content_fp_override,
    )

    s_min, s_max, s_cur, s_period = rj.salary_min, rj.salary_max, rj.salary_currency, rj.salary_period
    if s_min is None and s_max is None:
        s_min, s_max, s_cur, s_period = parse_salary(rj.salary_raw)

    return Job(
        url_fp=url_fp,
        content_fp=content_fp,
        title=title,
        company=company,
        location_raw=location,
        remote_flag=remote_flag,
        geo_flags=geo_flags,
        employment_type=rj.employment_type,
        salary_raw=rj.salary_raw,
        salary_min=s_min,
        salary_max=s_max,
        salary_currency=s_cur or rj.salary_currency,
        salary_period=s_period or rj.salary_period,
        description=description,
        description_html=description_html,
        apply_url=rj.apply_url,
        posted_at=posted_at,
        posted_at_confident=confident,
        updated_at_src=updated_at_src,
        source=rj.source,
        source_job_id=rj.source_job_id,
        source_url=rj.source_url,
    )
