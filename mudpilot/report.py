"""Report a problem: the user says what went wrong; MudPilot bundles what's needed to fix it.

The report (.zip) holds:
  report.txt     what they typed, version, Windows/Python, board, what the bot was doing
  screen.txt     the MUD screen back-scroll (optional — on by default)
  log.txt        MudPilot's own log
  errors.txt     any Python errors caught this session
  settings.json  this character's settings with anything secret removed
It's always saved in MudPilot\\data\\reports\\, then sent to the developer's private Discord channel
(a webhook only accepts posts — nobody can read reports through it). Passwords never appear:
they live in Windows Credential Manager, and the screen shows "(password)" when one is sent.
"""
from __future__ import annotations

import io
import json
import os
import platform
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import zipfile

from . import __version__, config

REPORTS_DIR = os.path.join(config.DATA_DIR, "reports")
ENDPOINT_FILE = os.path.join(os.path.dirname(__file__), "report_endpoint.txt")
SECRET_WORDS = ("pass", "token", "secret", "topic", "webhook", "key")
ERRORS: list = []          # (time, text) — filled by install_error_hooks
MAX_ERRORS = 50


def install_error_hooks(root=None):
    """Remember crashes/tracebacks so a report can include them (and they're in data\\errors.log)."""
    def remember(text):
        ERRORS.append((time.strftime("%Y-%m-%d %H:%M:%S"), text))
        del ERRORS[:-MAX_ERRORS]
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            with open(os.path.join(config.DATA_DIR, "errors.log"), "a", encoding="utf-8") as f:
                f.write(f"--- {ERRORS[-1][0]} (v{__version__})\n{text}\n")
        except OSError:
            pass
    prev = sys.excepthook

    def hook(t, v, tb):
        remember("".join(traceback.format_exception(t, v, tb)))
        prev(t, v, tb)
    sys.excepthook = hook
    if root is not None:
        def tk_hook(t, v, tb):
            remember("".join(traceback.format_exception(t, v, tb)))
            traceback.print_exception(t, v, tb)
        root.report_callback_exception = tk_hook
    return remember


def endpoint() -> str:
    url = os.environ.get("MUDPILOT_REPORT_URL", "").strip()
    if not url:
        try:
            with open(ENDPOINT_FILE, encoding="utf-8") as f:
                url = next((l.strip() for l in f if l.strip() and not l.startswith("#")), "")
        except OSError:
            url = ""
    return url if url.startswith("https://") else ""


def clean_settings(st) -> dict:
    from dataclasses import asdict
    try:
        d = asdict(st)
    except TypeError:
        d = dict(vars(st))

    def scrub(o):
        if isinstance(o, dict):
            return {k: ("(removed)" if any(w in str(k).lower() for w in SECRET_WORDS) else scrub(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        return o
    d = scrub(d)
    d["username"] = "(removed)"
    return d


def build(session, text: str, screen: str = "", include_screen=True) -> str:
    """Write the report zip and return its path."""
    s, st, bot = session, session.state, session.bot
    os.makedirs(REPORTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(REPORTS_DIR, f"report-{stamp}.zip")
    r = s.world.room(st.room) if st.room else None
    info = [
        f"What happened:\n{text.strip() or '(nothing typed)'}\n",
        f"MudPilot {__version__} · {platform.platform()} · Python {platform.python_version()}",
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Board: {s.settings.board} · profile: {s.settings.profile} · character: {s.settings.my_name or '?'}"
        f" ({st.char_class or s.settings.char_class or '?'}, level {st.level or s.settings.char_level or '?'})",
        f"Connected: {s.telnet.connected} · mode: {getattr(bot, 'mode', '?')} · status: {bot.status}",
        f"Path: {bot.path.title if bot.path else '-'} step {getattr(bot, 'idx', 0)}"
        f"/{len(bot.path.steps) if bot.path else 0} · loop {bot.loop} · laps {getattr(bot, 'laps', 0)}",
        f"Room: {st.room} {r.name if r else ''} · candidates {len(st.candidates)}",
        f"HP {st.hp}/{st.max_hp} MA {st.ma}/{st.max_ma} · in combat {st.in_combat} · resting {st.resting}",
        f"Party: {', '.join(st.party) if st.party else '-'}",
        f"Errand: {json.dumps((bot.errands.active or {}).get('todo'), default=str) if getattr(bot, 'errands', None) else '-'}",
        f"Paths loaded: {len(s.paths)}",
        f"Time (last full 10 min): {getattr(bot, 'acct_summary', '-')}",
        f"Time (this stretch): {getattr(bot, 'acct', {})}",
        "Rests by reason: " + "; ".join(f"{w}: {n}× avg {a:.0f}s" for w, n, a, _t, _b in s.stats.rest_summary()),
    ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.txt", "\n".join(info))
        if include_screen and screen:
            from .timeline import scrub
            z.writestr("screen.txt", "\n".join(scrub(l) for l in screen[-400_000:].split("\n")))
        z.writestr("log.txt", "\n".join(s.logs))
        try:
            lf = os.path.join(config.DATA_DIR, "logs", f"mudpilot-{time.strftime('%Y%m%d')}.log")
            with open(lf, encoding="utf-8", errors="replace") as f:
                z.writestr("log-today.txt", f.read()[-3_000_000:])
        except OSError:
            pass
        z.writestr("rests.json", json.dumps(s.stats.rest_log[-300:], indent=0, default=str))
        z.writestr("errors.txt", "\n\n".join(f"--- {t}\n{e}" for t, e in ERRORS) or "(none this session)")
        z.writestr("settings.json", json.dumps(clean_settings(s.settings), indent=1, default=str))
    return path


def send(path: str, text: str, who: str, on_done=None):
    """Post the zip to the developer's Discord webhook in the background. on_done(ok, message)."""
    url = endpoint()
    if not url:
        if on_done:
            on_done(False, "no report address set in this copy — the report is saved; send that file instead")
        return

    def work():
        try:
            boundary = uuid.uuid4().hex
            body = io.BytesIO()

            def part(headers, data):
                body.write(f"--{boundary}\r\n".encode())
                body.write(headers.encode() + b"\r\n\r\n")
                body.write(data)
                body.write(b"\r\n")
            msg = f"**MudPilot {__version__}** report from {who or 'someone'}:\n{text.strip()[:1500]}"
            part('Content-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json',
                 json.dumps({"content": msg, "allowed_mentions": {"parse": []}}).encode())
            with open(path, "rb") as f:
                part(f'Content-Disposition: form-data; name="files[0]"; filename="{os.path.basename(path)}"\r\n'
                     f'Content-Type: application/zip', f.read())
            body.write(f"--{boundary}--\r\n".encode())
            req = urllib.request.Request(url, data=body.getvalue(), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                                  "User-Agent": f"MudPilot/{__version__}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                ok = 200 <= r.status < 300
            if on_done:
                on_done(ok, "sent — thanks!" if ok else f"server said {r.status}; the report is saved")
        except Exception as ex:
            if on_done:
                on_done(False, f"couldn't send ({ex}); the report is saved")
    threading.Thread(target=work, daemon=True).start()
