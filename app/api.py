"""Python <-> JS API. JS never builds SQL; sanitisation happens here.

All methods return plain JSON-able dicts. The tracker query follows
04-TRACKERS.md: websearch_to_tsquery over the weighted search_vec,
title matches ranked above description matches.
"""

from __future__ import annotations

import re
import webbrowser
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from worker.geo import REGION_GROUPS
from .sanitize import sanitize_html
from .score_queue import ScoreQueue
from .scoring import profile_version

_WINDOWS = {"24h": "24 hours", "7d": "7 days", "14d": "14 days", "30d": "30 days"}
_STATUSES = {"new", "interesting", "applied", "replied", "rejected", "dead"}
_WORK_MODES = {"remote", "hybrid", "onsite"}
_HYBRID_FLAGS = ["hybrid"]
_ONSITE_FLAGS = ["onsite", "on-site", "in-office"]
# Georgia the country, not the US state (SQL-side veto for region mode)
_US_GEORGIA_SQL = r"georgia\s*,\s*(united states|usa?)|,\s*ga\b|\bga\s*,\s*usa?|\batlanta\b"

_JOB_COLS = """j.id, j.title, j.company, j.location_raw, j.remote_flag, j.geo_flags,
  j.salary_raw, j.employment_type, j.status, j.apply_url, j.notes,
  j.posted_at, j.posted_at_confident, j.first_seen_at, j.apply_clicked_at, j.applied_at,
  (select count(*) from job_sources s where s.job_id = j.id) as source_count,
  (select array_agg(s.source) from job_sources s where s.job_id = j.id) as sources,
  sc.score as fit_score, sc.label as fit_label,
  sc.verdict->>'one_liner' as fit_one_liner"""

_JOB_FROM = "jobs j left join job_scores sc on sc.job_id = j.id and not sc.failed"


def _tsquery(terms: list[str]) -> str:
    """['AI', 'tool calling'] -> 'AI or \"tool calling\"' (websearch syntax)."""
    return " or ".join(f'"{t}"' if " " in t else t for t in (t.strip() for t in terms) if t)


def _iso(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row_out(row: dict) -> dict:
    return {k: _iso(v) for k, v in row.items()}


class Api:
    def __init__(self, database_url: str, config: dict, save_config):
        self._url = database_url
        self._config = config
        self._save_config = save_config
        self._conn = None
        self._scoring_cfg = config.get("scoring") or {}
        self._squeue = ScoreQueue(database_url, self._scoring_cfg)

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
            scope = t.get("search_in") or "both"
            # expression must match the index expression exactly
            vec = {
                "title": "to_tsvector('english', coalesce(j.title, ''))",
                "description": "to_tsvector('english', coalesce(j.description, ''))",
            }.get(scope, "j.search_vec")
            clauses.append(f"{vec} @@ websearch_to_tsquery('english', %(inc)s)")
            params["inc"] = _tsquery(t["include_terms"])
        if t["exclude_terms"]:
            clauses.append("not j.search_vec @@ websearch_to_tsquery('english', %(exc)s)")
            params["exc"] = _tsquery(t["exclude_terms"])
        if t["exclude_companies"]:
            clauses.append("lower(coalesce(j.company,'')) <> all(%(exco)s)")
            params["exco"] = [c.lower() for c in t["exclude_companies"]]
        if t["date_window"] in _WINDOWS:
            clauses.append(f"j.posted_at > now() - interval '{_WINDOWS[t['date_window']]}'")

        # work mode is orthogonal to geography: OR of the selected toggles,
        # no toggles = no filter
        modes = [m for m in (t.get("work_modes") or []) if m in _WORK_MODES]
        mode_ors = []
        if "remote" in modes:
            # a "remote" job that flags hybrid/onsite isn't remote
            mode_ors.append("(j.remote_flag and not (j.geo_flags && %(wm_not_remote)s))")
            params["wm_not_remote"] = _HYBRID_FLAGS + _ONSITE_FLAGS
        if "hybrid" in modes:
            mode_ors.append("j.geo_flags && %(wm_hybrid)s")
            params["wm_hybrid"] = _HYBRID_FLAGS
        if "onsite" in modes:
            mode_ors.append("j.geo_flags && %(wm_onsite)s")
            params["wm_onsite"] = _ONSITE_FLAGS
        if mode_ors:
            clauses.append("(" + " or ".join(mode_ors) + ")")

        mode, value = t["location_mode"], (t.get("location_value") or "").strip()
        if mode == "region" and value in REGION_GROUPS:
            clauses.append("j.location_raw ilike any(%(regterms)s)")
            params["regterms"] = [f"%{term}%" for term in REGION_GROUPS[value]]
            if value == "caucasus":
                clauses.append("j.location_raw !~* %(gaveto)s")
                params["gaveto"] = _US_GEORGIA_SQL
        elif mode == "country" and value:
            # word-boundary match so "India" never matches "Indiana"
            clauses.append("j.location_raw ~* %(country_rx)s")
            params["country_rx"] = r"\m" + re.escape(value) + r"\M"
            if value.lower() == "georgia":
                clauses.append("j.location_raw !~* %(gaveto)s")
                params["gaveto"] = _US_GEORGIA_SQL
        elif mode == "place" and value:
            # free entry: comma-separated, any match, checked against
            # location, title and description
            ors = []
            for i, term in enumerate(s.strip() for s in value.split(",")):
                if not term:
                    continue
                params[f"locv{i}"] = f"%{term}%"
                ors.append(f"(j.location_raw ilike %(locv{i})s or j.title ilike %(locv{i})s"
                           f" or j.description ilike %(locv{i})s)")
            if ors:
                clauses.append("(" + " or ".join(ors) + ")")
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
                    from {_JOB_FROM} where {where}
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
            "search_in": fields.get("search_in")
                         if fields.get("search_in") in ("both", "title", "description")
                         else "both",
            "work_modes": [m for m in fields.get("work_modes", []) if m in _WORK_MODES],
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
                       date_window=%(date_window)s, search_in=%(search_in)s,
                       work_modes=%(work_modes)s, location_mode=%(location_mode)s,
                       location_value=%(location_value)s where id=%(id)s returning id""",
                    {**cols, "id": fields["id"]})
            else:
                cur.execute(
                    """insert into trackers (name, include_terms, exclude_terms,
                       exclude_companies, date_window, search_in, work_modes,
                       location_mode, location_value)
                       values (%(name)s,%(include_terms)s,%(exclude_terms)s,
                       %(exclude_companies)s,%(date_window)s,%(search_in)s,%(work_modes)s,
                       %(location_mode)s,%(location_value)s) returning id""", cols)
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
                f"select {_JOB_COLS}, sc.verdict as fit_verdict, j.description, "
                f"j.description_html, false as is_new "
                f"from {_JOB_FROM} where j.id = %s", (job_id,))
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
                f"""select {_JOB_COLS}, false as is_new from {_JOB_FROM}
                    where j.apply_clicked_at is not null and j.status <> 'applied'
                    order by j.apply_clicked_at desc""")
            to_confirm = [_row_out(r) for r in cur.fetchall()]
            cur.execute(
                f"""select {_JOB_COLS}, false as is_new from {_JOB_FROM}
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

    # -- fit scoring -------------------------------------------------------

    def get_profile(self) -> dict:
        with self._db().cursor() as cur:
            cur.execute("select * from profile where id = 1")
            row = cur.fetchone()
        out = _row_out(row) if row else {}
        out["scoring_enabled"] = self._squeue.enabled
        out["model"] = self._scoring_cfg.get("model", "")
        return out

    def save_profile(self, fields: dict) -> dict:
        cols = {
            "summary": (fields.get("summary") or "").strip() or None,
            "conf_coding": fields.get("conf_coding") or None,
            "conf_design": fields.get("conf_design") or None,
            "conf_english": fields.get("conf_english") or None,
            "needs_sponsorship": bool(fields.get("needs_sponsorship")),
            "min_salary": fields.get("min_salary") or None,
            "salary_currency": (fields.get("salary_currency") or "USD").upper()[:6],
            "tz_range": (fields.get("tz_range") or "").strip() or None,
            "contract_ok": bool(fields.get("contract_ok", True)),
            "domains_avoid": [s for s in fields.get("domains_avoid", []) if s.strip()],
            "domains_love": [s for s in fields.get("domains_love", []) if s.strip()],
            "stack_love": [s for s in fields.get("stack_love", []) if s.strip()],
            "stack_avoid": [s for s in fields.get("stack_avoid", []) if s.strip()],
            "dealbreakers": (fields.get("dealbreakers") or "").strip() or None,
        }
        cols["version"] = profile_version(cols)
        sets = ", ".join(f"{k} = %({k})s" for k in cols)
        with self._db().cursor() as cur:
            cur.execute(
                f"""insert into profile (id, {', '.join(cols)})
                    values (1, {', '.join(f'%({k})s' for k in cols)})
                    on conflict (id) do update set {sets}""", cols)
        return {"ok": True, "version": cols["version"]}

    def _unscored_ids(self, cur, where: str, params: dict, cap: int) -> list[int]:
        cur.execute(
            f"""select j.id from {_JOB_FROM}
                left join profile p on p.id = 1
                where {where}
                  and p.summary is not null
                  and (sc.job_id is null or sc.profile_version <> p.version)
                  and not exists (select 1 from job_scores f
                                  where f.job_id = j.id and f.failed
                                    and f.profile_version = p.version)
                order by j.first_seen_at desc limit %(cap)s""",
            {**params, "cap": cap})
        return [r["id"] for r in cur.fetchall()]

    def score_new(self, tracker_id: int) -> dict:
        """Auto-scoring hook: called after a tracker opens."""
        if not self._squeue.enabled or not self._scoring_cfg.get("auto", True):
            return {"queued": 0}
        with self._db().cursor() as cur:
            cur.execute("select * from trackers where id = %s", (tracker_id,))
            t = cur.fetchone()
            if not t:
                return {"queued": 0}
            where, params = self._tracker_where(dict(t))
            ids = self._unscored_ids(cur, where, params,
                                     int(self._scoring_cfg.get("cap_per_open", 20)))
        return {"queued": self._squeue.enqueue(ids)}

    def score_all_unscored(self) -> dict:
        """Dashboard catch-up button: everything unscored across enabled trackers."""
        if not self._squeue.enabled:
            return {"queued": 0}
        all_ids: list[int] = []
        with self._db().cursor() as cur:
            cur.execute("select * from trackers where enabled order by id")
            for t in cur.fetchall():
                where, params = self._tracker_where(dict(t))
                all_ids.extend(self._unscored_ids(cur, where, params, 100))
        return {"queued": self._squeue.enqueue(list(dict.fromkeys(all_ids))[:150])}

    def score_poll(self) -> dict:
        return self._squeue.drain()

    # -- dashboard stats ---------------------------------------------------

    def dashboard_stats(self) -> dict:
        with self._db().cursor() as cur:
            cur.execute("""select count(*) total,
                                  count(*) filter (where first_seen_at > now() - interval '7 days') new_week,
                                  count(*) filter (where applied_at is not null) applied,
                                  count(*) filter (where status = 'replied') replied,
                                  count(*) filter (where apply_clicked_at is not null) clicked,
                                  count(*) filter (where status = 'rejected') rejected
                           from jobs""")
            totals = _row_out(cur.fetchone())

            cur.execute("""select s.source, count(distinct j.id) apps,
                                  count(distinct j.id) filter (where j.status = 'replied') replies
                           from jobs j join job_sources s on s.job_id = j.id
                           where j.applied_at is not null
                           group by s.source having count(distinct j.id) >= 3
                           order by 3::float / count(distinct j.id) desc, 2 desc""")
            by_source = [_row_out(r) for r in cur.fetchall()]

            cur.execute("""select percentile_cont(0.5) within group
                             (order by extract(epoch from (apply_clicked_at - posted_at)) / 3600)
                           from jobs
                           where apply_clicked_at is not null and posted_at is not null
                             and posted_at_confident""")
            row = cur.fetchone()
            freshness_hours = list(row.values())[0]

            cur.execute("""select to_char(date_trunc('week', apply_clicked_at), 'MM-DD') wk,
                                  count(*) n
                           from jobs
                           where apply_clicked_at > now() - interval '8 weeks'
                           group by 1 order by 1""")
            per_week = [_row_out(r) for r in cur.fetchall()]

            cur.execute("select * from trackers where enabled order by created_at, id")
            trackers = cur.fetchall()
            pulse = []
            for t in trackers:
                where, params = self._tracker_where(dict(t))
                cur.execute(
                    f"""select date(j.first_seen_at) d, count(*) n from {_JOB_FROM}
                        where {where} and j.first_seen_at > now() - interval '14 days'
                        group by 1 order by 1""", params)
                days = {str(r["d"]): r["n"] for r in cur.fetchall()}
                pulse.append({"name": t["name"], "days": days,
                              "total": sum(days.values())})

            cur.execute("""select avg(sc.score) filter (where j.applied_at is not null) avg_applied,
                                  avg(sc.score) filter (where j.applied_at is null) avg_skipped,
                                  count(sc.score) scored
                           from job_scores sc join jobs j on j.id = sc.job_id
                           where not sc.failed""")
            fit = _row_out(cur.fetchone())
            for k in ("avg_applied", "avg_skipped"):
                if fit.get(k) is not None:
                    fit[k] = round(float(fit[k]), 1)

        return {"totals": totals, "by_source": by_source,
                "freshness_hours": round(freshness_hours, 1) if freshness_hours else None,
                "per_week": per_week, "pulse": pulse, "fit": fit}

    # -- config ------------------------------------------------------------

    def get_config(self) -> dict:
        return {"theme": self._config.get("theme", "dark"),
                "scoring_enabled": self._squeue.enabled}

    def set_theme(self, theme: str) -> dict:
        if theme in ("dark", "light"):
            self._config["theme"] = theme
            self._save_config(self._config)
        return {"ok": True}
