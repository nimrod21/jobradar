# Setting up JobRadar from scratch

Everything you need to run your own instance: a free Supabase project, any
small Linux VPS for the worker (Oracle Cloud free tier shown), and the desktop
app on your machine. No step assumes anything from my accounts — clone and go.

---

## 1. Database (Supabase, free tier)

1. Create an account at [supabase.com](https://supabase.com) and create a
   **New project**. Pick any name (`jobradar`), a strong database password
   (save it — you'll need it in the connection string), and the region nearest
   to wherever the worker will run.
2. When the project finishes provisioning, open **SQL Editor**, paste the whole
   of [`migrations/001_init.sql`](../migrations/001_init.sql), and run it.
   You should see `Success. No rows returned`.
3. Get the connection string: **Connect** (top bar) → **Session pooler** →
   copy the URI. It looks like:

   ```
   postgresql://postgres.abcdefghij:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```

   Replace `[YOUR-PASSWORD]` with the database password from step 1.

**Why the session pooler and not the direct connection:** Supabase's direct
connection is IPv6-only. Most home networks and many VPSes (including Oracle
free tier) have no IPv6, and the direct string will just hang. The session
pooler is IPv4 and behaves like a normal Postgres connection.

**Why no API keys:** the migration enables row-level security on every table
with no policies, so Supabase's auto-generated REST API exposes nothing.
The worker and the app connect over direct Postgres; the connection string is
the only credential in the whole system. Never commit it.

---

## 2. Worker — run it anywhere first

```bash
git clone https://github.com/nimrod21/jobradar && cd jobradar
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
cp .env.example .env                             # fill DATABASE_URL from step 1

.venv/bin/python -m worker.main --dry-run   # no database needed: fetch + normalise, prints per-source stats
.venv/bin/python -m worker.main --once      # one real cycle into your database
```

A first `--once` cycle takes 1–2 minutes and should end with several hundred
jobs. Run it twice — the second run should report mostly `0 new`, which is the
write-time dedupe working. `select count(*) from jobs` in the SQL editor to
confirm.

---

## 3. Worker on a VPS (Oracle Cloud free tier example)

Any always-on Linux box with Python 3.11+ works. Oracle's "Always Free" tier
includes small AMD/ARM instances that are enough (the worker is I/O-bound and
`Nice=10`).

### 3a. Create the instance

1. [cloud.oracle.com](https://cloud.oracle.com) → **Compute → Instances →
   Create instance**.
2. Image: **Ubuntu 24.04** (or the newest Ubuntu). Shape: any Always Free
   eligible one (`VM.Standard.E2.1.Micro`, or an `A1.Flex` ARM shape if
   available — ARM gives you far more headroom).
3. Under **Add SSH keys**, paste your public key (`~/.ssh/id_ed25519.pub`;
   generate one with `ssh-keygen -t ed25519` if you don't have it).
4. Create, wait for RUNNING, note the **public IP**.
5. Default firewall allows SSH only — that's all the worker needs (it makes
   outbound requests only).

> Oracle reclaims Always Free instances that sit idle for long periods, and a
> reclaimed/recreated instance gets a new host key and often a new IP. If ssh
> warns REMOTE HOST IDENTIFICATION HAS CHANGED after a recreate, remove the
> stale line from `~/.ssh/known_hosts` and verify you're talking to the IP
> shown in the Oracle console before accepting.

### 3b. Deploy

From your machine:

```bash
ssh ubuntu@<PUBLIC-IP>                    # confirm you can get in
```

Then on the server, one command:

```bash
curl -fsSL https://raw.githubusercontent.com/nimrod21/jobradar/main/deploy/bootstrap.sh | bash
```

…or clone and run it yourself (it's ~30 lines — read it first, always):

```bash
git clone https://github.com/nimrod21/jobradar /opt/jobradar
cd /opt/jobradar && bash deploy/bootstrap.sh
```

The script installs Python + venv + dependencies, prompts you to fill
`/opt/jobradar/.env`, installs the systemd unit, and starts the service.

### 3c. Verify

```bash
systemctl status jobradar-worker          # active (running)
journalctl -u jobradar-worker -f          # watch a cycle happen
```

And in Supabase's SQL editor:

```sql
select source, last_success, consecutive_failures, jobs_last_run
from source_health order by last_success desc;
```

A silently dead adapter shows up here rather than just going quiet.

---

## 4. Desktop app

```bash
python -m app.main
```

First run creates `jobradar.toml` next to the repo (or the binary) — put your
session-pooler string in `database_url` there, or set `DATABASE_URL` in the
environment. Create a tracker and you're triaging.

To build a single-file binary:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name JobRadar --add-data "app/web;app/web" app_entry.py
# -> dist/JobRadar.exe  (config file lives NEXT TO the exe, never inside it)
```

On Windows the app uses the system's Edge WebView2 runtime (preinstalled on
Windows 11).

---

## 5. Optional: more sources

Tier-2 sources (Adzuna, Jooble, Reed, Findwork, USAJobs) all have free API
tiers but need per-account keys — register, add the keys to `.env`, and write
an adapter per source following any file in `worker/sources/` as a template.
An adapter is ~30 lines: fetch, map fields to `RawJob`, done. The pipeline
(normalise → fingerprint → dedupe → search) needs no changes.
