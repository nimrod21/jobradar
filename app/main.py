"""Desktop app entry point.

  python -m app.main

Config lives in jobradar.toml next to the binary (or repo root in dev):
  database_url = "postgresql://..."
  theme = "dark"
A missing file is created with a placeholder; DATABASE_URL in the
environment (or .env) overrides it for development.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

import webview
from dotenv import load_dotenv

from .api import Api

_PLACEHOLDER = '''# JobRadar app config
# Supabase -> Connect -> Session pooler connection string:
database_url = ""
theme = "dark"
'''


def _base_dir() -> Path:
    """Where jobradar.toml lives: next to the binary, or the repo root in dev."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _asset_dir() -> Path:
    """Where app/web lives: the onefile extraction dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


def _config_path() -> Path:
    return _base_dir() / "jobradar.toml"


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        path.write_text(_PLACEHOLDER, encoding="utf-8")
        return {"database_url": "", "theme": "dark"}
    try:
        # decode ourselves so a BOM (Notepad's default) doesn't break tomllib
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"Ignoring broken {path.name}: {e}", file=sys.stderr)
        return {"database_url": "", "theme": "dark"}


def save_config(cfg: dict) -> None:
    lines = [f'database_url = "{cfg.get("database_url", "")}"',
             f'theme = "{cfg.get("theme", "dark")}"']
    sc = cfg.get("scoring") or {}
    if sc:
        lines += ["", "[scoring]",
                  f'api_base = "{sc.get("api_base", "https://openrouter.ai/api/v1")}"',
                  f'openrouter_api_key = "{sc.get("openrouter_api_key", "")}"',
                  f'model = "{sc.get("model", "")}"',
                  f'auto = {"true" if sc.get("auto", True) else "false"}',
                  f'cap_per_open = {int(sc.get("cap_per_open", 20))}']
    for acc in cfg.get("email", []):
        lines += ["", "[[email]]",
                  f'address = "{acc.get("address", "")}"',
                  f'app_password = "{acc.get("app_password", "")}"',
                  f'imap_host = "{acc.get("imap_host", "")}"']
    _config_path().write_text("# JobRadar app config\n" + "\n".join(lines) + "\n",
                              encoding="utf-8")


def main() -> None:
    load_dotenv()
    cfg = load_config()
    database_url = os.environ.get("DATABASE_URL") or cfg.get("database_url", "")
    if not database_url:
        print(f"No database_url configured. Fill in {_config_path()}", file=sys.stderr)

    api = Api(database_url, cfg, save_config)
    webview.create_window(
        "JobRadar",
        str(_asset_dir() / "app" / "web" / "index.html"),
        js_api=api,
        width=1280,
        height=820,
        min_size=(960, 600),
        background_color="#0d0b12",
    )
    webview.start()


if __name__ == "__main__":
    main()
