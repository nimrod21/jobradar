"""Background fit-scoring queue. One worker thread, own DB connection,
sequential calls (free-tier rate limits make concurrency pointless).

Transient failures (429/5xx/timeouts) drop the job silently — it gets
re-queued on the next tracker open. Parse failures retry once with the
error appended, then write failed=true so the job never loops.
"""

from __future__ import annotations

import threading

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .scoring import build_messages, parse_verdict

_DEFAULT_BASE = "https://openrouter.ai/api/v1"


class ScoreQueue:
    def __init__(self, database_url: str, cfg: dict):
        self._url = database_url
        # Any OpenAI-compatible endpoint: OpenRouter (default), OpenAI,
        # Anthropic, Groq, or local Ollama/LM Studio (no key needed there).
        self._base = (cfg.get("api_base") or _DEFAULT_BASE).rstrip("/")
        self._key = cfg.get("openrouter_api_key") or cfg.get("api_key") or ""
        self._model = cfg.get("model") or "nvidia/nemotron-3-ultra-550b-a55b:free"
        self._lock = threading.Lock()
        self._queue: list[int] = []
        self._queued: set[int] = set()
        self._results: list[dict] = []
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        # a keyless local endpoint (Ollama) is a valid setup
        return bool(self._key) or "localhost" in self._base or "127.0.0.1" in self._base

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
        """Poll: results since last drain + whether work remains."""
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
        verdict, parse_error = None, None
        for attempt in range(2):
            text = self._call(messages if attempt == 0 else messages + [
                {"role": "user",
                 "content": f"Your previous reply was invalid ({parse_error}). "
                            "Return ONLY the JSON object."}])
            if text is None:
                return None  # transient — leave unscored
            try:
                verdict = parse_verdict(text)
                break
            except ValueError as e:
                parse_error = str(e)

        with conn.cursor() as cur:
            if verdict is None:
                cur.execute(
                    """insert into job_scores (job_id, profile_version, failed, model)
                       values (%s, %s, true, %s)
                       on conflict (job_id) do update
                         set failed = true, profile_version = excluded.profile_version,
                             model = excluded.model, created_at = now()""",
                    (job_id, profile["version"], self._model))
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
                 Jsonb(verdict), self._model))
        return {"job_id": job_id, "score": verdict["score"], "label": verdict["label"],
                "one_liner": verdict["one_liner"]}

    def _call(self, messages: list[dict]) -> str | None:
        headers = {"HTTP-Referer": "https://github.com/nimrod21/jobradar",
                   "X-Title": "JobRadar"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        try:
            r = httpx.post(
                f"{self._base}/chat/completions",
                headers=headers,
                json={"model": self._model, "messages": messages, "temperature": 0.2},
                timeout=90,
            )
            data = r.json()
            if "error" in data:
                return None
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return None

    def test_connection(self) -> dict:
        """One tiny call for the dashboard's Test button."""
        if not self.enabled:
            return {"ok": False, "error": "No key configured (and not a local endpoint)."}
        text = self._call([{"role": "user", "content": "Reply with the single word: ok"}])
        if text is None:
            return {"ok": False, "error": f"No response from {self._base} with model {self._model}."}
        return {"ok": True, "model": self._model, "base": self._base}
