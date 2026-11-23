"""Session recorder (from pMUD's debug tap): everything the board sends, everything MudPilot or you send,
MudPilot's log lines and its decisions — one JSON object a line, to data/traces/.

    {"t": 1730000000.123, "k": "rx",  "d": "...raw text from the board..."}
    {"t": ...,            "k": "tx",  "d": "esto", "bot": true}
    {"t": ...,            "k": "log", "d": "Switching spell → dragonfire …"}
    {"t": ...,            "k": "dec", "d": {"what": "cast", "spell": "esto", "why": "…"}}

A file a session, rotated at 25 MB, at most 8 files / 150 MB kept. Written by a background thread so the
window never waits on the disk. Passwords never reach it: anything typed at a password prompt, your
saved password, and lines the game prints with a password in them are written as (hidden).

`python -m mudpilot.replay <file>` runs a recording back through MudPilot offline.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time

from . import config

MAX_FILE = 25 * 1024 * 1024
MAX_FILES = 8
MAX_TOTAL = 150 * 1024 * 1024
PASS_PROMPT_RE = re.compile(r"password\s*:?\s*$|enter your password", re.I)


def trace_dir() -> str:
    return os.path.join(config.DATA_DIR, "traces")


class Recorder:
    def __init__(self, session):
        self.s = session
        self.q: queue.Queue = queue.Queue()
        self.path = None
        self._size = 0
        self._f = None
        self._pass_prompt = False
        self._thread = None
        self.seq = 0

    # ------------------------------------------------------------ what gets recorded
    started = False                                  # from the first connect on (nothing worth keeping before)

    @property
    def on(self) -> bool:
        return self.started and bool(getattr(self.s.settings, "record_sessions", True)) \
            and not getattr(self.s, "_no_log_file", False) and not os.environ.get("MUDPILOT_NO_RECORD")

    def rx(self, data: str):
        if not self.on or not data:
            return
        from .timeline import scrub, SECRET_RE
        tail = data.rstrip()[-80:]
        self._pass_prompt = bool(PASS_PROMPT_RE.search(tail))
        prev = getattr(self, "_rx_frag", "")
        cut = re.search(r"[\r\n]", data)
        head = data[:cut.start()] if cut else data
        out = scrub(data) if "assword" in data else data
        if prev and head:
            # the network split 'Recover Password: ...' between two chunks: this chunk's start is (part of) the value
            m = SECRET_RE.search(prev + head)
            if m and m.end() > len(prev):
                rest = data[len(head):]
                out = "(hidden)" + (scrub(rest) if "assword" in rest else rest)
        self._rx_frag = (prev + data).replace("\r", "\n").rsplit("\n", 1)[-1][-80:]
        self._put("rx", out)

    def tx(self, cmd: str, from_bot: bool):
        if not self.on:
            return
        c = cmd or ""
        secret = self._pass_prompt
        pw = self.s.password or self._saved_pw()
        if pw and c.strip() == pw:
            secret = True
        self._pass_prompt = False
        self._put("tx", "(hidden)" if secret and c.strip() else c, bot=bool(from_bot))

    def _saved_pw(self):
        """The saved password, looked up once a minute per user/board — not twice in Credential Manager for every
        command sent (it showed in the window's freeze stacks)."""
        st = self.s.settings
        key = (st.username, st.host)
        c = getattr(self, "_pw_cache", None)
        now = time.time()
        if c is None or c[0] != key or now - c[2] > 60:
            try:
                pw = config.get_password(st.username, st.host)
            except Exception:
                pw = None
            c = self._pw_cache = (key, pw, now)
        return c[1]

    def log(self, msg: str):
        if self.on:
            self._put("log", msg)

    def decision(self, rec: dict):
        if self.on:
            self._put("dec", rec)

    def mark(self, what: str, **extra):
        """Session events: connected, entered the realm, settings, map data — the replay needs them."""
        if what == "connect":
            self.started = True
        if self.on:
            self._put("evt", {"what": what, **extra})

    # ------------------------------------------------------------ writing
    def _put(self, kind, data, **extra):
        self.seq += 1
        rec = {"t": round(time.time(), 3), "k": kind, "n": self.seq, "d": data, **extra}
        self.q.put(rec)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="recorder")
            self._thread.start()

    def _run(self):
        while True:
            try:
                rec = self.q.get(timeout=30)
            except queue.Empty:
                self._flush()
                continue
            try:
                self._write(rec)
                while True:                          # write what's queued in one go
                    try:
                        self._write(self.q.get_nowait())
                    except queue.Empty:
                        break
                self._flush()
            except Exception:
                pass                                 # recording is best-effort: never break the session

    def _flush(self):
        try:
            if self._f:
                self._f.flush()
        except Exception:
            pass

    def _open(self):
        d = trace_dir()
        os.makedirs(d, exist_ok=True)
        cfg = self.s.settings
        who = re.sub(r"[^A-Za-z0-9_-]+", "", (cfg.my_name or "char"))[:20] or "char"
        board = re.sub(r"[^A-Za-z0-9_-]+", "", (cfg.board or "board"))[:20] or "board"
        self.path = os.path.join(d, f"{board}-{who}-{time.strftime('%Y%m%d-%H%M%S')}.ndjson")
        self._f = open(self.path, "a", encoding="utf-8")
        self._size = 0
        from . import __version__
        head = {"t": round(time.time(), 3), "k": "head", "n": 0,
                "d": {"version": __version__, "board": cfg.board, "char": cfg.my_name,
                      "level": cfg.char_level, "class": cfg.char_class, "world": getattr(self.s, "world_path", ""),
                      "settings": self._settings()}}
        self._f.write(json.dumps(head) + "\n")
        self._prune()

    def _settings(self):
        try:
            from .report import clean_settings
            return clean_settings(self.s.settings)         # passwords, tokens and the user name removed
        except Exception:
            return {}

    def _write(self, rec):
        if self._f is None or self._size > MAX_FILE:
            if self._f:
                self._f.close()
            self._open()
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        self._f.write(line)
        self._size += len(line)

    def _prune(self):
        d = trace_dir()
        try:
            files = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".ndjson")),
                           key=os.path.getmtime, reverse=True)
        except OSError:
            return
        total = 0
        for i, fp in enumerate(files):
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            total += sz
            if fp != self.path and (i >= MAX_FILES or total > MAX_TOTAL):
                try:
                    os.remove(fp)
                except OSError:
                    pass

    def flush_now(self, wait=2.0):
        """Write out everything queued (before a debug bundle)."""
        end = time.time() + wait
        while not self.q.empty() and time.time() < end:
            time.sleep(0.05)
        self._flush()
        return self.path

    def recent_files(self, n=2) -> list:
        d = trace_dir()
        try:
            files = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".ndjson")),
                           key=os.path.getmtime, reverse=True)
        except OSError:
            return []
        return files[:n]
