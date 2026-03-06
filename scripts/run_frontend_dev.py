from __future__ import annotations

import os
from pathlib import Path

from livereload import Server

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "sentinelfi" / "web" / "templates" / "index.html"
STATIC_DIR = ROOT / "src" / "sentinelfi" / "web" / "static"
DEV_ROOT = ROOT / ".frontend_dev"
DEV_INDEX = DEV_ROOT / "index.html"
DEV_ASSETS = DEV_ROOT / "assets"
USES_FALLBACK_COPY = False


def _render_index() -> None:
    app_name = os.environ.get("FRONTEND_APP_NAME", "VittaAI")
    api_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/v1")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("{{ app_name }}", app_name).replace("{{ api_base }}", api_base)
    DEV_ROOT.mkdir(parents=True, exist_ok=True)
    DEV_INDEX.write_text(html, encoding="utf-8")


def _ensure_assets_link() -> None:
    global USES_FALLBACK_COPY
    if DEV_ASSETS.exists() or DEV_ASSETS.is_symlink():
        return
    try:
        DEV_ASSETS.symlink_to(STATIC_DIR, target_is_directory=True)
    except OSError:
        # Symlinks can require elevated permissions on some systems.
        # Fallback keeps local dev working with direct file copies.
        USES_FALLBACK_COPY = True
        DEV_ASSETS.mkdir(parents=True, exist_ok=True)
        _sync_assets_copy()


def _sync_assets_copy() -> None:
    if not USES_FALLBACK_COPY:
        return
    DEV_ASSETS.mkdir(parents=True, exist_ok=True)
    for src in STATIC_DIR.iterdir():
        if not src.is_file():
            continue
        dest = DEV_ASSETS / src.name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> None:
    port = int(os.environ.get("FRONTEND_PORT", "5173"))
    _render_index()
    _ensure_assets_link()
    _sync_assets_copy()

    server = Server()
    server.watch(str(TEMPLATE), _render_index)
    server.watch(str(STATIC_DIR / "*.css"), _sync_assets_copy)
    server.watch(str(STATIC_DIR / "*.js"), _sync_assets_copy)
    print(f"Frontend dev server: http://127.0.0.1:{port}")
    print("Expected backend API: " + os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/v1"))
    server.serve(root=str(DEV_ROOT), host="0.0.0.0", port=port, open_url_delay=False)


if __name__ == "__main__":
    main()
