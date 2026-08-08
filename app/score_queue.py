"""Background fit-scoring queue with multi-provider failover.

Providers are OpenAI-compatible endpoints tried in config order; one that
rate-limits or errors goes on a cooldown and the next takes over, so free
tiers stack into something that effectively never runs out. Parse failures
retry once with the error appended, then write failed=true so the job never
loops. Transient failures (all providers down) drop the job silently — it
re-queues on the next tracker open.
"""

from __future__ import annotations

import threading
import time

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .scoring import build_messages, parse_verdict

_DEFAULT_BASE = "https://openrouter.ai/api/v1"
COOLDOWN_SECONDS = 15 * 60


def providers_from_cfg(cfg: dict) -> list[dict]:
    """[[scoring.providers]] list; falls back to the legacy flat fields so
    old configs keep working."""
    provs = []
    for p in cfg.get("providers", []):
        if p.get("api_base") and (p.get("api_key") or _is_local(p.get("api_base", ""))):
            provs.append({
                "name": p.get("name") or p["api_base"].split("/")[2],
                "api_base": p["api_base"].rstrip("/"),
                "api_key": p.get("api_key", ""),
                "model": p.get("model", ""),
            })
    if not provs and (cfg.get("openrouter_api_key") or cfg.get("api_key")):
        provs.append({
            "name": "openrouter",
            "api_base": (cfg.get("api_base") or _DEFAULT_BASE).rstrip("/"),
            "api_key": cfg.get("openrouter_api_key") or cfg.get("api_key"),
            "model": cfg.get("model", ""),
        })
    return provs


def _is_local(base: str) -> bool:
    return "localhost" in base or "127.0.0.1" in base


def eligible_providers(providers: list[dict], cooldowns: dict[str, float],
                       now: float) -> list[dict]:
    """Config order, minus anyone still cooling down. Pure — tested."""
    return [p for p in providers if cooldowns.get(p["name"], 0) <= now]


class ScoreQueue:
    def __init__(self, database_url: str, cfg: dict):
        self._url = database_url
        self._providers = providers_from_cfg(cfg)
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()
        self._queue: list[int] = []
        self._queued: set[int] = set()
        self._results: list[dict] = []
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._providers)

    def provider_status(self) -> list[dict]:
        now = time.time()
        return [{"name": p["name"], "api_base": p["api_base"], "model": p["model"],
                 "cooling_s": max(0, int(self._cooldowns.get(p["name"], 0) - now))}
                for p in self._providers]

    def enqueue(self, job_ids: list[int]) -> int:
        if not self.enabled:
            return 0
        with self._lock:
            fresh = [j for j in job_ids if j not in self._queued]
            self._queue.extend(fresh)
            self._queued.update(fresh)
            if fresh and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            return len(fresh)

    def drain(self) -> dict:
        with self._lock:
            out, self._results = self._results, []
            active = bool(self._queue) or (self._thread is not None
                                           and self._thread.is_alive())
        return {"active": active, "scored": out}

    # -- worker thread -----------------------------------------------------

    def _run(self) -> None:
        conn = psycopg.connect(self._url, autocommit=True, row_factory=dict_row)
        try:
            with conn.cursor() as cur:
                cur.execute("select * from profile where id = 1")
                profile = cur.fetchone()
            if not profile:
                return
            while True:
                with self._lock:
                    if not self._queue:
                        return
                    job_id = self._queue.pop(0)
                try:
                    result = self._score_one(conn, job_id, profile)
                except Exception:  # noqa: BLE001 — transient; re-queued next open
                    result = None
                with self._lock:
                    self._queued.discard(job_id)
                    if result:
                        self._results.append(result)
        finally:
            conn.close()

    def _score_one(self, conn, job_id: int, profile: dict) -> dict | None:
        with conn.cursor() as cur:
            cur.execute(
                """select id, title, company, location_raw, remote_flag, geo_flags,
                          salary_raw, employment_type, description
                   from jobs where id = %s""", (job_id,))
            job = cur.fetchone()
        if not job:
            return None

        messages = build_messages(dict(profile), dict(job))
        verdict, parse_error, used = None, None, None
        for attempt in range(2):
            text, used = self._call(messages if attempt == 0 else messages + [
                {"role": "user",
                 "content": f"Your previous reply was invalid ({parse_error}). "
                            "Return ONLY the JSON object."}])
            if text is None:
                return None  # every provider down — leave unscored
            try:
                verdict = parse_verdict(text)
                break
            except ValueError as e:
                parse_error = str(e)

        model_tag = f"{used['name']}:{used['model']}" if used else "?"
        with conn.cursor() as cur:
            if verdict is None:
                cur.execute(
                    """insert into job_scores (job_id, profile_version, failed, model)
                       values (%s, %s, true, %s)
                       on conflict (job_id) do update
                         set failed = true, profile_version = excluded.profile_version,
                             model = excluded.model, created_at = now()""",
                    (job_id, profile["version"], model_tag))
                return {"job_id": job_id, "failed": True}
            cur.execute(
                """insert into job_scores (job_id, profile_version, score, label,
                                           verdict, model, failed)
                   values (%s, %s, %s, %s, %s, %s, false)
                   on conflict (job_id) do update
                     set profile_version = excluded.profile_version,
                         score = excluded.score, label = excluded.label,
                         verdict = excluded.verdict, model = excluded.model,
                         failed = false, created_at = now()""",
                (job_id, profile["version"], verdict["score"], verdict["label"],
                 Jsonb(verdict), model_tag))
        return {"job_id": job_id, "score": verdict["score"], "label": verdict["label"],
                "one_liner": verdict["one_liner"]}

    # -- provider rotation ---------------------------------------------------

    def _call(self, messages: list[dict]) -> tuple[str | None, dict | None]:
        for p in eligible_providers(self._providers, self._cooldowns, time.time()):
            text = self._call_provider(p, messages)
            if text is not None:
                return text, p
            self._cooldowns[p["name"]] = time.time() + COOLDOWN_SECONDS
        return None, None

    def _call_provider(self, p: dict, messages: list[dict]) -> str | None:
        headers = {"HTTP-Referer": "https://github.com/nimrod21/jobradar",
                   "X-Title": "JobRadar"}
        if p["api_key"]:
            headers["Authorization"] = f"Bearer {p['api_key']}"
        try:
            r = httpx.post(
                f"{p['api_base']}/chat/completions",
                headers=headers,
                json={"model": p["model"], "messages": messages, "temperature": 0.2},
                timeout=90,
            )
            data = r.json()
            if isinstance(data, list):  # Gemini wraps errors in a list
                data = data[0] if data else {}
            if r.status_code != 200 or "error" in data:
                return None
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None

    def test_connection(self, name: str = "") -> dict:
        """Test one provider by name, or the first eligible one."""
        targets = [p for p in self._providers if not name or p["name"] == name]
        if not targets:
            return {"ok": False, "error": "No such provider configured."}
        p = targets[0]
        text = self._call_provider(p, [{"role": "user",
                                        "content": "Reply with the single word: ok"}])
        if text is None:
            return {"ok": False, "error": f"{p['name']}: no response from "
                                          f"{p['api_base']} with model {p['model']}."}
        return {"ok": True, "name": p["name"], "model": p["model"]}
