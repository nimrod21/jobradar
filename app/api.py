"""Python <-> JS API. JS never builds SQL; sanitisation happens here.

All methods return plain JSON-able dicts. The tracker query follows
04-TRACKERS.md: websearch_to_tsquery over the weighted search_vec,
title matches ranked above description matches.
"""

from __future__ import annotations

import re
import webbrowser
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from worker.geo import REGION_GROUPS
from .sanitize import sanitize_html

_WINDOWS = {"24h": "24 hours", "7d": "7 days", "14d": "14 days", "30d": "30 days"}
_STATUSES = {"new", "interesting", "applied", "replied", "rejected", "dead"}
_HARD_BLOCKERS = ["hybrid", "onsite", "on-site", "in-office",
                  "must be based in", "visa sponsorship: no"]
# Georgia the country, not the US state (SQL-side veto for region mode)
_US_GEORGIA_SQL = r"georgia\s*,\s*(united states|usa?)|,\s*ga\b|\bga\s*,\s*usa?|\batlanta\b"

_JOB_COLS = """j.id, j.title, j.company, j.location_raw, j.remote_flag, j.geo_flags,
  j.salary_raw, j.employment_type, j.status, j.apply_url, j.notes,
  j.posted_at, j.posted_at_confident, j.first_seen_at, j.apply_clicked_at, j.applied_at,
  (select count(*) from job_sources s where s.job_id = j.id) as source_count,
  (select array_agg(s.source) from job_sources s where s.job_id = j.id) as sources"""


def _tsquery(terms: list[str]) -> str:
    """['AI', 'tool calling'] -> 'AI or \"tool calling\"' (websearch syntax)."""
    return " or ".join(f'"{t}"' if " " in t else t for t in (t.strip() for t in terms) if t)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _row_out(row: dict) -> dict:
    return {k: _iso(v) for k, v in row.items()}


class Api:
    def __init__(self, database_url: str, config: dict, save_config):
        self._url = database_url
        self._config = config
        self._save_config = save_config
        self._conn = None

    # -- connection --------------------------------------------------------

    def _db(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._url, autocommit=True, row_factory=dict_row)
        return self._conn

    def ping(self) -> dict:
        try:
            with self._db().cursor() as cur:
                cur.execute("select count(*) n from jobs")
                jobs = cur.fetchone()["n"]
            return {"ok": True, "jobs": jobs}
        except psycopg.Error as e:
            self._conn = None
            return {"ok": False, "error": str(e).strip().split("\n")[0]}

    # -- trackers ----------------------------------------------------------

    def list_trackers(self) -> list[dict]:
        with self._db().cursor() as cur:
            cur.execute("select * from trackers order by created_at, id")
            trackers = [_row_out(t) for t in cur.fetchall()]
            for t in trackers:
                where, params = self._tracker_where(t)
                cur.execute(
                    f"select count(*) n from jobs j where {where} and j.viewed_at is null",
                    params,
                )
                t["new_count"] = cur.fetchone()["n"]
        return trackers

    def _tracker_where(self, t: dict) -> tuple[str, dict]:
        clauses = ["j.status <> 'dead'"]
        params: dict = {}
        if t["include_terms"]:
            clauses.append("j.search_vec @@ websearch_to_tsquery('english', %(inc)s)")
            params["inc"] = _tsquery(t["include_terms"])
        if t["exclude_terms"]:
            clauses.append("not j.search_vec @@ websearch_to_tsquery('english', %(exc)s)")
            params["exc"] = _tsquery(t["exclude_terms"])
        if t["exclude_companies"]:
            clauses.append("lower(coalesce(j.company,'')) <> all(%(exco)s)")
            params["exco"] = [c.lower() for c in t["exclude_companies"]]
        if t["date_window"] in _WINDOWS:
            clauses.append(f"j.posted_at > now() - interval '{_WINDOWS[t['date_window']]}'")

        mode, value = t["location_mode"], t.get("location_value") or ""
        if mode == "remote":
            clauses.append("j.remote_flag and not (j.geo_flags && %(blockers)s)")
            params["blockers"] = _HARD_BLOCKERS
        elif mode == "text" and value:
            # comma-separated custom terms, any match — the non-hardcoded
            # counterpart to the region presets
            ors = []
            for i, term in enumerate(t.strip() for t in value.split(",")):
                if not term:
                    continue
                params[f"locv{i}"] = f"%{term}%"
                ors.append(f"(j.location_raw ilike %(locv{i})s or j.title ilike %(locv{i})s"
                           f" or j.description ilike %(locv{i})s)")
            if ors:
                clauses.append("(" + " or ".join(ors) + ")")
        elif mode == "region" and value in REGION_GROUPS:
            clauses.append("j.location_raw ilike any(%(regterms)s)")
            params["regterms"] = [f"%{term}%" for term in REGION_GROUPS[value]]
            if value in ("georgia", "caucasus"):
                clauses.append("j.location_raw !~* %(gaveto)s")
                params["gaveto"] = _US_GEORGIA_SQL
        return " and ".join(clauses), params

    # NB: no parameter may be named `window` — pywebview mirrors Python param
    # names into the generated JS stub, and it would shadow the global window.
    def open_tracker(self, tracker_id: int, query: str = "", win: str = "") -> dict:
        """A job stays 'new' until it is individually opened (get_job) —
        opening the tracker itself marks nothing as read."""
        with self._db().cursor() as cur:
            cur.execute("select * from trackers where id = %s", (tracker_id,))
            t = cur.fetchone()
        if not t:
            return {"jobs": []}
        return {"jobs": self._query_jobs(t, query, win), "tracker": _row_out(t)}

    def search(self, tracker_id: int, query: str = "", win: str = "") -> dict:
        """`win` is a session-only override of the tracker's date window."""
        return self.open_tracker(tracker_id, query, win)

    def _query_jobs(self, t: dict, query: str, win: str = "") -> list[dict]:
        t = dict(t)
        if win in (*_WINDOWS, "all"):
            t["date_window"] = win
        where, params = self._tracker_where(t)
        rank = "j.posted_at desc nulls last"
        if query.strip():
            where += " and j.search_vec @@ websearch_to_tsquery('english', %(q)s)"
            params["q"] = query.strip()
            rank = ("ts_rank(j.search_vec, websearch_to_tsquery('english', %(q)s)) desc, "
                    + rank)
        with self._db().cursor() as cur:
            cur.execute(
                f"""select {_JOB_COLS}, j.viewed_at is null as is_new
                    from jobs j where {where}
                    order by {rank} limit 2000""",
                params,
            )
            return [_row_out(r) for r in cur.fetchall()]

    def save_tracker(self, fields: dict) -> dict:
        cols = {
            "name": (fields.get("name") or "").strip() or "Untitled",
            "include_terms": [t for t in fields.get("include_terms", []) if t.strip()],
            "exclude_terms": [t for t in fields.get("exclude_terms", []) if t.strip()],
            "exclude_companies": [t for t in fields.get("exclude_companies", []) if t.strip()],
            "date_window": fields.get("date_window") or "14d",
            "location_mode": fields.get("location_mode") or "any",
            "location_value": (fields.get("location_value") or "").strip() or None,
        }
        if cols["location_mode"] == "region" and cols["location_value"]:
            cols["location_value"] = cols["location_value"].lower()
        with self._db().cursor() as cur:
            if fields.get("id"):
                cur.execute(
                    """update trackers set name=%(name)s, include_terms=%(include_terms)s,
                       exclude_terms=%(exclude_terms)s, exclude_companies=%(exclude_companies)s,
                       date_window=%(date_window)s, location_mode=%(location_mode)s,
                       location_value=%(location_value)s where id=%(id)s returning id""",
                    {**cols, "id": fields["id"]})
            else:
                cur.execute(
                    """insert into trackers (name, include_terms, exclude_terms,
                       exclude_companies, date_window, location_mode, location_value)
                       values (%(name)s,%(include_terms)s,%(exclude_terms)s,
                       %(exclude_companies)s,%(date_window)s,%(location_mode)s,
                       %(location_value)s) returning id""", cols)
            return {"id": cur.fetchone()["id"]}

    def delete_tracker(self, tracker_id: int) -> dict:
        with self._db().cursor() as cur:
            cur.execute("delete from trackers where id = %s", (tracker_id,))
        return {"ok": True}

    def exclude_company(self, tracker_id: int, company: str) -> dict:
        if not company:
            return {"ok": False}
        with self._db().cursor() as cur:
            cur.execute(
                """update trackers set exclude_companies =
                     (select array(select distinct unnest(exclude_companies || %s::text)))
                   where id = %s""", (company, tracker_id))
        return {"ok": True}

    # -- jobs --------------------------------------------------------------

    def get_job(self, job_id: int) -> dict | None:
        """Opening a job in the detail pane is what marks it read."""
        with self._db().cursor() as cur:
            cur.execute(
                "update jobs set viewed_at = coalesce(viewed_at, now()) where id = %s",
                (job_id,))
            cur.execute(
                f"select {_JOB_COLS}, j.description, j.description_html, false as is_new "
                "from jobs j where j.id = %s", (job_id,))
            row = cur.fetchone()
        if not row:
            return None
        out = _row_out(row)
        out["description_html"] = sanitize_html(row["description_html"])
        return out

    def set_status(self, job_id: int, status: str) -> dict:
        if status not in _STATUSES:
            return {"ok": False}
        with self._db().cursor() as cur:
            cur.execute("update jobs set status = %s where id = %s", (status, job_id))
        return {"ok": True}

    def save_note(self, job_id: int, text: str) -> dict:
        with self._db().cursor() as cur:
            cur.execute("update jobs set notes = %s where id = %s",
                        (text.strip() or None, job_id))
        return {"ok": True}

    def click_apply(self, job_id: int) -> dict:
        with self._db().cursor() as cur:
            cur.execute(
                """update jobs set apply_clicked_at = coalesce(apply_clicked_at, now())
                   where id = %s returning apply_url""", (job_id,))
            row = cur.fetchone()
        if not row:
            return {"ok": False}
        webbrowser.open(row["apply_url"])
        return {"ok": True}

    def open_url(self, url: str) -> dict:
        if re.match(r"^https?://", url or ""):
            webbrowser.open(url)
        return {"ok": True}

    # -- applied page ------------------------------------------------------

    def applied_page(self) -> dict:
        with self._db().cursor() as cur:
            cur.execute(
                f"""select {_JOB_COLS}, false as is_new from jobs j
                    where j.apply_clicked_at is not null and j.status <> 'applied'
                    order by j.apply_clicked_at desc""")
            to_confirm = [_row_out(r) for r in cur.fetchall()]
            cur.execute(
                f"""select {_JOB_COLS}, false as is_new from jobs j
                    where j.status = 'applied'
                    order by j.applied_at desc nulls last""")
            applied = [_row_out(r) for r in cur.fetchall()]
        return {"to_confirm": to_confirm, "applied": applied}

    def applied_count(self) -> int:
        with self._db().cursor() as cur:
            cur.execute("""select count(*) n from jobs
                           where apply_clicked_at is not null and status <> 'applied'""")
            return cur.fetchone()["n"]

    def confirm_applied(self, job_id: int) -> dict:
        with self._db().cursor() as cur:
            cur.execute(
                """update jobs set status = 'applied', applied_at = now()
                   where id = %s""", (job_id,))
        return {"ok": True}

    def remove_applied(self, job_id: int) -> dict:
        """Un-record the click; the job keeps its previous status."""
        with self._db().cursor() as cur:
            cur.execute("update jobs set apply_clicked_at = null where id = %s", (job_id,))
        return {"ok": True}

    # -- config ------------------------------------------------------------

    def get_config(self) -> dict:
        return {"theme": self._config.get("theme", "dark")}

    def set_theme(self, theme: str) -> dict:
        if theme in ("dark", "light"):
            self._config["theme"] = theme
            self._save_config(self._config)
        return {"ok": True}
