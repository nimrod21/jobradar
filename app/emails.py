"""Reply detection over IMAP (stdlib imaplib, app passwords, read-only).

Matching is deliberately conservative: a missed match costs a glance at the
inbox; a false match lies about the funnel. The heuristics are pure
functions; the IMAP fetch is a thin wrapper.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
from datetime import datetime, timedelta, timezone

from .sanitize import sanitize_html

# Known ATS relays: sender proves nothing about the company, so these
# require the subject to mention it instead.
ATS_DOMAINS = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co",
               "ashbyhq.com", "workable.com", "workablemail.com",
               "smartrecruiters.com", "myworkday.com", "icims.com", "breezy.hr")

_LEGAL = re.compile(r"\b(inc|llc|ltd|gmbh|corp|co|io|labs|hq)\b\.?", re.IGNORECASE)
_SNIPPET_LEN = 200

IMAP_PRESETS = {"gmail": "imap.gmail.com", "yahoo": "imap.mail.yahoo.com",
                "outlook": "outlook.office365.com"}


def company_tokens(company: str | None) -> list[str]:
    """Normalised tokens of a company name worth matching on (>= 4 chars,
    legal suffixes stripped)."""
    if not company:
        return []
    cleaned = _LEGAL.sub(" ", company.lower())
    tokens = re.split(r"[^a-z0-9]+", cleaned)
    return [t for t in tokens if len(t) >= 4]


def match_email(from_addr: str, display_name: str, subject: str,
                company: str | None, title: str | None) -> bool:
    """Does this message plausibly come from `company` about `title`?"""
    tokens = company_tokens(company)
    if not tokens:
        return False
    domain = from_addr.rsplit("@", 1)[-1].lower() if "@" in from_addr else ""
    name_l = (display_name or "").lower()
    subj_l = (subject or "").lower()

    is_ats = any(domain == d or domain.endswith("." + d) for d in ATS_DOMAINS)
    if is_ats:
        # relay sender: the subject or display name must carry the company
        return any(t in subj_l or t in name_l for t in tokens)

    # direct mail: company token in the sender's own domain or display name
    if any(t in domain for t in tokens):
        return True
    company_l = (company or "").lower().strip()
    return bool(company_l) and (company_l in name_l or company_l in subj_l)


def decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def extract_body(msg: email.message.Message) -> tuple[str, int]:
    """(sanitised full body, attachment count). Prefers text/plain."""
    plain, html, attachments = None, None, 0
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            attachments += 1
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
            text = payload.decode(part.get_content_charset() or "utf-8",
                                  errors="replace") if payload else ""
        except (LookupError, TypeError):
            continue
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    if plain and plain.strip():
        body = plain.strip()
    elif html:
        body = sanitize_html(html) or ""
    else:
        body = ""
    return body[:20000], attachments


def strip_html_snippet(body: str) -> str:
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text).strip()[:_SNIPPET_LEN]


def check_account(account: dict, applied_jobs: list[dict],
                  since: datetime) -> list[dict]:
    """Connect, scan headers since `since`, return matches:
    [{job_id, msg_id, from_addr, subject, snippet, body, attachments, received_at}]
    Raises imaplib.IMAP4.error / OSError on connection problems.
    """
    host = account.get("imap_host") or IMAP_PRESETS.get(
        account.get("provider", ""), "")
    conn = imaplib.IMAP4_SSL(host, timeout=30)
    matches: list[dict] = []
    try:
        conn.login(account["address"], account["app_password"])
        conn.select("INBOX", readonly=True)
        date_str = since.strftime("%d-%b-%Y")
        _, data = conn.search(None, f'(SINCE "{date_str}")')
        ids = data[0].split()[-300:]  # cap per check

        for mid in reversed(ids):
            _, hdata = conn.fetch(
                mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if not hdata or not hdata[0]:
                continue
            hdr = email.message_from_bytes(hdata[0][1])
            display, from_addr = email.utils.parseaddr(decode_header(hdr.get("From")))
            subject = decode_header(hdr.get("Subject"))
            msg_id = (hdr.get("Message-ID") or "").strip() or f"{account['address']}:{mid.decode()}"

            hit = next((j for j in applied_jobs
                        if match_email(from_addr, display, subject,
                                       j.get("company"), j.get("title"))), None)
            if not hit:
                continue

            _, fdata = conn.fetch(mid, "(BODY.PEEK[])")
            body, attachments = ("", 0)
            if fdata and fdata[0]:
                body, attachments = extract_body(email.message_from_bytes(fdata[0][1]))
            received = None
            try:
                received = email.utils.parsedate_to_datetime(hdr.get("Date"))
            except (TypeError, ValueError):
                pass
            matches.append({
                "job_id": hit["id"], "msg_id": msg_id, "from_addr": from_addr,
                "subject": subject, "snippet": strip_html_snippet(body),
                "body": body, "attachments": attachments,
                "received_at": received,
            })
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return matches


def default_since(applied_jobs: list[dict]) -> datetime:
    earliest = min((j["apply_clicked_at"] for j in applied_jobs
                    if j.get("apply_clicked_at")), default=None)
    if earliest is None:
        return datetime.now(timezone.utc) - timedelta(days=14)
    if isinstance(earliest, str):
        earliest = datetime.fromisoformat(earliest)
    return earliest - timedelta(days=2)
