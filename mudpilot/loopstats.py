"""Loop history: how every loop actually pays, lap by lap, kept between sessions.

Each finished lap records: how long it took, exp and kills, rests, deaths, your level, and how
many lair rooms on it had monsters waiting vs. were empty (empty lairs = you're lapping faster
than they respawn). Paths tab → Loops shows each loop's recent exp/hr; More → Loop stats… shows
the full table so you can see which loop is best at your level.

Saved per board and character in data\\boards\\<board>\\loop_stats.json.
"""
from __future__ import annotations

import json
import os
import time

from . import config

KEEP_LAPS = 60          # per loop and character


class LoopStats:
    def __init__(self, session):
        self.s = session
        self.data: dict = {}
        self._lap = None          # the lap in progress
        self._loaded_for = None

    # ------------------------------------------------------------ storage
    def path(self):
        return os.path.join(config.board_dir(self.s.settings.board), "loop_stats.json")

    def _load(self):
        key = self.s.settings.board
        if self._loaded_for == key:
            return
        self._loaded_for = key
        try:
            with open(self.path(), encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path()), exist_ok=True)
            tmp = self.path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=0)
            os.replace(tmp, self.path())
        except OSError:
            pass

    def who(self):
        return (self.s.settings.my_name or self.s.settings.profile or "?").lower()

    # ------------------------------------------------------------ recording
    def lap_start(self, loop):
        st = self.s.state
        self._lap = {"key": self.s.bot.x.loop_key(loop), "title": loop.title, "t": time.time(),
                     "exp": st.exp_gained, "kills": st.kills, "rests": self.s.stats.rests,
                     "deaths": getattr(self, "_deaths", 0), "lairs_full": 0, "lairs_empty": 0, "seen": set()}

    def reset_baseline(self):
        """Exp counters were just reset (new loop) — measure from here."""
        if self._lap:
            self._lap.update({"exp": 0, "kills": 0, "t": time.time()})

    def note_room(self, room, view):
        """Each new room on a lap: was its lair stocked?"""
        lap = self._lap
        if not lap or not room or room in lap["seen"]:
            return
        r = self.s.world.room(room)
        if not r or not r.lair:
            return
        lap["seen"].add(room)
        if view and view.monsters:
            lap["lairs_full"] += 1
        else:
            lap["lairs_empty"] += 1

    def note_death(self):
        self._deaths = getattr(self, "_deaths", 0) + 1

    def lap_end(self, loop):
        """Called when a lap finishes; starts the next one."""
        lap = self._lap
        st = self.s.state
        rec = None
        if lap and lap["key"] == self.s.bot.x.loop_key(loop):
            secs = time.time() - lap["t"]
            if secs >= 20:                        # ignore half laps (resumed mid-way etc.)
                rec = {"t": round(time.time()), "secs": round(secs), "exp": max(0, st.exp_gained - lap["exp"]),
                       "kills": max(0, st.kills - lap["kills"]), "rests": max(0, self.s.stats.rests - lap["rests"]),
                       "deaths": max(0, getattr(self, "_deaths", 0) - lap["deaths"]),
                       "level": st.level or self.s.settings.char_level or 0,
                       "lairs_full": lap["lairs_full"], "lairs_empty": lap["lairs_empty"]}
                self._load()
                bucket = self.data.setdefault(lap["key"], {"title": lap["title"], "by": {}})
                bucket["title"] = lap["title"]
                laps = bucket["by"].setdefault(self.who(), [])
                laps.append(rec)
                del laps[:-KEEP_LAPS]
                self.save()
                eh = rec["exp"] / secs * 3600
                self.s.log(f"Lap {self.s.bot.laps}: {secs / 60:.1f} min, {rec['exp']:,} exp "
                           f"({eh / 1000:,.0f}k/hr), {rec['kills']} kills, {rec['rests']} rests, "
                           f"lairs {rec['lairs_full']} stocked / {rec['lairs_empty']} empty")
        self.lap_start(loop)
        return rec

    def lap_secs(self, loop) -> float | None:
        """How long a lap of this loop really takes you (fights and all): the quickest of your last few."""
        self._load()
        b = self.data.get(self.s.bot.x.loop_key(loop)) or {}
        laps = (b.get("by") or {}).get(self.who(), [])[-5:]
        secs = [x.get("secs") for x in laps if x.get("secs")]
        return float(min(secs)) if secs else None

    # ------------------------------------------------------------ reading
    def summary(self, key, who=None, last=10) -> dict | None:
        """Recent laps for a loop: exp/hr, minutes per lap, rests per lap, empty-lair share."""
        self._load()
        b = self.data.get(key)
        if not b:
            return None
        laps = b["by"].get(who or self.who(), [])[-last:]
        if not laps:
            return None
        secs = sum(l["secs"] for l in laps) or 1
        lairs = sum(l["lairs_full"] + l["lairs_empty"] for l in laps)
        return {"title": b.get("title", key), "laps": len(laps), "exp_hr": sum(l["exp"] for l in laps) / secs * 3600,
                "lap_min": secs / len(laps) / 60, "rests": sum(l["rests"] for l in laps) / len(laps),
                "deaths": sum(l["deaths"] for l in laps),
                "empty_lairs": (sum(l["lairs_empty"] for l in laps) / lairs) if lairs else None,
                "level": laps[-1].get("level"), "when": laps[-1]["t"]}

    def all_summaries(self, who=None):
        self._load()
        out = []
        for key in self.data:
            sm = self.summary(key, who)
            if sm:
                out.append((key, sm))
        out.sort(key=lambda kv: -kv[1]["exp_hr"])
        return out
