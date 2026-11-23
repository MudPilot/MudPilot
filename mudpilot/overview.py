"""All characters: one window showing every MudPilot on the LAN (0.8.201, Dan: "the single desktop window that shows
all characters on your lan would be awesome").

Where the rows come from:
  * status folders: each running MudPilot already writes data*\\control\\status.json (control.py, every 10 s). This
    window reads those from this install's own data folders, plus any folders you add (Folders…): a mapped drive or
    UNC path to another PC's install (M:\\MudPilot\\MudPilot) or one data folder (R:\\MudPilot\\MudPilot\\data-Evolution);
  * LAN packets (optional, off by default): a MudPilot with Settings 'status_broadcast' on sends the same small
    status as a UDP broadcast on this LAN; tick "Listen" here to show those too.

Security (Dan: "industrial level"):
  * read-only: nothing here sends anything to a character, writes into its folders, or can start/stop/restart it.
    The only file it writes is this PC's own data\\overview.json (the folder list and the Listen tick);
  * status files carry names, numbers and the bot's status line — never a password, chat or screen text; files are
    read with a size cap and every value is checked and cut short before it's shown;
  * the UDP listener is off unless ticked, takes only packets from private LAN addresses (10/8, 172.16/12,
    192.168/16, link-local, loopback), at most 2 KB, known keys only, from at most 64 senders — and it is never
    answered. Broadcasts don't cross routers or Tailscale, so it's this LAN only;
  * a folder on a PC that's switched off can hang a read for a while: each folder is read on its own worker thread,
    so the window never freezes and one dead share doesn't hold up the rest.
"""
from __future__ import annotations

import glob
import ipaddress
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__, config

PREFS_FILE = "overview.json"
UDP_PORT = 47870
UDP_MAGIC = "mudpilot-status-1"
UDP_MAX = 2048
UDP_MAX_SENDERS = 64
MAX_FILE = 64 * 1024
REFRESH_MS = 3000
STALE_SECS = 75          # a status older than this is grey (written every 10 s; 30 s before 0.8.201)
OFFLINE_SECS = 300       # older than this: MudPilot isn't running there (or the PC is off) — red
EXPAND_SECS = 120        # look for new data folders in an added folder this often
OLD_DAYS = 7           # a data folder not written in a week is hidden unless 'Show old' is ticked

# what a status can carry (key -> type); anything else in a file or packet is ignored
FIELDS = {"t": float, "version": str, "connected": bool, "in_game": bool, "walking": bool, "path": str,
          "status": str, "room": list, "hp_pct": int, "ma_pct": int, "in_combat": bool, "exp_hr": int,
          "hands_off": bool, "profile": str, "name": str, "board": str, "pvp_realm": bool, "level": int, "cls": str,
          "room_name": str, "hp": int, "max_hp": int, "ma": int, "max_ma": int, "loop": bool, "hung_up": bool,
          "dead": bool, "by_launcher": bool, "status_every": int}
STR_MAX = 160


def clean(d) -> dict:
    """Only the known keys, each the right type, strings cut short and printable. Anything odd is dropped."""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, typ in FIELDS.items():
        v = d.get(k)
        if v is None:
            continue
        try:
            if typ is bool:
                if isinstance(v, bool):
                    out[k] = v
            elif typ is int:
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e12:
                    out[k] = int(v)
            elif typ is float:
                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e11:
                    out[k] = float(v)
            elif typ is str:
                if isinstance(v, str):
                    out[k] = "".join(c for c in v if c.isprintable())[:STR_MAX]
            elif typ is list:
                if isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool)
                                                                for x in v):
                    out[k] = [int(v[0]), int(v[1])]
        except (TypeError, ValueError, OverflowError):
            pass
    return out


def _read_json(p, cap=MAX_FILE):
    try:
        with open(p, "rb") as f:
            raw = f.read(cap + 1)
        if len(raw) > cap:
            return None
        d = json.loads(raw.decode("utf-8", "replace"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- prefs (this PC's own data folder only)
def prefs_path(data_dir=None) -> str:
    return os.path.join(data_dir or config.DATA_DIR, PREFS_FILE)


def load_prefs(data_dir=None) -> dict:
    d = _read_json(prefs_path(data_dir)) or {}
    folders = [str(x).strip() for x in d.get("folders") or [] if isinstance(x, str) and str(x).strip()][:50]
    try:
        port = int(d.get("port") or UDP_PORT)
    except (TypeError, ValueError):
        port = UDP_PORT
    return {"folders": folders, "listen": d.get("listen") is True, "port": port if 1024 <= port <= 65535 else UDP_PORT,
            "show_old": d.get("show_old") is True}


def save_prefs(prefs: dict, data_dir=None) -> bool:
    p = prefs_path(data_dir)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"folders": list(prefs.get("folders") or []), "listen": bool(prefs.get("listen")),
                       "port": int(prefs.get("port") or UDP_PORT), "show_old": bool(prefs.get("show_old"))}, f, indent=1)
        os.replace(p + ".tmp", p)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- finding characters
def local_roots(data_dir=None) -> list:
    """This install's data folders (data, data-PVE, …) — the one we're running from and its siblings."""
    here = os.path.abspath(data_dir or config.DATA_DIR)
    parent = os.path.dirname(here)
    out = [here]
    try:
        for d in sorted(os.listdir(parent)):
            full = os.path.join(parent, d)
            if (d == "data" or d.startswith("data-")) and os.path.isdir(full):
                out.append(full)
    except OSError:
        pass
    return out


def expand(entry: str) -> list:
    """A configured entry → its data folders. Takes a data folder (has control\\), its control folder, or an install
    folder (has data*\\control). Only ever lists and reads."""
    e = os.path.expandvars(os.path.expanduser(entry.strip().strip('"')))
    if not e:
        return []
    if os.path.basename(os.path.normpath(e)).lower() == "control" and os.path.isfile(os.path.join(e, "status.json")):
        return [os.path.dirname(os.path.normpath(e))]
    if os.path.isdir(os.path.join(e, "control")):
        return [e]
    found = [os.path.dirname(c) for c in sorted(glob.glob(os.path.join(e, "data*", "control")))]
    if not found:                       # e.g. M:\ (Downloads) → M:\MudPilot\MudPilot\data*
        found = [os.path.dirname(c) for c in sorted(glob.glob(os.path.join(e, "*", "*", "data*", "control")))]
    return found


def _key(folder: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(folder)))


def read_folder(folder: str, now=None) -> dict | None:
    """One data folder → a row (or None when it has no status.json)."""
    ctl = os.path.join(folder, "control")
    sp = os.path.join(ctl, "status.json")
    raw = _read_json(sp)
    if raw is None:
        if not os.path.isdir(ctl):
            return None
        d = {}
    else:
        d = clean(raw)
    try:
        mtime = os.path.getmtime(sp)
    except OSError:
        mtime = 0.0
    if not d.get("name"):
        who = (_read_json(os.path.join(folder, "app.json"), 16 * 1024) or {}).get("profile")
        if isinstance(who, str) and who.strip():
            d.setdefault("profile", "".join(c for c in who if c.isprintable())[:40])
    return make_row(d, source=folder, mtime=mtime, now=now)


def make_row(d: dict, source: str, mtime: float = 0.0, now=None, via="folder") -> dict:
    now = time.time() if now is None else now
    t = d.get("t") or 0.0
    age = now - t if t else None
    if mtime and (age is None or age < -60):
        age = now - mtime               # no time inside, or the other PC's clock is ahead: the file's own time
    if age is not None and age < 0:
        age = 0.0
    name = d.get("name") or ""
    if not name:                        # older status.json (before 0.8.201): no name in it — profile + folder
        name = d.get("profile") or ""
        if via == "folder":
            name = f"{name} ({folder_label(source)})" if name else folder_label(source)
        name = name or "?"
    state, doing = activity(d, age)
    return {"key": via + ":" + (_key(source) if via == "folder" else source) + (":" + name if via == "udp" else ""),
            "via": via, "source": source, "name": name, "age": age, "state": state, "doing": doing, "d": d}


def folder_label(folder: str) -> str:
    b = os.path.basename(os.path.normpath(folder))
    return b[5:] if b.lower().startswith("data-") else b


def activity(d: dict, age) -> tuple:
    """(state, what it's doing). state: offline | stale | down | dead | hung | fight | rest | loop | walk | idle."""
    st = d.get("status") or ""
    if age is None or not d:
        return "offline", "no status yet"
    if age > OFFLINE_SECS:
        return "offline", "not running (last seen " + fmt_age(age) + " ago)"
    stale = age > max(STALE_SECS, int(d.get("status_every") or 0) * 3)
    if d.get("hung_up"):
        res = ("hung", "hung up — staying offline")
    elif not d.get("connected"):
        res = ("down", "disconnected" + (f" ({st})" if st and st.lower() != "disconnected" else ""))
    elif not d.get("in_game"):
        res = ("down", "at the BBS menu")
    elif d.get("dead"):
        res = ("dead", "died — waiting for you")
    elif d.get("in_combat"):
        res = ("fight", st or "fighting")
    elif "resting" in st.lower() or st.lower().startswith(("meditat", "rest")):
        res = ("rest", st)
    elif d.get("walking"):
        p = d.get("path") or ""
        if p.startswith("Go to"):
            res = ("walk", "walking: " + p[3:].strip() + (f" — {st}" if st and st not in ("Walking", p) else ""))
        elif d.get("loop"):
            res = ("loop", "looping " + p + (f" — {st}" if st and st != "Walking" else ""))
        else:
            res = ("walk", "walking " + p + (f" — {st}" if st and st != "Walking" else ""))
    else:
        res = ("idle", "stopped" + (f" — {st}" if st and st not in ("Idle", "Stopped") else ""))
    if stale:
        return "stale", res[1] + "  (no word for " + fmt_age(age) + ")"
    return res


def fmt_age(a) -> str:
    if a is None:
        return "—"
    a = int(a)
    if a < 90:
        return f"{a} s"
    if a < 5400:
        return f"{a // 60} min"
    if a < 172800:
        return f"{a / 3600:.1f} h"
    return f"{a // 86400} days"


def fmt_exp(v) -> str:
    if not v:
        return "—"
    return f"{v / 1e6:.2f}M" if v >= 1e6 else f"{v / 1e3:.0f}k"


def fmt_pool(d, cur, mx, pct) -> str:
    c, m, p = d.get(cur), d.get(mx), d.get(pct)
    if m:
        return f"{round(100 * (c or 0) / m)}% {c}/{m}"
    return f"{p}%" if p is not None else "—"


def columns(row: dict) -> tuple:
    d = row["d"]
    realm = d.get("board") or ""
    if d.get("pvp_realm"):
        realm = (realm + " PvP").strip()
    lv = d.get("level")
    lvc = ((f"{lv} " if lv else "") + (d.get("cls") or "")).strip() or "—"
    room = d.get("room")
    where = d.get("room_name") or ""
    if room:
        where = (where + f" ({room[0]}/{room[1]})").strip()
    return (row["name"], realm or "—", lvc, fmt_pool(d, "hp", "max_hp", "hp_pct"), fmt_pool(d, "ma", "max_ma", "ma_pct"),
            where or "—", row["doing"], fmt_exp(d.get("exp_hr")), fmt_age(row["age"]), d.get("version") or "—")


# ---------------------------------------------------------------- optional LAN packets
_SEND_KEYS = [k for k in FIELDS if k not in ("by_launcher",)]


def packet(d: dict) -> bytes:
    """The broadcast: the cleaned status only (no password/chat/screen text exists in it to begin with)."""
    body = {k: v for k, v in clean(d).items() if k in _SEND_KEYS}
    body["mp"] = UDP_MAGIC
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if len(raw) > UDP_MAX:
        body.pop("status", None)
        body.pop("path", None)
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")[:UDP_MAX]
    return raw


def send_status(d: dict, port: int = UDP_PORT):
    """One UDP broadcast on this LAN (routers don't forward it). Never waits; any error is dropped."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            u.setblocking(False)
            u.sendto(packet(d), ("255.255.255.255", int(port)))
    except (OSError, ValueError, TypeError):
        pass


def lan_ok(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.version != 4:
        return False
    return a.is_loopback or a.is_link_local or any(a in n for n in (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16")))


def parse_packet(raw: bytes, ip: str) -> dict | None:
    if not lan_ok(ip) or len(raw) > UDP_MAX:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("mp") != UDP_MAGIC:
        return None
    return clean(d)


class UdpListener:
    """Off unless ticked. Receives only; never replies."""

    def __init__(self, port: int = UDP_PORT):
        self.port = port
        self.lock = threading.Lock()
        self.got: dict = {}              # (ip, name) -> (recv time, status)
        self.error = ""
        self._stop = threading.Event()
        self.sock = None
        self.thread = None

    def start(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("", self.port))      # broadcasts only arrive on the any-address; source checked per packet
            s.settimeout(0.5)
        except OSError as ex:
            self.error = str(ex)[:120]
            return False
        self.sock = s
        self.thread = threading.Thread(target=self._run, name="overview-udp", daemon=True)
        self.thread.start()
        return True

    def _run(self):
        while not self._stop.is_set():
            try:
                raw, (ip, _port) = self.sock.recvfrom(UDP_MAX + 1)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                time.sleep(0.5)
                continue
            self.take(raw, ip)

    def take(self, raw: bytes, ip: str, now=None) -> bool:
        d = parse_packet(raw, ip)
        if d is None:
            return False
        name = d.get("name") or d.get("profile") or "?"
        k = (ip, name)
        with self.lock:
            if k not in self.got and len(self.got) >= UDP_MAX_SENDERS:
                return False
            self.got[k] = (time.time() if now is None else now, d)
        return True

    def rows(self, now=None) -> list:
        now = time.time() if now is None else now
        with self.lock:
            items = list(self.got.items())
        out = []
        for (ip, _name), (rt, d) in items:
            if now - rt > 86400:
                continue
            d = dict(d)
            d["t"] = rt                  # the time we heard it (the other PC's clock may be off)
            out.append(make_row(d, source=ip, now=now, via="udp"))
        return out

    def stop(self):
        self._stop.set()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None


# ---------------------------------------------------------------- scanning (off the Tk thread)
class Scanner:
    """Reads every folder on worker threads; rows() returns the latest without ever blocking."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir or config.DATA_DIR
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="overview")
        self.lock = threading.Lock()
        self.results: dict = {}          # folder key -> row
        self.busy: set = set()           # entries being read right now (a dead share stays here, never piles up)
        self.folders: dict = {}          # entry -> [data folders] (expanding is slow on a dead share too)
        self.expanded_at: dict = {}
        self.closed = False

    def scan(self, entries: list):
        if self.closed:
            return
        for e in local_roots(self.data_dir):
            self._submit(("folder", e))
        for e in entries:
            self._submit(("entry", e))

    def _submit(self, job):
        with self.lock:
            if job in self.busy:
                return
            self.busy.add(job)
        try:
            self.pool.submit(self._run, job)
        except RuntimeError:              # shut down
            with self.lock:
                self.busy.discard(job)

    def _run(self, job):
        kind, e = job
        try:
            if kind == "entry":
                with self.lock:
                    known, at = self.folders.get(e), self.expanded_at.get(e, 0)
                if known is None or time.time() - at > EXPAND_SECS:
                    # listing a share is the slow part (R: over Tailscale: ~30 s for R:\) — redo it now and then
                    known = expand(e)
                    with self.lock:
                        self.folders[e], self.expanded_at[e] = known, time.time()
                for f in known:
                    self._submit(("folder", f))      # each folder read on its own: fresh every few seconds
                return
            row = read_folder(e)
            if row is not None:
                with self.lock:
                    self.results[_key(e)] = row
        except Exception:
            pass
        finally:
            with self.lock:
                self.busy.discard(job)

    def rows(self, entries: list, show_old=False) -> list:
        keep = {_key(f) for f in local_roots(self.data_dir)}
        with self.lock:
            for e in entries:
                keep |= {_key(f) for f in self.folders.get(e, [])}
            rows = [r for k, r in self.results.items() if k in keep]
        if not show_old:
            rows = [r for r in rows if r["age"] is not None and r["age"] < OLD_DAYS * 86400]
        return rows

    def close(self):
        self.closed = True
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.pool.shutdown(wait=False)


ORDER = {"fight": 0, "loop": 0, "walk": 0, "rest": 0, "idle": 1, "dead": 1, "hung": 2, "down": 2, "stale": 3,
         "offline": 4}


def merge(rows: list) -> list:
    """A character seen in a folder and also by LAN packet shows once (the folder row). Folder rows are never merged
    with each other (two folders can share a profile name). Live first, then by name."""
    named = {(r["d"].get("name", "").lower(), r["d"].get("board") or "") for r in rows
             if r["via"] == "folder" and r["d"].get("name")}
    out = [r for r in rows if r["via"] == "folder" or (r["d"].get("name", "").lower(), r["d"].get("board") or "")
           not in named]
    return sorted(out, key=lambda r: (ORDER.get(r["state"], 5), r["name"].lower()))


# ---------------------------------------------------------------- the window
COLS = (("name", "Character", 110), ("realm", "Realm", 90), ("lvl", "Level", 90), ("hp", "HP", 100),
        ("ma", "Mana", 100), ("where", "Where", 220), ("doing", "Doing", 300), ("exp", "Exp/hr", 70),
        ("age", "Updated", 70), ("ver", "Version", 70))
COLOURS = {"fight": "#e6b450", "loop": "#2fbf71", "walk": "#6d8cff", "rest": "#5cffff", "idle": "#e0e6ef",
           "dead": "#ff5c5c", "hung": "#ff5c5c", "down": "#c8a23a", "stale": "#8a94a6", "offline": "#a04848"}


def _tk():
    import tkinter as tk
    from tkinter import ttk
    return tk, ttk


class OverviewPane:
    """Built into any Tk container. app = the main App (for the 'share this character' tick) or None (standalone)."""

    BG, PANEL, TEXT, MUTED = "#0b0d10", "#151a21", "#e0e6ef", "#8a94a6"

    def __init__(self, master, app=None, data_dir=None, auto=True):
        tk, ttk = _tk()
        self.tk = tk
        self.app = app
        self.data_dir = data_dir or config.DATA_DIR
        self.prefs = load_prefs(self.data_dir)
        self.scanner = Scanner(self.data_dir)
        self.listener = None
        self.rows: list = []
        self._after = None
        self.frame = f = tk.Frame(master, background=self.PANEL)
        top = tk.Frame(f, background=self.PANEL)
        top.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(top, text="All characters", background=self.PANEL, foreground=self.TEXT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(top, text="  read-only — nothing here sends anything to a character", background=self.PANEL,
                 foreground=self.MUTED).pack(side="left")
        ttk.Button(top, text="Folders…", command=self.edit_folders).pack(side="right")
        self.v_old = tk.BooleanVar(value=self.prefs["show_old"])
        tk.Checkbutton(top, text="Show old folders", variable=self.v_old, command=self._prefs_changed,
                       background=self.PANEL, foreground=self.TEXT, selectcolor=self.BG,
                       activebackground=self.PANEL, activeforeground=self.TEXT).pack(side="right", padx=6)
        self.v_listen = tk.BooleanVar(value=self.prefs["listen"])
        tk.Checkbutton(top, text=f"Listen for LAN status packets (UDP {self.prefs['port']})", variable=self.v_listen,
                       command=self._prefs_changed, background=self.PANEL, foreground=self.TEXT, selectcolor=self.BG,
                       activebackground=self.PANEL, activeforeground=self.TEXT).pack(side="right", padx=6)
        if app is not None:
            self.v_share = tk.BooleanVar(value=bool(getattr(app.s.settings, "status_broadcast", False)))
            tk.Checkbutton(top, text="Share this character on the LAN", variable=self.v_share,
                           command=self._share_changed, background=self.PANEL, foreground=self.TEXT,
                           selectcolor=self.BG, activebackground=self.PANEL,
                           activeforeground=self.TEXT).pack(side="right", padx=6)
        mid = tk.Frame(f, background=self.PANEL)
        mid.pack(fill="both", expand=True, padx=8)
        self.tree = t = ttk.Treeview(mid, columns=[c[0] for c in COLS], show="headings", height=8,
                                     selectmode="browse")
        for key, title, w in COLS:
            t.heading(key, text=title)
            t.column(key, width=w, stretch=key in ("where", "doing"), anchor="w")
        for st, col in COLOURS.items():
            t.tag_configure(st, foreground=col)
        sb = ttk.Scrollbar(mid, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        t.bind("<<TreeviewSelect>>", lambda e: self._show_detail())
        self.v_detail = tk.StringVar(value="")
        tk.Label(f, textvariable=self.v_detail, background=self.PANEL, foreground=self.MUTED, anchor="w",
                 justify="left", wraplength=1000).pack(fill="x", padx=8, pady=(4, 2))
        self.v_foot = tk.StringVar(value="")
        tk.Label(f, textvariable=self.v_foot, background=self.PANEL, foreground=self.MUTED,
                 anchor="w").pack(fill="x", padx=8, pady=(0, 6))
        f.bind("<Destroy>", self._destroyed, add="+")
        self._apply_listen()
        if auto:
            self.tick()

    # pack/grid like a widget (popout packs what the factory returns)
    def pack(self, **kw):
        self.frame.pack(**kw)

    def grid(self, **kw):
        self.frame.grid(**kw)

    def tick(self):
        try:
            self.scanner.scan(self.prefs["folders"])
            self.refresh()
        finally:
            try:
                self._after = self.frame.after(REFRESH_MS, self.tick)
            except Exception:
                self._after = None

    def collect(self) -> list:
        rows = self.scanner.rows(self.prefs["folders"], self.v_old.get())
        if self.listener:
            rows += self.listener.rows()
        return merge(rows)

    def refresh(self):
        self.rows = self.collect()
        t = self.tree
        sel = t.selection()
        want = [r["key"] for r in self.rows]
        for iid in t.get_children():
            if iid not in want:
                t.delete(iid)
        for i, r in enumerate(self.rows):
            vals = columns(r)
            if t.exists(r["key"]):
                t.item(r["key"], values=vals, tags=(r["state"],))
                t.move(r["key"], "", i)
            else:
                t.insert("", i, iid=r["key"], values=vals, tags=(r["state"],))
        if sel and t.exists(sel[0]):
            self._show_detail()
        live = sum(1 for r in self.rows if r["state"] not in ("offline", "stale"))
        folders = len(self.prefs["folders"])
        lis = ""
        if self.listener:
            lis = f" · listening on UDP {self.prefs['port']}"
        elif self.v_listen.get():
            lis = " · UDP listen failed: " + (self._listen_error or "?")
        self.v_foot.set(f"{live} running, {len(self.rows)} shown · this PC's data folders"
                        + (f" + {folders} added folder{'s' if folders != 1 else ''}" if folders else "")
                        + lis + f" · refreshed {time.strftime('%H:%M:%S')}")

    def _show_detail(self):
        sel = self.tree.selection()
        r = next((x for x in self.rows if sel and x["key"] == sel[0]), None)
        if not r:
            self.v_detail.set("")
            return
        d = r["d"]
        src = ("folder " + r["source"]) if r["via"] == "folder" else ("LAN packet from " + r["source"])
        bits = [r["name"], "status: " + (d.get("status") or "—"), "path: " + (d.get("path") or "—"),
                "profile: " + (d.get("profile") or "—"), src]
        if d.get("hands_off"):
            bits.append("hands off")
        self.v_detail.set("   ·   ".join(bits))

    # ---- settings this window keeps (this PC's own overview.json only)
    _listen_error = ""

    def _prefs_changed(self):
        self.prefs["listen"] = bool(self.v_listen.get())
        self.prefs["show_old"] = bool(self.v_old.get())
        save_prefs(self.prefs, self.data_dir)
        self._apply_listen()
        self.refresh()

    def _apply_listen(self):
        want = bool(self.v_listen.get())
        if want and not self.listener:
            lis = UdpListener(self.prefs["port"])
            if lis.start():
                self.listener, self._listen_error = lis, ""
            else:
                self._listen_error = lis.error
        elif not want and self.listener:
            self.listener.stop()
            self.listener = None

    def _share_changed(self):
        cfg = self.app.s.settings
        cfg.status_broadcast = bool(self.v_share.get())
        cfg.save_quietly(self.app.s.log)
        try:
            self.app.s.log("You: All characters → share this character on the LAN "
                           + ("on" if cfg.status_broadcast else "off"))
        except Exception:
            pass

    def edit_folders(self):
        tk, ttk = self.tk, _tk()[1]
        d = tk.Toplevel(self.frame)
        d.title("All characters — folders")
        d.configure(background=self.PANEL)
        d.transient(self.frame.winfo_toplevel())
        tk.Label(d, background=self.PANEL, foreground=self.TEXT, justify="left", anchor="w", text=(
            "One folder per line: another PC's MudPilot install (e.g. M:\\MudPilot\\MudPilot — every data*\n"
            "folder in it is read) or a single data folder. Mapped drives and \\\\PC\\share paths both work.\n"
            "This PC's own data folders are always shown. Only status.json is read; nothing is written there."
        )).pack(fill="x", padx=10, pady=(10, 4))
        txt = tk.Text(d, width=70, height=8, background=self.BG, foreground=self.TEXT, insertbackground=self.TEXT)
        txt.pack(fill="both", expand=True, padx=10)
        txt.insert("1.0", "\n".join(self.prefs["folders"]))
        bar = tk.Frame(d, background=self.PANEL)
        bar.pack(fill="x", padx=10, pady=8)

        def ok():
            lines = [ln.strip().strip('"') for ln in txt.get("1.0", "end").splitlines()]
            self.set_folders([ln for ln in lines if ln])
            d.destroy()
        ttk.Button(bar, text="Save", command=ok).pack(side="right")
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right", padx=6)
        return d

    def set_folders(self, folders: list):
        seen, out = set(), []
        for x in folders:
            if x.lower() not in seen:
                seen.add(x.lower())
                out.append(x)
        self.prefs["folders"] = out[:50]
        save_prefs(self.prefs, self.data_dir)
        self.scanner.scan(self.prefs["folders"])

    def _destroyed(self, e=None):
        if e is not None and e.widget is not self.frame:
            return
        self.close()

    def close(self):
        if self._after:
            try:
                self.frame.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.scanner.close()


def main(argv=None):
    """python -m mudpilot --overview — the window on its own (no character, no game connection)."""
    tk, _ttk = _tk()
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    root.title(f"MudPilot {__version__} — All characters")
    root.configure(background=OverviewPane.PANEL)
    if os.name == "nt":
        try:
            root.iconbitmap(default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mudpilot.ico"))
        except tk.TclError:
            pass
    root.geometry("1240x360")
    pane = OverviewPane(root)
    pane.pack(fill="both", expand=True)
    root.mainloop()
    return 0
