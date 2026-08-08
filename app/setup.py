"""Setup wizard backend: migration runner, GitHub worker wiring, AI presets.

Everything here is the "app does it for you" half of onboarding — the user
registers accounts and pastes strings; these functions do the plumbing.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx
import psycopg

_GH = "https://api.github.com"

AI_PRESETS: dict[str, dict] = {
    "groq": {"api_base": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile",
             "key_url": "https://console.groq.com/keys"},
    "google": {"api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-3.1-flash-lite-preview",
               "key_url": "https://aistudio.google.com/apikey"},
    "openrouter": {"api_base": "https://openrouter.ai/api/v1",
                   "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                   "key_url": "https://openrouter.ai/settings/keys"},
    "cerebras": {"api_base": "https://api.cerebras.ai/v1",
                 "model": "gemma-4-31b",
                 "key_url": "https://cloud.cerebras.ai"},
    "ollama": {"api_base": "http://localhost:11434/v1",
               "model": "llama3.2",
               "key_url": "https://ollama.com/download"},
}


def migrations_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "migrations"  # noqa: SLF001
    return Path(__file__).resolve().parent.parent / "migrations"


def migration_files() -> list[Path]:
    return sorted(migrations_dir().glob("*.sql"))


def test_db(url: str) -> dict:
    try:
        with psycopg.connect(url, connect_timeout=8) as conn, conn.cursor() as cur:
            cur.execute("select version()")
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e).strip().split("\n")[0][:200]}


def run_migrations(url: str) -> dict:
    """Apply migrations in filename order, tracked in schema_migrations.
    A pre-wizard database (jobs table exists, no tracking table) is marked
    fully applied rather than re-run."""
    files = migration_files()
    if not files:
        return {"ok": False, "error": "No migration files found."}
    applied: list[str] = []
    try:
        with psycopg.connect(url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("""create table if not exists schema_migrations
                               (name text primary key, applied_at timestamptz
                                not null default now())""")
                cur.execute("select name from schema_migrations")
                done = {r[0] for r in cur.fetchall()}
                if not done:
                    cur.execute("""select count(*) from information_schema.tables
                                   where table_schema = 'public' and table_name = 'jobs'""")
                    if cur.fetchone()[0]:  # existing pre-wizard database
                        for f in files:
                            cur.execute(
                                "insert into schema_migrations (name) values (%s)"
                                " on conflict do nothing", (f.name,))
                        conn.commit()
                        return {"ok": True, "applied": [], "note": "existing database adopted"}
                for f in files:
                    if f.name in done:
                        continue
                    cur.execute(f.read_text(encoding="utf-8"))
                    cur.execute("insert into schema_migrations (name) values (%s)",
                                (f.name,))
                    conn.commit()
                    applied.append(f.name)
        return {"ok": True, "applied": applied}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e).strip().split("\n")[0][:200],
                "applied": applied}


def setup_github(token: str, database_url: str, repo: str = "") -> dict:
    """Wire the serverless worker on the user's fork: set the DATABASE_URL
    secret, enable the workflow, fire the first run. Token is used, never
    stored."""
    token = token.strip()
    if not token:
        return {"ok": False, "error": "Token is empty."}
    h = {"Authorization": f"Bearer {token}",
         "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    try:
        with httpx.Client(timeout=30, headers=h, base_url=_GH) as c:
            r = c.get("/user")
            if r.status_code != 200:
                return {"ok": False, "error": f"Token rejected (HTTP {r.status_code})."}
            login = r.json()["login"]
            repo = repo.strip() or f"{login}/jobradar"

            r = c.get(f"/repos/{repo}")
            if r.status_code != 200:
                return {"ok": False,
                        "error": f"Repo {repo} not found — fork jobradar first."}

            # secrets must be sealed with the repo public key (libsodium)
            r = c.get(f"/repos/{repo}/actions/secrets/public-key")
            if r.status_code != 200:
                return {"ok": False, "error": "Cannot read repo key — token needs "
                                              "'Secrets: read and write' on the repo."}
            pk = r.json()
            from nacl.public import PublicKey, SealedBox  # app-only dependency
            sealed = SealedBox(PublicKey(base64.b64decode(pk["key"]))).encrypt(
                database_url.encode())
            r = c.put(f"/repos/{repo}/actions/secrets/DATABASE_URL",
                      json={"encrypted_value": base64.b64encode(sealed).decode(),
                            "key_id": pk["key_id"]})
            if r.status_code not in (201, 204):
                return {"ok": False, "error": f"Setting secret failed (HTTP {r.status_code})."}

            c.put(f"/repos/{repo}/actions/workflows/worker.yml/enable")  # 204 or 404-if-already
            r = c.post(f"/repos/{repo}/actions/workflows/worker.yml/dispatches",
                       json={"ref": "main"})
            fired = r.status_code == 204
        return {"ok": True, "repo": repo, "first_run_fired": fired}
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Network error: {str(e)[:150]}"}
