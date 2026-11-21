"""Lair refill clock: learns how long each lair room takes to fill back up.

Every time we're in a lair room and it's empty, that's "last seen empty". Arriving later, the
time since then is a sample: stocked (monsters waiting) or still empty. The refill estimate for
a room is the shortest wait after which most visits found it stocked. With an estimate, a loop
can rest a bit *before* walking into a lair that isn't ready yet, instead of walking in, finding
it empty, and resting later anyway.

Kept per board in data\\boards\\<board>\\lairs.json (shared by your characters on that board).
"""
from __future__ import annotations

import json
import os
import time

from . import config

KEEP = 30          # samples per room
MIN_SAMPLES = 5


class LairClock:
    def __init__(self, session):
        self.s = session
        self.data: dict = {}
        self._for = None
        self._dirty = 0.0

    def path(self):
        return os.path.join(config.board_dir(self.s.settings.board), "lairs.json")

    def _load(self):
        if self._for == self.s.settings.board:
            return
        self._for = self.s.settings.board
        try:
            with open(self.path(), encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self, force=False):
        if not self._dirty or (not force and time.time() - self._dirty < 60):
            return
        self._dirty = 0.0
        try:
            os.makedirs(os.path.dirname(self.path()), exist_ok=True)
            tmp = self.path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path())
        except OSError:
            pass

    @staticmethod
    def key(room):
        return f"{room[0]}/{room[1]}"

    def _rec(self, room):
        self._load()
        return self.data.setdefault(self.key(room), {"empty": 0, "s": []})

    # ------------------------------------------------------------ learning
    def arrive(self, room, stocked: bool, now=None):
        """First look at a lair room this visit."""
        now = now or time.time()
        r = self._rec(room)
        if r.get("empty"):
            el = now - r["empty"]
            if 2 <= el <= 3600:
                r["s"] = (r["s"] + [[round(el), 1 if stocked else 0, round(now)]])[-KEEP:]   # time: for merging PCs
                self._dirty = self._dirty or now
        if not stocked:
            r["empty"] = now

    def seen_empty(self, room, now=None):
        """Standing in it and nothing's here (we cleared it)."""
        r = self._rec(room)
        r["empty"] = now or time.time()
        self._dirty = self._dirty or r["empty"]

    def estimate(self, room):
        """Seconds a cleared lair takes to have monsters again (None until learned)."""
        self._load()
        r = self.data.get(self.key(room))
        if not r or len(r["s"]) < MIN_SAMPLES:
            return None
        ss = sorted((x[0], x[1]) for x in r["s"])
        for el, stocked in ss:
            if not stocked:
                continue                     # the answer is always a wait that did find monsters
            later = [x for x in ss if x[0] >= el]
            if len(later) >= 2 and sum(x[1] for x in later) / len(later) >= 0.6:
                return float(el)
        return None

    def remaining(self, room, now=None):
        """Seconds until this lair should be stocked again (0 = should be now; None = unknown)."""
        est = self.estimate(room)
        r = self.data.get(self.key(room)) if est is not None else None
        if not r or not r.get("empty"):
            return None
        return max(0.0, est - ((now or time.time()) - r["empty"]))
