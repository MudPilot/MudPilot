"""Boss tracking: kills, sightings and respawn timers.

A boss is what MME treats as one: a monster with a regen time (hours) that spawns
from specific rooms rather than a lair group. Kills are detected when a boss you were
fighting is gone after you gain experience; sightings whenever one shows up in a room.
Timers are kept per board (data/boards/<board>/bosses.json) so they survive restarts
and are shared by every character on that board."""
from __future__ import annotations

import json
import os
import re
import time

from . import config

BOSS_FILE_OVERRIDE = None   # tests only


def fmt_dur(secs: float) -> str:
    secs = int(abs(secs))
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _hm(secs: float) -> str:
    secs = max(0, int(secs))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    out = (f"{d}d " if d else "") + (f"{h}h " if h or d else "") + f"{m}m"
    return out.strip()


def _parse_hm(text: str) -> float | None:
    t = (text or "").lower().replace("ago", "").strip(" .")
    if t in ("now", "ready", "due", "just now"):
        return 0.0
    total, hit = 0.0, False
    for n, u in re.findall(r"(\d+)\s*(w|d|h|m)", t):
        hit = True
        total += int(n) * {"w": 604800, "d": 86400, "h": 3600, "m": 60}[u]
    return total if hit else None


class BossTracker:
    def __init__(self, session):
        self.s = session
        self.data: dict = {}          # monster num (str) -> record
        self._pending: dict = {}      # num -> (time we gained exp with it present)
        self.on_change = lambda: None
        self.load()

    # ------------------------------------------------------------ storage
    @property
    def file(self) -> str:
        if BOSS_FILE_OVERRIDE:
            return BOSS_FILE_OVERRIDE
        return os.path.join(config.board_dir(self.s.settings.board), "bosses.json")

    def load(self):
        try:
            with open(self.file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.file)

    # ------------------------------------------------------------ which bosses count
    def _drop_nums(self) -> set:
        """Monsters MME says drop an item (cached per world)."""
        w = self.s.world
        if getattr(self, "_drops_for", None) is not w:
            import re
            nums = set()
            for src in (getattr(w, "gear", None) or {}, getattr(w, "items", None) or {}):
                for g in src.values():
                    nums.update(int(n) for n in re.findall(r"Monster #(\d+)", (g or {}).get("obtained", "") or ""))
            self._drops, self._drops_for = nums, w
        return self._drops

    def killable(self, mon: dict | None) -> bool:
        """Worth tracking: can be fought (not a 999-protected town NPC) and gives exp or drops something."""
        if not mon:
            return False
        ab = mon.get("abils") or {}
        if ab.get(28, 0) >= 999 or ab.get(139, 0) >= 999:
            return False                  # healers, messengers, guildmasters… can't be killed
        return (mon.get("exp") or 0) > 5 or mon["num"] in self._drop_nums()

    def rec(self, mon: dict) -> dict:
        r = self.data.setdefault(str(mon["num"]), {"name": mon["name"], "kills": []})
        r["name"] = mon["name"]
        return r

    # ------------------------------------------------------------ events
    def bosses_in_view(self):
        """Bosses in the room — and any monster you've put on the list by hand (pMUD: track anything)."""
        v = self.s.state.view
        if not v:
            return []
        out = []
        for _shown, rec in v.monsters:
            if not rec:
                continue
            if (self.data.get(str(rec["num"])) or {}).get("manual"):
                if rec not in out:
                    out.append(rec)
                continue
            b = rec if rec.get("boss") else self.s.world.boss_named(rec["name"])
            if b and b.get("boss") and b not in out:
                out.append(b)
        return out

    # ------------------------------------------------------------ by hand (pMUD's Monster Stats window)
    def respawn_secs(self, num) -> float:
        """How long it takes to come back: your own figure for it, else MME's regen hours."""
        r = self.data.get(str(num), {})
        if r.get("respawn_min"):
            return float(r["respawn_min"]) * 60
        mon = self.s.world.monsters.get(int(num))
        return float((mon or {}).get("regen_h", 0) or 0) * 3600

    def track(self, mon: dict, respawn_min: float | None = None):
        r = self.rec(mon)
        r["manual"] = True
        if respawn_min:
            r["respawn_min"] = float(respawn_min)
        self.save()
        self.on_change()

    def set_kill_time(self, mon: dict, when: float, by="set by hand"):
        """A kill you didn't see (someone else got it, or it died before you logged on)."""
        r = self.rec(mon)
        if by == "set by hand":
            r["manual"] = r.get("manual") or not mon.get("boss")
        r["last_kill"] = r["dead_since"] = when
        r.pop("check_at", None)
        r["kills"] = (r.get("kills") or [])[-49:] + [{"t": when, "by": by, "room": None}]
        r.pop("announced", None)
        self.save()
        self.on_change()

    def set_next_spawn(self, mon: dict, when: float, by="set by hand") -> bool:
        regen = self.respawn_secs(mon["num"])
        if not regen:
            return False
        self.set_kill_time(mon, when - regen, by=by)
        return True

    # ------------------------------------------------------------ shared timers (pMUD's @spawn)
    def spawn_reply(self, mon: dict) -> str:
        """'Ice Queen: dead - Next spawn: 2h 5m' / 'Ice Queen: live - Last known kill: 3h 2m ago'."""
        r = self.data.get(str(mon["num"])) or {}
        now = time.time()
        regen = self.respawn_secs(mon["num"])
        dead = r.get("dead_since")
        if dead and regen and dead + regen > now:
            return f"{mon['name']}: dead - Next spawn: {_hm(dead + regen - now)}"
        if r.get("last_kill"):
            return f"{mon['name']}: live - Last known kill: {_hm(now - r['last_kill'])} ago"
        return f"{mon['name']}: no available data"

    SPAWN_REPLY_RE = re.compile(r"^\{?\s*(.+?)\s*:\s*(dead|live)\s*-\s*(?:next\s+spawn\s*:\s*(.+?)|"
                                r"last\s+known\s+kill\s*:\s*(.+?))\s*\}?\s*$", re.I)

    def ingest_spawn_reply(self, sender: str, text: str) -> bool:
        """Another bot's answer to @spawn: learn the kill time from it (only for monsters on your list, or
        bosses). Returns True if it was one."""
        m = self.SPAWN_REPLY_RE.match((text or "").strip())
        if not m:
            return False
        mon = self.s.world.boss_named(m.group(1)) or self.s.world.identify_monster(m.group(1))
        if not mon or str(mon["num"]) not in self.data:
            return True                              # only monsters already on your list
        secs = _parse_hm(m.group(3) or m.group(4) or "")
        if secs is None:
            return True
        now = time.time()
        if m.group(2).lower() == "dead":
            if not self.set_next_spawn(mon, now + secs, by=f"from {sender}"):
                return True
        else:
            r = self.rec(mon)
            regen = self.respawn_secs(mon["num"])
            if r.get("dead_since") and regen and r["dead_since"] + regen > now:
                return True                          # by your own clock it's still down: keep it
            if not r.get("last_kill") or r["last_kill"] < now - secs - 60:
                r["last_kill"] = now - secs
                r["seen"] = now
                r.pop("dead_since", None)
                self.save()
                self.on_change()
        self.s.log(f"Timer from {sender}: {text.strip('{} ')}")
        return True

    def on_room(self, state):
        now = time.time()
        here = list(state.candidates) if state.candidates else []
        present = {b["num"] for b in self.bosses_in_view()}
        changed = False
        for mon in self.bosses_in_view():
            if not self.killable(mon):
                continue
            r = self.rec(mon)
            r["seen"] = now
            r["seen_room"] = list(here[0]) if len(here) == 1 else r.get("seen_room")
            r.pop("dead_since", None)
            changed = True
        # a boss we were fighting is gone after the exp came in -> killed
        for num, t in list(self._pending.items()):
            if now - t > 90:
                del self._pending[num]
                continue
            if num not in present and not state.in_combat:
                self.record_kill(self.s.world.monsters[num], by="you")
                try:
                    self.s.bosshunt.after_kill(num)    # pick up what it dropped (not chests)
                except AttributeError:
                    pass
                del self._pending[num]
                changed = True
        if changed:
            self.save()
            self.on_change()

    def on_exp(self, n):
        now = time.time()
        for mon in self.bosses_in_view():
            if self.killable(mon):
                self._pending[mon["num"]] = now
        # its death line ("The crimson mist suddenly solidifies and vanishes in a shower of blood!") already took it
        # off the room list before this exp line: count the one the exp was credited to
        b = self._tracked(getattr(self.s.state, "last_kill_rec", None))
        if b and self.killable(b):
            self._pending[b["num"]] = now

    def _tracked(self, rec):
        """Its boss-list record: a boss, or one you've added by hand (the same test as bosses_in_view)."""
        if not rec:
            return None
        if (self.data.get(str(rec["num"])) or {}).get("manual"):
            return rec
        b = rec if rec.get("boss") else self.s.world.boss_named(rec["name"])
        return b if b and b.get("boss") else None

    def record_kill(self, mon: dict, by="you", when: float | None = None):
        when = when or time.time()
        r = self.rec(mon)
        r["last_kill"] = when
        r["dead_since"] = when
        r.pop("check_at", None)                        # its own clock now (bosshunt: no more blind checks)
        r["kills"] = (r.get("kills") or [])[-49:] + [{"t": when, "by": by,
                                                      "room": list(self.s.state.room) if self.s.state.room else None}]
        self.s.log(f"Boss killed: {mon['name']} — respawns in ~{fmt_dur(self.respawn_secs(mon['num']))}")
        if hasattr(self.s, "timeline"):
            self.s.timeline.event("boss", mon["name"])
        self.save()
        self.on_change()

    def mark_alive(self, mon: dict):
        r = self.rec(mon)
        r["seen"] = time.time()
        r.pop("dead_since", None)
        self.save()
        self.on_change()

    def forget(self, num):
        self.data.pop(str(num), None)
        self.save()
        self.on_change()

    # ------------------------------------------------------------ status
    def status(self, num) -> tuple[str, float | None]:
        """(text, seconds until respawn — negative = overdue / None)"""
        r = self.data.get(str(num), {})
        mon = self.s.world.monsters.get(int(num))
        now = time.time()
        regen = self.respawn_secs(num)
        dead = r.get("dead_since")
        if dead and regen:
            left = dead + regen - now
            if left > 0:
                return f"dead - respawns in {fmt_dur(left)}", left
            return f"should be up (due {fmt_dur(-left)} ago)", left
        if r.get("seen"):
            return f"seen alive {fmt_dur(now - r['seen'])} ago", None
        return "no data yet", None

    def tracked(self) -> list:
        """Bosses on the list: killable ones you've killed at least once (or added by hand).
        Ones only ever seen alive stay out — the clock that matters starts at the kill."""
        out = []
        for num, r in self.data.items():
            mon = self.s.world.monsters.get(int(num))
            if mon and (r.get("manual") or (self.killable(mon) and (r.get("last_kill") or r.get("kills")))):
                out.append(mon)
        return out

    def tick(self):
        """Announce once when a timer comes due."""
        now = time.time()
        for num, r in self.data.items():
            mon = self.s.world.monsters.get(int(num))
            if not mon or not r.get("dead_since") or r.get("announced") == r["dead_since"]:
                continue
            regen = self.respawn_secs(num)
            if regen and now >= r["dead_since"] + regen:
                r["announced"] = r["dead_since"]
                self.s.log(f"Boss timer: {mon['name']} should be back up")
                self.s.on_alert(f"{mon['name']} should be back up")
                self.save()
                self.on_change()
