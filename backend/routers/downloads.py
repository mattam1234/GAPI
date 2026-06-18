"""Client-download domain (native FastAPI).

Serves the companion client apps so users can grab them straight from the web
UI:

  * GET /api/downloads/manifest          (JSON: what's available to download)
  * GET /api/downloads/extension         (browser-extension/ zipped on the fly)
  * GET /api/downloads/desktop/{name}    (a pre-built desktop installer)

The browser extension is plain Manifest-V3 source, so it is zipped from
``browser-extension/`` on every request — always current, no build step.

Desktop installers are large, platform-specific binaries produced by
``electron-builder``. They are NOT built here; this router simply serves
whatever installer files have been dropped into the downloads directory
(``GAPI_DOWNLOADS_DIR``, default ``<repo>/downloads``). Build them with
``npm run dist`` inside ``desktop-app/`` and copy the artifacts there.

Downloads are intentionally public (no auth): they are client apps, and the
auth boundary is the GAPI server they later talk to, not the download itself.
"""
import io
import os
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

import gapi_gui

router = APIRouter(prefix="/api/downloads", tags=["downloads"])

# Matches the `DEFAULT_SERVER = '…'` constant in the extension's JS files so the
# built download can be re-pointed at the admin-configured server.
_DEFAULT_SERVER_RE = re.compile(r"(DEFAULT_SERVER\s*=\s*)(['\"])[^'\"]*\2")

# <repo>/backend/routers/downloads.py -> <repo>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_DIR = PROJECT_ROOT / "browser-extension"
DOWNLOADS_DIR = Path(
    os.environ.get("GAPI_DOWNLOADS_DIR", str(PROJECT_ROOT / "downloads"))
).resolve()

# Map installer file extensions to a platform + human label.
_INSTALLER_TYPES = {
    ".exe": ("windows", "Windows installer"),
    ".msi": ("windows", "Windows installer"),
    ".dmg": ("macos", "macOS disk image"),
    ".pkg": ("macos", "macOS installer"),
    ".appimage": ("linux", "Linux AppImage"),
    ".deb": ("linux", "Debian/Ubuntu package"),
    ".rpm": ("linux", "Fedora/RHEL package"),
    ".snap": ("linux", "Snap package"),
}


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _resolve_server_url(request: Request) -> str:
    """The server URL to bake into download clients.

    Prefers the admin-configured ``server_url`` app setting; falls back to the
    address the request came in on so a freshly installed client still points
    somewhere sensible.
    """
    configured = ""
    try:
        db = next(gapi_gui.database.get_db())
        try:
            svc = getattr(gapi_gui, "_app_settings_service", None)
            if svc:
                configured = svc.get(db, "server_url", "") or ""
            else:
                configured = gapi_gui.database.get_app_setting(
                    db, "server_url", "") or ""
        finally:
            if db:
                db.close()
    except Exception:
        configured = ""
    url = configured.strip() or str(request.base_url)
    return url.rstrip("/")


def _rewrite_extension_js(text: str, server_url: str) -> str:
    """Point the extension's DEFAULT_SERVER constant at *server_url*."""
    return _DEFAULT_SERVER_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{server_url}{m.group(2)}", text)


def _list_desktop_installers() -> list[dict]:
    """Return metadata for every installer file in the downloads directory."""
    if not DOWNLOADS_DIR.is_dir():
        return []
    installers = []
    for entry in sorted(DOWNLOADS_DIR.iterdir()):
        if not entry.is_file():
            continue
        platform, label = _INSTALLER_TYPES.get(entry.suffix.lower(), (None, None))
        if platform is None:
            continue
        size = entry.stat().st_size
        installers.append({
            "filename": entry.name,
            "platform": platform,
            "label": label,
            "size_bytes": size,
            "size_human": _human_size(size),
            "url": f"/api/downloads/desktop/{entry.name}",
        })
    return installers


@router.get("/manifest")
def downloads_manifest(request: Request):
    """List the client apps available for download."""
    return {
        "server_url": _resolve_server_url(request),
        "extension": {
            "name": "GAPI Browser Extension",
            "available": EXTENSION_DIR.is_dir(),
            "url": "/api/downloads/extension",
            "filename": "gapi-browser-extension.zip",
        },
        "desktop": {
            "name": "GAPI Desktop App",
            "installers": _list_desktop_installers(),
        },
    }


@router.get("/extension")
def download_extension(request: Request):
    """Zip the browser-extension source on the fly and serve it.

    The extension's ``DEFAULT_SERVER`` constant is rewritten to the
    admin-configured server URL so the download works out of the box.
    """
    if not EXTENSION_DIR.is_dir():
        raise HTTPException(status_code=404, detail="Extension source not found")

    server_url = _resolve_server_url(request)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            if not path.is_file():
                continue
            arcname = path.relative_to(EXTENSION_DIR).as_posix()
            if path.suffix.lower() == ".js":
                source = path.read_text(encoding="utf-8")
                zf.writestr(arcname, _rewrite_extension_js(source, server_url))
            else:
                zf.write(path, arcname=arcname)
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                'attachment; filename="gapi-browser-extension.zip"',
        },
    )


@router.get("/desktop/{filename}")
def download_desktop(filename: str):
    """Serve a pre-built desktop installer from the downloads directory."""
    # Resolve and confirm the target stays inside DOWNLOADS_DIR (no traversal).
    target = (DOWNLOADS_DIR / filename).resolve()
    if (
        DOWNLOADS_DIR not in target.parents
        or not target.is_file()
        or target.suffix.lower() not in _INSTALLER_TYPES
    ):
        raise HTTPException(status_code=404, detail="Installer not found")
    return FileResponse(
        path=str(target),
        media_type="application/octet-stream",
        filename=target.name,
    )
