"""Fit scoring: prompt builder and verdict parser. Pure functions — the
HTTP call lives in the queue, these are what the tests cover.

The three interview-confidence sliders are the calibration: the same job is
Safe for one person and Reach for another, and the model is told exactly why.
"""

from __future__ import annotations

import hashlib
import json

MAX_DESC_CHARS = 6000
LABELS = ("safe", "stretch", "reach")
DEALBREAKER_MAX_SCORE = 20

_PROFILE_FIELDS = ("summary", "conf_coding", "conf_design", "conf_english",
                   "conf_behavioral", "needs_sponsorship", "min_salary",
                   "salary_target", "salary_period", "salary_currency",
                   "tz_range", "contract_ok", "domains_avoid", "domains_love",
                   "stack_love", "stack_avoid", "dealbreakers", "years_exp",
                   "current_title", "target_roles", "target_level", "notice",
                   "education", "languages", "citizenship")


def profile_version(profile: dict) -> str:
    key = json.dumps({f: profile.get(f) for f in _PROFILE_FIELDS},
                     sort_keys=True, default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


_SYSTEM = """You are a strict job-fit evaluator working for one specific candidate.
Score how well a job posting fits THIS candidate, using their self-assessed
interview confidences to calibrate:

- label "safe": they would very likely get and pass the interview process
- label "stretch": realistic but demanding; some gaps or a tough process
- label "reach": unlikely given their profile or confidences

Low coding-interview confidence makes algorithm-heavy hiring processes a
stretch/reach even when skills match. Low design confidence does the same
for staff/architect roles. Judge the process as well as the job.

Hard rules:
- Any dealbreaker or hard-constraint violation goes in "dealbreaker_hits"
  and caps the score at 20.
- Score 0-100. Be honest, not encouraging. Most jobs are a poor fit.
- reasons_for: 2-3 short concrete phrases. reasons_against: 1-2. one_liner:
  a single decisive sentence.

Return ONLY a JSON object, no prose, no code fences:
{"score": int, "label": "safe"|"stretch"|"reach", "one_liner": str,
 "reasons_for": [str], "reasons_against": [str], "dealbreaker_hits": [str]}"""


def _fmt_list(items) -> str:
    return ", ".join(items) if items else "-"


def build_messages(profile: dict, job: dict) -> list[dict]:
    p = profile
    desc = (job.get("description") or "")[:MAX_DESC_CHARS]

    def money(v):
        return f"{float(v):g}" if v is not None else None

    salary = "-"
    if p.get("min_salary") or p.get("salary_target"):
        per = p.get("salary_period") or "month"
        cur = p.get("salary_currency") or ""
        lo, tgt = money(p.get("min_salary")), money(p.get("salary_target"))
        salary = (f"floor {lo}" if lo else "") + (f", target {tgt}" if tgt else "")
        salary = f"{salary.strip(', ')} {cur}/{per}"

    prof_block = f"""CANDIDATE
Summary: {p.get('summary') or '-'}
Experience: {p.get('years_exp') or '?'} years, currently {p.get('current_title') or '-'}
Target roles: {_fmt_list(p.get('target_roles'))} (level: {p.get('target_level') or 'any'})
Interview confidence (1-10): live-coding/algorithms {p.get('conf_coding') or '?'}, system design {p.get('conf_design') or '?'}, spoken English {p.get('conf_english') or '?'}, behavioral/self-presentation {p.get('conf_behavioral') or '?'}
Citizenship/work authorization: {p.get('citizenship') or '-'}; needs visa sponsorship: {'yes' if p.get('needs_sponsorship') else 'no'}
Salary expectation: {salary}
Timezone: {p.get('tz_range') or '-'}; availability: {p.get('notice') or '-'}
Contract/freelance acceptable: {'yes' if p.get('contract_ok', True) else 'no'}
Education: {p.get('education') or '-'}
Languages: {_fmt_list(p.get('languages'))}
Domains to avoid (dealbreaker): {_fmt_list(p.get('domains_avoid'))}
Domains preferred: {_fmt_list(p.get('domains_love'))}
Stack preferred: {_fmt_list(p.get('stack_love'))}
Stack to avoid: {_fmt_list(p.get('stack_avoid'))}
Other dealbreakers: {p.get('dealbreakers') or '-'}"""

    job_block = f"""JOB
Title: {job.get('title')}
Company: {job.get('company') or '-'}
Location: {job.get('location_raw') or '-'}
Remote: {'yes' if job.get('remote_flag') else 'not stated'}
Salary: {job.get('salary_raw') or '-'}
Type: {job.get('employment_type') or '-'}
Red flags detected: {_fmt_list(job.get('geo_flags'))}
Description:
{desc or '-'}"""

    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prof_block + "\n\n" + job_block}]


def parse_verdict(text: str) -> dict:
    """Extract and validate the verdict JSON. Raises ValueError on garbage;
    the caller retries once with the error appended, then marks failed."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ValueError("top level is not an object")

    score = raw.get("score")
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    if not isinstance(score, int) or isinstance(score, bool):
        raise ValueError(f"score is not an int: {score!r}")
    score = max(0, min(100, score))

    label = raw.get("label")
    if label not in LABELS:
        raise ValueError(f"bad label: {label!r}")

    def _strs(key, limit):
        v = raw.get(key) or []
        if not isinstance(v, list):
            raise ValueError(f"{key} is not a list")
        return [str(s).strip() for s in v if str(s).strip()][:limit]

    hits = _strs("dealbreaker_hits", 5)
    if hits:
        score = min(score, DEALBREAKER_MAX_SCORE)

    return {
        "score": score,
        "label": label,
        "one_liner": str(raw.get("one_liner") or "").strip()[:200],
        "reasons_for": _strs("reasons_for", 3),
        "reasons_against": _strs("reasons_against", 2),
        "dealbreaker_hits": hits,
    }
