"""Charged items: count the uses, stop using one that's out (0.8.201, Dan: "crozier is unlimited uses in a day but
would come in handy for teak or pine wands and some other several use and dead or several uses per day then none til
cleanup"). Settings → Loot → "Count charged items' uses" (item_charges_on).

MME says how many uses an item has (Items: UseCount) and whether it keeps them (Retain After Uses):
  * UseCount -1 / 0 / 9999 — unlimited (the emerald-tipped crozier): never counted.
  * Retain After Uses 0 — finite: N charges, then it's spent (teak, pine, gnarled wands). Never refills.
  * Retain After Uses 1 — per day: N uses, then none until the realm's daily cleanup (eagle helm, nexus spear).
A 'use <item>' counts once nothing turned it away within a few seconds ("You don't have…", "Nothing happens.").
What the game says beats the count: "Uses remaining: N" (Paradigm's look at an item), "has no charges" / "Nothing
happens." straight after a use = it's out. Out → MudPilot stops sending 'use' for it (one try every 30 minutes in
case it refilled), until the cleanup time (Settings; blank = 24 h after it ran out). Anything you type yourself
always goes out. Counts are kept per character in data/item_charges.json (MudPlay's ItemChargeTracker idea)."""
from __future__ import annotations

import json
import os
import re
import time

UNLIMITED = 9999
USE_RE = re.compile(r"^\s*use\s+(.+?)\s*$", re.I)
LOOK_RE = re.compile(r"^\s*(?:l|look|exa|exam|examine)\s+(.{3,}?)\s*$", re.I)
USES_RE = re.compile(r"uses?\s+remaining:\s*(\d+)", re.I)
OUT_RE = re.compile(r"\b(?:no (?:more )?(?:charges|uses)|out of (?:charges|uses)|(?:is|are|has been|have been) "
                    r"(?:used up|depleted|drained|exhausted)|no power left|has no (?:more )?power)\b", re.I)
NOTHING_RE = re.compile(r"^nothing happens\.?$", re.I)
FAIL_RE = re.compile(r"^(?:You (?:do not|don't|cannot|can't|are not|aren't|must|have no)\b|What\?|.*\bnot equipped\b|"
                     r".*\b(?:isn't|is not) here\b|There is no\b)", re.I)
GONE_RE = re.compile(r"^(?:Your |The |An? )?(.+?) (?:crumbles?|disintegrates?|turns? to dust|shatters?|vanish(?:es)?|"
                     r"fades? away|falls? apart|is destroyed)\b", re.I)
SETTLE = 4.0             # a use nothing turned away in this long has spent a charge
LINE_WINDOW = 6.0        # lines this soon after a use / look are about it
PROBE_SECS = 1800        # out: one try every half hour, in case it refilled
TELL_SECS = 600


def _norm(s) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", (s or "").strip().lower())
    return re.sub(r"\s+", " ", s)


def last_cleanup(now: float, hhmm: str) -> float | None:
    """The most recent daily cleanup at or before `now` (this PC's clock), None when no time is set."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", hhmm or "")
    if not m:
        return None
    lt = time.localtime(now)
    at = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(m.group(1)), int(m.group(2)), 0, 0, 0, -1))
    return at if at <= now else at - 86400


class ItemCharges:
    def __init__(self, session, path=None):
        self.s = session
        self.path = path
        self.data = None             # {character: {item: {"left", "max", "daily", "t", "out"}}}
        self.pending = None          # {"name", "t"}: a use waiting to be confirmed
        self._look = None            # (name, t): a look whose "Uses remaining" we expect
        self._told: dict = {}
        self._probe: dict = {}
        self._summary = None

    # ------------------------------------------------------------ data
    def _file(self):
        if self.path:
            return self.path
        from . import config
        return os.path.join(config.DATA_DIR, "item_charges.json")

    def _load(self):
        if self.data is None:
            try:
                with open(self._file(), "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                if not isinstance(self.data, dict):
                    self.data = {}
            except (OSError, ValueError):
                self.data = {}
        return self.data

    def _save(self):
        try:
            p = self._file()
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data or {}, f, indent=1)
            os.replace(tmp, p)
        except OSError:
            pass

    def _book(self) -> dict:
        who = (self.s.settings.my_name or "").strip().lower() or "_"
        return self._load().setdefault(who, {})

    def meta(self, name):
        """(max uses, per-day) for a charged item; None for unlimited / uncharged / one-shot / unknown items."""
        from .chestloot import item_named
        w = self.s.world
        it = item_named(w, name)
        g = (getattr(w, "gear", None) or {}).get(int(it["num"])) if it else None
        if not g:
            return None
        uc = int(g.get("UseCount") or 0)
        daily = bool(int(g.get("Retain After Uses") or 0))
        if uc <= 0 or uc >= UNLIMITED or (uc == 1 and not daily):
            return None
        return uc, daily

    def _refilled(self, rec, now) -> bool:
        """A per-day item whose count is from before the last cleanup has its uses back."""
        if not rec.get("daily"):
            return False
        at = last_cleanup(now, self.s.settings.cleanup_time)
        if at is None:
            return bool(rec.get("out")) and now - rec["out"] >= 86400
        return rec.get("t", 0) < at

    def record(self, name, now=None):
        now = now or time.time()
        n = _norm(name)
        rec = self._book().get(n)
        if rec and self._refilled(rec, now):
            rec.update(left=rec.get("max"), out=0, t=now)
            self.s.log(f"Item charges: {n} — cleanup has been, {rec.get('max')} uses again")
            self._save()
        return rec

    def left(self, name):
        """Uses left (None = not counted yet / not a charged item)."""
        rec = self.record(name)
        return None if not rec else rec.get("left")

    def is_out(self, name) -> bool:
        rec = self.record(name)
        return bool(rec and rec.get("left") == 0)

    def _set(self, name, left, why=""):
        mt = self.meta(name)
        if not mt:
            return
        n, now = _norm(name), time.time()
        rec = self._book().setdefault(n, {"max": mt[0], "daily": mt[1]})
        rec.update(max=mt[0], daily=mt[1], left=max(int(left), 0), t=now)
        if rec["left"] == 0:
            rec["out"] = now
            self.s.log(f"Item charges: {n} is out" + (" until cleanup" if mt[1] else " (spent)")
                       + (f" — {why}" if why else ""))
        else:
            rec["out"] = 0
            if rec["left"] <= 3 or why:
                self.s.log(f"Item charges: {n} — {self._fmt(n, rec)}" + (f" ({why})" if why else ""))
        self._save()

    @staticmethod
    def _fmt(n, rec) -> str:
        unit = "today" if rec.get("daily") else "left"
        return f"{rec.get('left')}/{rec.get('max')} {unit}"

    # ------------------------------------------------------------ what's carried
    def _held(self) -> list:
        from .gamestate import parse_item_list
        out = []
        for _q, nm in parse_item_list(self.s.state.carrying or ""):
            k = _norm(nm)
            if k not in out:
                out.append(k)
        return out

    def match_item(self, arg):
        """The charged item you carry that 'use <arg>' names ('use teak wand orc', 'use teak orc')."""
        a = _norm(arg)
        held = [h for h in self._held() if self.meta(h)]
        for h in sorted(held, key=len, reverse=True):
            if a == h or a.startswith(h + " "):
                return h
        w0 = a.split()[0] if a.split() else ""
        if len(w0) < 3:
            return None
        return next((h for h in held if any(x.startswith(w0) for x in h.split())), None)

    # ------------------------------------------------------------ hooks
    def note_send(self, cmd):
        if not self.s.settings.item_charges_on:
            return
        now = time.time()
        m = USE_RE.match(cmd or "")
        if m:
            name = self.match_item(m.group(1))
            if name:
                self._settle(now, force=True)          # the last use went through: count it before this one
                self.pending = {"name": name, "t": now}
            return
        m = LOOK_RE.match(cmd or "")
        if m:
            name = self.match_item(m.group(1))
            if name:
                self._look = (name, now)

    def feed_line(self, text):
        if not self.s.settings.item_charges_on:
            return
        t, now = (text or "").strip(), time.time()
        if not t:
            return
        m = USES_RE.search(t)
        if m:
            who = self._look[0] if self._look and now - self._look[1] < LINE_WINDOW else \
                (self.pending["name"] if self.pending and now - self.pending["t"] < LINE_WINDOW else None)
            if who:
                if self.pending and self.pending["name"] == who:
                    self.pending = None                 # the game's own count already has this use in it
                self._look = None
                self._set(who, int(m.group(1)), "the game says")
            return
        p = self.pending
        if p and now - p["t"] < LINE_WINDOW:
            if OUT_RE.search(t) or NOTHING_RE.match(t):
                self.pending = None
                self._set(p["name"], 0, f'"{t[:60]}"')
                return
            if FAIL_RE.match(t):
                self.pending = None                     # turned away: no charge spent
                return
        m = GONE_RE.match(t)
        if m:
            gone = _norm(m.group(1))
            book = self._book()
            if gone in book and not book[gone].get("daily"):
                del book[gone]                          # a spent wand crumbled away: a new one starts afresh
                self.pending = None
                self.s.log(f"Item charges: {gone} is gone")
                self._save()

    def _settle(self, now, force=False):
        p = self.pending
        if not p or (not force and now - p["t"] < SETTLE):
            return
        self.pending = None
        mt = self.meta(p["name"])
        if not mt:
            return
        rec = self.record(p["name"], now)
        left = rec.get("left") if rec else None
        if left is None or left == 0:
            left = mt[0]                                # first use seen, or it worked although we had it at 0
        self._set(p["name"], left - 1)

    def tick(self):
        if self.s.settings.item_charges_on:
            self._settle(time.time())
            self._tell_summary()

    def blocked(self, cmd, from_bot) -> bool:
        """An automatic 'use' of an item that's out: hold it (one probe every PROBE_SECS)."""
        if not from_bot or not self.s.settings.item_charges_on:
            return False
        m = USE_RE.match(cmd or "")
        if not m:
            return False
        name = self.match_item(m.group(1))
        if not name or not self.is_out(name):
            return False
        now = time.time()
        if now - self._probe.get(name, 0) >= PROBE_SECS and now - (self.record(name) or {}).get("out", 0) >= PROBE_SECS:
            self._probe[name] = now
            return False                                # one try now and then, in case it has its uses back
        if now - self._told.get(name, 0) >= TELL_SECS:
            self._told[name] = now
            rec = self.record(name) or {}
            self.s.log(f"Not using the {name} — out of charges" + (" until cleanup" if rec.get("daily") else ""))
        return True

    # ------------------------------------------------------------ show
    def summary(self) -> list:
        """['teak wand 7/10 left', 'eagle helm 0/3 today', 'pine wand (10 charges, not counted yet)'] for what you
        carry."""
        out = []
        for h in self._held():
            mt = self.meta(h)
            if not mt:
                continue
            rec = self.record(h)
            if rec and rec.get("left") is not None:
                out.append(f"{h} {self._fmt(h, rec)}")
            else:
                out.append(f"{h} ({mt[0]} {'a day' if mt[1] else 'charges'}, not counted yet)")
        return out

    def _tell_summary(self):
        if self.s.state.inv_seq == getattr(self, "_sum_seq", -1):
            return
        self._sum_seq = self.s.state.inv_seq
        got = self.summary()
        said = self.__dict__.setdefault("_said_entries", set())
        if got and got != self._summary and not set(got) <= said:
            # (only when something's new — a count, an item: Miserable PVE's rainbow stone goes on to meditate and
            #  back in the pack after, and each swap wrote the whole list again, ~1,000 times a session)
            self._summary = got
            said |= set(got)
            self.s.log("Charged items you carry: " + ", ".join(got))
