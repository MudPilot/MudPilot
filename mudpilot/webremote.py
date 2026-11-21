"""Phone page: watch MudPilot from your phone's browser over Headscale / Tailscale.

MudPilot keeps running on this PC; the phone only looks. Settings → Phone alerts → "Phone page".

Security (default deny, like the Remote tab):
  * off unless you tick it;
  * it only listens on this PC's Headscale/Tailscale address (100.64.0.0/10), never on every address —
    so only devices on your own tailnet can even reach it (an address typed in Settings may be loopback or a
    private LAN address, never 0.0.0.0);
  * every data request needs the phone key. A phone gets it once by typing a 6-digit pairing code that
    MudPilot shows for 5 minutes; wrong codes burn the code after 5 tries, and an address that keeps
    failing is shut out for 10 minutes;
  * the key lives in Windows Credential Manager (shared by every MudPilot on this PC, so one pairing covers
    all of them), never in a file; "Forget all phones" makes a new one;
  * this version is watch-only: nothing from the page can walk, type, cast or change a setting;
  * the screen it shows is the same masked text as the window (the recover password stays hidden).
"""
from __future__ import annotations

import glob
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, config

SECRET_USER = "web-remote-key"
PORT_BASE = 8770
PORT_SPAN = 20
TAILNET = ipaddress.ip_network("100.64.0.0/10")
SCREEN_LINES = 400
CODE_SECS = 300
CODE_TRIES = 5
FAIL_MAX, FAIL_WINDOW, BLOCK_SECS = 20, 600, 600
FRESH_SECS = 90


# ---------------------------------------------------------------- key / addresses
def get_key(create=False) -> str:
    k = config.get_password(SECRET_USER) or ""
    if not k and create:
        k = secrets.token_urlsafe(24)
        if not config.set_password(SECRET_USER, k):
            return ""
    return k


def new_key() -> str:
    k = secrets.token_urlsafe(24)
    return k if config.set_password(SECRET_USER, k) else ""


def tailnet_ips() -> list[str]:
    """This PC's Headscale/Tailscale IPv4 address(es)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:                                 # the tailnet's own DNS address: the route to it says which address is ours
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.connect(("100.100.100.100", 53))
            ips.add(u.getsockname()[0])
    except OSError:
        pass
    out = []
    for ip in ips:
        try:
            if ipaddress.ip_address(ip) in TAILNET:
                out.append(ip)
        except ValueError:
            pass
    return sorted(out)


def bind_ok(addr: str) -> bool:
    """An address typed in Settings: loopback, tailnet or a private LAN address — never 'every address'."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not ip.is_unspecified and (ip.is_loopback or ip in TAILNET or ip.is_private)


def _segs(segs) -> list:
    out = []
    for seg in segs or []:
        try:
            text, st = seg[0], seg[1]
            fg = st[0] if st else None
            bold = bool(st[1]) if st else False
        except (TypeError, IndexError):
            text, fg, bold = str(seg), None, False
        if text:
            out.append([text, fg, bold])
    return out


# ---------------------------------------------------------------- the part the main thread owns
class WebRemote:
    def __init__(self, session):
        self.s = session
        self.lock = threading.Lock()
        self.lines: deque = deque(maxlen=SCREEN_LINES)
        self.seq = 0
        self.snap: dict = {}
        self.partial = ""
        self.server = None
        self.thread = None
        self.addr = ""
        self.port = 0
        self.state = "off"
        self._next_try = 0.0
        self._snap_at = 0.0
        self.code = None                 # {"code", "until", "tries"}
        self.fails: dict = {}            # ip -> [times]
        self.blocked: dict = {}          # ip -> until

    # -- called by the session
    def add_line(self, segs):
        if not self.server:
            return
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, _segs(segs)))

    def clear(self):
        with self.lock:
            self.seq += 1
            self.lines.clear()

    def tick(self):
        cfg = self.s.settings
        now = time.time()
        want = bool(getattr(cfg, "web_on", False))
        if want and not self.server and now >= self._next_try:
            self._start()
        elif not want and self.server:
            self._stop("off")
        elif want and self.server:
            b = (getattr(cfg, "web_bind", "") or "").strip()
            if b and b != self.addr:                  # address changed in Settings: listen there instead
                self._stop("moving to " + b)
                self._next_try = 0
        if self.server and now - self._snap_at >= 1.0:
            self._snap_at = now
            try:
                snap = self.snapshot()
            except Exception as ex:            # never let the phone page bother the game
                snap = {"error": str(ex)[:120], "t": now}
            with self.lock:
                self.snap = snap
                try:
                    self.partial = self.s.ansi.partial_text()[-200:]
                except Exception:
                    self.partial = ""

    @property
    def url(self) -> str:
        return f"http://{self.addr}:{self.port}/" if self.server else ""

    # -- pairing (main thread: Settings buttons)
    def pair_code(self) -> str:
        c = f"{secrets.randbelow(1000000):06d}"
        self.code = {"code": c, "until": time.time() + CODE_SECS, "tries": 0}
        get_key(create=True)
        self.s.log("Phone page: pairing code shown (good for 5 minutes)")
        return c

    def forget_phones(self) -> bool:
        ok = bool(new_key())
        self.code = None
        self.s.log("Phone page: every paired phone forgotten — pair again to watch" if ok
                   else "Phone page: couldn't make a new key (Credential Manager)")
        return ok

    # -- server start / stop
    def _start(self):
        cfg = self.s.settings
        want = (getattr(cfg, "web_bind", "") or "").strip()
        if want:
            if not bind_ok(want):
                self.state = f"won't listen on {want} (use your Headscale/Tailscale address, or leave it blank)"
                self._next_try = time.time() + 30
                return
            addr = want
        else:
            ips = tailnet_ips()
            if not ips:
                self.state = "waiting — no Headscale/Tailscale address on this PC yet"
                self._next_try = time.time() + 30
                return
            addr = ips[0]
        if not get_key(create=True):
            self.state = "can't keep the phone key in Credential Manager"
            self._next_try = time.time() + 60
            return
        ports = []
        fixed = int(getattr(cfg, "web_port", 0) or 0)
        if fixed:
            ports = [fixed]
        else:
            last = self._last_port()
            ports = ([last] if last else []) + [p for p in range(PORT_BASE, PORT_BASE + PORT_SPAN) if p != last]
        for p in ports:
            try:
                srv = ThreadingHTTPServer((addr, p), _Handler)
            except OSError:
                continue
            srv.daemon_threads = True
            srv.remote = self
            self.server, self.addr, self.port = srv, addr, p
            self.thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
            self.thread.start()
            self.state = f"on — {self.url}"
            self._write_web({"port": p, "addr": addr, "t": time.time()})
            self.s.log(f"Phone page: on at {self.url} (watch-only; pair your phone from Settings → Phone alerts)")
            return
        self.state = "no free port" + (f" ({fixed})" if fixed else f" ({PORT_BASE}-{PORT_BASE + PORT_SPAN - 1})")
        self._next_try = time.time() + 30

    def _stop(self, state="off"):
        srv, self.server = self.server, None
        self.state = state
        self._write_web(None)
        if srv:
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
            self.s.log("Phone page: off")

    def close(self):
        if self.server:
            self._stop("off")

    def _ctl(self) -> str:
        return os.path.join(config.DATA_DIR, "control")

    def _last_port(self) -> int:
        try:
            with open(os.path.join(self._ctl(), "web.json"), encoding="utf-8") as f:
                return int(json.load(f).get("port") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    def _write_web(self, d):
        p = os.path.join(self._ctl(), "web.json")
        try:
            os.makedirs(self._ctl(), exist_ok=True)
            if d is None:
                d = {"port": self.port or self._last_port(), "off": True, "t": time.time()}
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(p + ".tmp", p)
        except OSError:
            pass

    # -- what the page shows (built on the main thread, read by the server thread)
    def snapshot(self) -> dict:
        s = self.s
        st, b = s.state, s.bot
        r = s.world.room(st.room) if st.room else None
        try:
            rate, rate30 = s.stats.exp_rate(), s.stats.exp_rate(1800)
            secs = s.stats.elapsed()
        except Exception:
            rate = rate30 = secs = 0
        try:
            leader = s.control._leader()
        except Exception:
            leader = None
        party = []
        for n, p in list((st.party or {}).items()):
            party.append({"name": n.split()[0] if n else n, "class": p.get("class", ""),
                          "hp": p.get("hp"), "ma": p.get("ma"), "rank": p.get("rank", "")})
        return {
            "t": time.time(), "version": __version__, "name": s.settings.my_name or "",
            "connected": bool(s.telnet.connected), "in_game": bool(getattr(s, "_entered", False)),
            "status": str(getattr(b, "status", ""))[:200], "walking": bool(b.walking),
            "path": b.path.title if b.path else None, "loop": bool(getattr(b, "loop", False)),
            "laps": int(getattr(b, "laps", 0) or 0),
            "room": list(st.room) if st.room else None, "room_name": r.name if r else "",
            "hp": st.hp, "max_hp": st.max_hp, "ma": st.ma, "max_ma": st.max_ma,
            "in_combat": bool(st.in_combat), "level": st.level,
            "exp_hr": round(rate), "exp_hr_30": round(rate30), "exp_session": int(st.exp_gained or 0),
            "session_secs": round(secs), "exp_needed": int(getattr(st, "exp_needed", 0) or 0),
            "party": party, "leader": leader,
            "hands_off": bool(getattr(s.settings, "hands_off", False)),
        }

    # -- server-thread helpers
    def screen(self, since: int) -> dict:
        with self.lock:
            lines = list(self.lines)
            seq, partial = self.seq, self.partial
        first = lines[0][0] if lines else seq + 1
        reset = since <= 0 or since < first - 1 or since > seq
        out = lines if reset else [ln for ln in lines if ln[0] > since]
        return {"seq": seq, "reset": reset, "lines": [ln[1] for ln in out], "partial": partial}

    def me(self) -> dict:
        with self.lock:
            return dict(self.snap)

    def peers(self) -> list:
        """Every MudPilot on this PC (sibling data folders), from their control folders."""
        here = os.path.normcase(os.path.abspath(config.DATA_DIR))
        out = []
        for ctl in sorted(glob.glob(os.path.join(os.path.dirname(here), "data*", "control"))):
            folder = os.path.dirname(ctl)
            st = _read_json(os.path.join(ctl, "status.json")) or {}
            web = _read_json(os.path.join(ctl, "web.json")) or {}
            mine = os.path.normcase(os.path.abspath(folder)) == here
            if mine:
                snap = self.me()
                st = {**st, **snap} if snap else st
            if not st:
                continue
            age = time.time() - float(st.get("t") or 0)
            if age > 7 * 86400:
                continue                                  # an old, unused data folder
            out.append({
                "folder": os.path.basename(folder), "me": mine, "fresh": age < FRESH_SECS, "age": round(age),
                "port": (self.port if mine else (int(web.get("port") or 0) if not web.get("off") else 0)),
                **{k: st.get(k) for k in ("name", "connected", "in_game", "status", "walking", "path", "room",
                                          "room_name", "hp_pct", "ma_pct", "hp", "max_hp", "ma", "max_ma",
                                          "in_combat", "exp_hr", "exp_session", "leader", "party", "level",
                                          "version", "laps")},
            })
        out.sort(key=lambda p: (not p["me"], not p["fresh"], p["folder"]))
        return out

    def auth_ok(self, ip: str, key: str) -> bool:
        now = time.time()
        if self.blocked.get(ip, 0) > now:
            return False
        good = get_key()
        if good and key and hmac.compare_digest(good.encode(), key.encode()):
            return True
        self._fail(ip, now)
        return False

    def _fail(self, ip, now):
        f = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW] + [now]
        self.fails[ip] = f
        if len(f) >= FAIL_MAX:
            self.blocked[ip] = now + BLOCK_SECS
            self.fails[ip] = []
            self.s._bg.put(lambda: self.s.log(f"Phone page: {ip} kept failing — shut out for 10 minutes"))

    def pair(self, ip: str, code: str) -> str:
        now = time.time()
        if self.blocked.get(ip, 0) > now:
            return ""
        c = self.code
        if not c or now > c["until"]:
            self._fail(ip, now)
            return ""
        if not hmac.compare_digest(c["code"].encode(), (code or "").strip().encode()):
            c["tries"] += 1
            if c["tries"] >= CODE_TRIES:
                self.code = None
                self.s._bg.put(lambda: self.s.log("Phone page: pairing code used up by wrong tries — make a new one"))
            self._fail(ip, now)
            return ""
        self.code = None
        self.s._bg.put(lambda: self.s.log(f"Phone page: a phone paired from {ip}"))
        return get_key(create=True)


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = "MudPilot"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):          # no request log (it would only fill the console)
        pass

    @property
    def remote(self) -> WebRemote:
        return self.server.remote

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                         "connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                         "form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    def do_GET(self):
        from . import webpage
        u = urlparse(self.path)
        ip = self.client_address[0]
        static = webpage.FILES.get(u.path)
        if static:
            body, ctype = static
            return self._send(200, body.encode("utf-8"), ctype)       # never cached: an update reaches the phone at once
        if not u.path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain")
        if not self.remote.auth_ok(ip, self.headers.get("X-MudPilot-Key", "")):
            return self._json(403, {"error": "not paired"})
        if u.path == "/api/me":
            return self._json(200, self.remote.me())
        if u.path == "/api/screen":
            try:
                since = int((parse_qs(u.query).get("since") or ["0"])[0])
            except ValueError:
                since = 0
            return self._json(200, self.remote.screen(since))
        if u.path == "/api/peers":
            return self._json(200, {"peers": self.remote.peers()})
        return self._json(404, {"error": "no such thing"})

    do_HEAD = do_GET

    def do_POST(self):
        u = urlparse(self.path)
        ip = self.client_address[0]
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1024)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""
        if u.path != "/api/pair":
            return self._json(404, {"error": "watch-only"})
        try:
            code = str((json.loads(raw.decode("utf-8") or "{}") or {}).get("code") or "")
        except (ValueError, AttributeError):
            code = ""
        key = self.remote.pair(ip, code)
        if not key:
            return self._json(403, {"error": "wrong or expired code"})
        return self._json(200, {"key": key})
