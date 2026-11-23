"""In-app update check (0.8.200, Dan: "a prompt that they're using an old version with a button to view the release
notes, then they can decide if they want to update").

At start (and Help → Check for updates) it asks GitHub for the newest MudPilot release. Nothing about the player is
sent: one plain request for the public release list, with "MudPilot/<version>" as the client name. If it's newer,
the app shows a bar: What's new / Update / Skip this version.

Update downloads the release zip next to the install, the folder the launcher already looks in, and the launcher
installs it the next time MudPilot opens (a restart under the launcher does it straight away). Only the compiled
build updates itself this way: a source install (MudPilot.bat) is told, but never sent the compiled zip.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

from . import __version__

API = "https://api.github.com/repos/MudPilot/MudPilot/releases/latest"
FROZEN = "__compiled__" in globals() or getattr(sys, "frozen", False)
LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)


def frozen() -> bool:
    try:
        from . import launcher
        return bool(launcher.FROZEN)
    except Exception:
        return FROZEN


def mac_arch() -> str:
    """'arm64' (Apple Silicon) or 'x64' (Intel)."""
    import platform
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def _asset_names(ver: str) -> list:
    """This system's zip names, best first. 0.8.224.2: a Mac took the Windows zip (anything not Linux was Windows) —
    the Mac build is MudPilot-x.y.z-mac-arm64.zip / -mac-x64.zip (or one -mac.zip for both)."""
    if LINUX:
        return [f"MudPilot-{ver}-linux.zip"]
    if MAC:
        return [f"MudPilot-{ver}-mac-{mac_arch()}.zip", f"MudPilot-{ver}-mac.zip"]
    return [f"MudPilot-{ver}.zip"]


def _asset_name(ver: str) -> str:
    return _asset_names(ver)[0]


def check(timeout=10) -> dict | None:
    """{'version', 'url' (release page), 'notes', 'asset' (zip URL for this system or None), 'size'} when GitHub has
    a newer release than this one; None when we're up to date. Raises on network trouble."""
    req = urllib.request.Request(API, headers={"User-Agent": f"MudPilot/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.load(r)
    ver = (rel.get("tag_name") or "").lstrip("vV")
    if not ver or vtuple(ver) <= vtuple(__version__):
        return None
    names = {a.get("name"): a for a in rel.get("assets") or []}
    asset = next((names[n] for n in _asset_names(ver) if n in names), None)
    return {"version": ver, "url": rel.get("html_url") or "", "notes": (rel.get("body") or "").strip(),
            "asset": asset.get("browser_download_url") if asset else None,
            "size": int(asset.get("size") or 0) if asset else 0}


def download_dir() -> str:
    """Where the launcher looks for a newer zip: the folder the install sits in (e.g. Downloads)."""
    return os.path.dirname(ROOT)


def download(info: dict, progress=None) -> str:
    """Fetch the release zip beside the install; returns its path. Only from GitHub's own download host."""
    url = info.get("asset") or ""
    if not url.startswith("https://github.com/MudPilot/MudPilot/releases/download/"):
        raise ValueError("not a MudPilot release download")
    dest = os.path.join(download_dir(), os.path.basename(url.split("?")[0]) or _asset_name(info["version"]))
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": f"MudPilot/{__version__}"})
    import zipfile
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            got, total = 0, int(r.headers.get("Content-Length") or info.get("size") or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        try:
            with zipfile.ZipFile(tmp) as z:          # a broken download never reaches the launcher
                if z.testzip() is not None or not any(n.startswith("MudPilot/") for n in z.namelist()):
                    raise ValueError("the download isn't a MudPilot zip")
        except zipfile.BadZipFile:
            raise ValueError("the download isn't a MudPilot zip")
        os.replace(tmp, dest)
    except BaseException:
        # no half-downloaded .part left beside the install (0.8.201, bug hunt)
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def under_launcher() -> bool:
    return os.environ.get("MUDPILOT_LAUNCHER") == "1"
