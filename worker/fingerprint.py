"""Dedupe fingerprints.

Two per job, matched on either at write time:

- url_fp:     hash of the normalised apply URL. Null when the host is a known
              aggregator/redirect — a redirect URL identifies the listing, not the job.
- content_fp: always computed: sha1(company | normalised_title | geo_key).

One fingerprint alone misses the most common duplicate pair: the aggregator
copy (redirect URL) and the company's own ATS copy (clean URL).
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

# Hosts whose apply URLs point at their own listing pages or redirects,
# not at the company's application page. Suffix-matched (covers subdomains).
AGGREGATOR_HOSTS = {
    "remoteok.com",
    "remotive.com",
    "jobicy.com",
    "himalayas.app",
    "arbeitnow.com",
    "workingnomads.com",
    "themuse.com",
    "weworkremotely.com",
    "joblet.ai",
    "news.ycombinator.com",
    "jobgether.com",
}

# Trailing location/mode suffixes on titles: "Backend Engineer (Remote)",
# "Data Analyst - Europe", "ML Engineer — EMEA (f/m/d)".
_TITLE_SUFFIX = re.compile(
    r"""(
        \s*[-–—:|]\s*[^-–—:|]{0,40}$   # trailing "- Europe", "| Remote"
      | \s*\((?:remote|hybrid|[^)]{0,30}(?:remote|europe|emea|usa?|uk|worldwide)[^)]{0,10})\)\s*$
      | \s*\((?:f/m/d|m/f/d|m/w/d|all\ genders)\)\s*$
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def is_aggregator_host(host: str) -> bool:
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS)


def normalise_url(url: str) -> str:
    """lowercase host, strip www., strip query/fragment, strip trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return f"{host}{path}"


def normalised_title(title: str) -> str:
    """Strip punctuation, collapse whitespace, drop trailing location suffixes."""
    t = title.strip()
    # Only strip a suffix if something meaningful remains before it.
    stripped = _TITLE_SUFFIX.sub("", t)
    if len(stripped) >= 8:
        t = stripped
    t = _PUNCT.sub(" ", t.lower())
    return _WS.sub(" ", t).strip()


def geo_key(location: str | None, remote_flag: bool) -> str:
    """'remote' for remote roles, else the last comma segment of the location
    (usually the country), lowercased. Remote-first so per-country syndication
    of the same remote role collapses to one fingerprint."""
    if remote_flag:
        return "remote"
    if not location:
        return ""
    return location.split(",")[-1].strip().lower()


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def url_fingerprint(apply_url: str) -> str | None:
    try:
        parts = urlsplit(apply_url)
    except ValueError:
        return None
    if not parts.netloc or is_aggregator_host(parts.netloc):
        return None
    return _sha1(normalise_url(apply_url))


def content_fingerprint(company: str | None, title: str, location: str | None,
                        remote_flag: bool) -> str:
    key = "|".join([
        (company or "").strip().lower(),
        normalised_title(title),
        geo_key(location, remote_flag),
    ])
    return _sha1(key)


def fingerprint(company: str | None, title: str, apply_url: str,
                location: str | None, remote_flag: bool,
                content_fp_override: str | None = None) -> tuple[str | None, str]:
    """Returns (url_fp, content_fp)."""
    if content_fp_override:  # HN comments: no reliable company/title/URL
        return None, content_fp_override
    return (url_fingerprint(apply_url),
            content_fingerprint(company, title, location, remote_flag))
