#!/usr/bin/env bash
# JobRadar worker bootstrap for a fresh Ubuntu server. Idempotent.
# Usage: bash deploy/bootstrap.sh   (run from anywhere; installs to /opt/jobradar)
set -euo pipefail

REPO="https://github.com/nimrod21/jobradar"
DIR="/opt/jobradar"

echo "== JobRadar worker bootstrap =="

sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git

if [ ! -d "$DIR/.git" ]; then
    sudo git clone "$REPO" "$DIR"
    sudo chown -R "$USER":"$USER" "$DIR"
else
    git -C "$DIR" pull --ff-only
fi

cd "$DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo ">> Edit $DIR/.env now and set DATABASE_URL (Supabase session-pooler string)."
    echo ">> Then re-run this script to install and start the service."
    exit 0
fi

if ! grep -q "^DATABASE_URL=postgresql" .env; then
    echo ">> DATABASE_URL is not set in $DIR/.env — fill it in and re-run."
    exit 1
fi

sudo cp deploy/jobradar-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jobradar-worker

sleep 3
sudo systemctl --no-pager status jobradar-worker | head -8
echo
echo "== Done. Watch it with: journalctl -u jobradar-worker -f =="
