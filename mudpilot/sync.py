"""Settings sync between PCs (e.g. your main PC and the MiniPC).

Pick a folder both PCs can see — OneDrive, Dropbox, a network share — on each PC (Settings →
General → Sync between PCs). MudPilot keeps a "MudPilot sync" folder in there up to date:
  * characters & settings (data\\profiles), macros, paths, players;
  * what it has learned — lair refill times and lair damage, loop stats, boss timers, daily
    history, auto-tune results, death replays.
Learned data is MERGED (both PCs' laps, kills and samples are kept); everything else is
newest-wins, and whatever gets replaced is backed up first (data\\sync_backup). Passwords and the
ntfy topic are never in these files (they're in Windows Credential Manager on each PC). The map
data (world.db), logs and reports stay on each PC.

When: on start, every 30 minutes, when MudPilot closes, and with "Sync now". The character
you're playing only takes the other PC's settings at start-up (never mid-session).
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import time

from . import config

LOCAL_STATE = os.path.join(config.DATA_DIR, "sync.json")      # this PC's sync folder — never synced
SUB = "MudPilot sync"
INCLUDE = ["macros.json", "profiles/*.json", "deaths/*.json",
           "boards/*/players.json", "boards/*/bosses.json", "boards/*/loop_stats.json", "boards/*/lairs.json",
           "boards/*/history.json", "boards/*/autotune.json", "boards/*/paths/*", "boards/*/paths/*/*",
           "boards/*/paths/*/*/*"]
EXCLUDE = ["*.tmp", "*.db", "*.db.old", "*.log", "*secret*", "*password*", "*.bak"]
MERGE = {"lairs.json", "history.json", "bosses.json", "loop_stats.json"}


def load_state() -> dict:
    try:
        with open(LOCAL_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(d: dict):
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(LOCAL_STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    except OSError:
        pass


def _wanted(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if any(fnmatch.fnmatch(os.path.basename(rel), e) for e in EXCLUDE):
        return False
    return any(fnmatch.fnmatch(rel, p) for p in INCLUDE)


def _walk(root: str) -> set:
    out = set()
    if not os.path.isdir(root):
        return out
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/")
            if _wanted(rel):
                out.add(rel)
    return out


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, p)


# ---------------------------------------------------------------- merges
def _by_time(a: list, b: list, key, keep=None):
    seen, out = set(), []
    for x in sorted((a or []) + (b or []), key=key):
        k = json.dumps(x, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out[-keep:] if keep else out


def merge(name: str, a, b):
    """Combine two copies of a learned-data file."""
    if a is None:
        return b
    if b is None:
        return a
    if name == "lairs.json":
        out = {}
        for k in set(a) | set(b):
            x, y = a.get(k) or {}, b.get(k) or {}
            out[k] = {"empty": max(x.get("empty", 0), y.get("empty", 0)),
                      "s": _by_time(x.get("s"), y.get("s"), key=lambda v: v[2] if len(v) > 2 else 0, keep=30),
                      "dmg": _by_time(x.get("dmg"), y.get("dmg"), key=lambda v: v[1] if isinstance(v, list) else 0,
                                      keep=12)}
        return out
    if name == "history.json":
        out = {}
        for who in set(a) | set(b):
            da, db_ = a.get(who) or {}, b.get(who) or {}
            out[who] = {day: (da[day] if (da.get(day, {}).get("on", 0) >= db_.get(day, {}).get("on", 0)) else db_[day])
                        for day in set(da) | set(db_)}
        return out
    if name == "bosses.json":
        out = {}
        for num in set(a) | set(b):
            x, y = a.get(num) or {}, b.get(num) or {}
            r = {**y, **x}
            r["kills"] = _by_time(x.get("kills"), y.get("kills"), key=lambda v: v.get("t", 0), keep=50)
            for f in ("last_kill", "dead_since", "seen"):
                vals = [v for v in (x.get(f), y.get(f)) if v]
                if vals:
                    r[f] = max(vals)
            if r.get("seen") and r.get("dead_since") and r["seen"] > r["dead_since"]:
                r.pop("dead_since", None)                    # seen alive after the kill
            out[num] = r
        return out
    if name == "loop_stats.json":
        out = {}
        for k in set(a) | set(b):
            x, y = a.get(k) or {}, b.get(k) or {}
            by = {}
            for who in set(x.get("by") or {}) | set(y.get("by") or {}):
                by[who] = _by_time((x.get("by") or {}).get(who), (y.get("by") or {}).get(who),
                                   key=lambda v: v.get("t", 0), keep=60)
            out[k] = {"title": x.get("title") or y.get("title"), "by": by}
        return out
    return a


class Sync:
    def __init__(self, session):
        self.s = session
        self.last = ""
        self._next = 0.0

    @property
    def folder(self) -> str:
        return load_state().get("folder", "")

    def set_folder(self, path: str):
        st = load_state()
        st["folder"] = (path or "").strip()
        save_state(st)

    def tick(self):
        now = time.time()
        if now < self._next:
            return
        first = not self._next
        self._next = now + 30 * 60
        if not first and self.folder:          # the first run happens at start-up (startup=True)
            self.sync_now()

    def _flush(self):
        s = self.s
        for fn in (lambda: s.history.save(), lambda: s.lairclock.save(force=True), lambda: s.bosses.save(),
                   lambda: s.loopstats.save(), lambda: s.players.save() if hasattr(s.players, "save") else None,
                   lambda: s.settings.save()):
            try:
                fn()
            except Exception:
                pass

    def _reload(self, changed: set):
        s = self.s
        if any(c.endswith("history.json") for c in changed):
            s.history._for = None
        if any(c.endswith("lairs.json") for c in changed):
            s.lairclock._for = None
        if any(c.endswith("loop_stats.json") for c in changed):
            s.loopstats._loaded_for = None
        if any(c.endswith("bosses.json") for c in changed):
            try:
                s.bosses.load()
            except Exception:
                pass
        if any("/paths/" in c for c in changed):
            try:
                s.load_saved_paths()
                s.on_paths_changed()
            except Exception:
                pass

    def sync_now(self, startup=False) -> str:
        root = self.folder
        if not root:
            self.last = "no sync folder set"
            return self.last
        if not os.path.isdir(root):
            self.last = f"sync folder not found: {root}"
            return self.last
        remote = os.path.join(root, SUB)
        local = config.DATA_DIR
        self._flush()
        active = os.path.relpath(config.Settings.profile_path(self.s.settings.profile), local).replace("\\", "/")
        pulled, pushed, merged, held = set(), set(), set(), 0
        backup = os.path.join(local, "sync_backup", time.strftime("%Y%m%d-%H%M%S"))
        try:
            for rel in sorted(_walk(local) | _walk(remote)):
                lp, rp = os.path.join(local, rel), os.path.join(remote, rel)
                name = os.path.basename(rel)
                if name in MERGE:
                    a, b = _load(lp), _load(rp)
                    m = merge(name, a, b)
                    if m is None:
                        continue
                    if m != a:
                        _write(lp, m)
                        pulled.add(rel)
                    if m != b:
                        _write(rp, m)
                        pushed.add(rel)
                    if m != a or m != b:
                        merged.add(rel)
                    continue
                le, re_ = os.path.exists(lp), os.path.exists(rp)
                if le and not re_:
                    os.makedirs(os.path.dirname(rp), exist_ok=True)
                    shutil.copy2(lp, rp)
                    pushed.add(rel)
                elif re_ and not le:
                    if rel == active and not startup:
                        held += 1
                        continue
                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                    shutil.copy2(rp, lp)
                    pulled.add(rel)
                else:
                    lm, rm = os.path.getmtime(lp), os.path.getmtime(rp)
                    if abs(lm - rm) < 2:
                        continue
                    if lm > rm:
                        shutil.copy2(lp, rp)
                        pushed.add(rel)
                    else:
                        if rel == active and not startup:
                            held += 1                  # the character you're playing: only at start-up
                            continue
                        os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
                        shutil.copy2(lp, os.path.join(backup, rel))
                        shutil.copy2(rp, lp)
                        pulled.add(rel)
        except OSError as ex:
            self.last = f"sync failed: {ex}"
            self.s.log(f"Sync: {self.last}")
            return self.last
        self._reload(pulled)
        if startup and active in pulled:
            try:
                fresh = config.Settings.load(self.s.settings.profile)
                for k, v in vars(fresh).items():
                    setattr(self.s.settings, k, v)
                self.s.on_settings_changed()
            except Exception:
                pass
        st = load_state()
        st["last"] = time.time()
        save_state(st)
        self.last = (f"synced {time.strftime('%H:%M')}: {len(pulled)} in, {len(pushed)} out"
                     + (f", {len(merged)} merged" if merged else "")
                     + (" — this character's settings come over at next start" if held else ""))
        if pulled or pushed:
            self.s.log("Sync: " + self.last)
        return self.last
