"""Combat round clock: learns the game's round length from when the hits/misses land, so the
status bar can count down to the next round (MegaMUD 2.0's reverse bar) — handy for PvP timing, and so
mid-fight blesses and heals go out where they don't cost a round.

Every round, all the attack lines for that round arrive together. A new burst after a quiet gap
is a round going off. The round length is always measured from the last 40 gaps between bursts: the
shortest gap that keeps recurring is one round, every gap is fitted as a whole number of rounds (a round
nothing happened in shows as a double gap), and the length is the total time over the total rounds. It's
never taken on trust from before: Buddy's clock read 8.2 s through 1,946 rounds of 5 s, because once learned
it only refined itself against its own guess and the saved one came back after every restart (Dan,
2026-11-04: "it should time rounds and determine that for itself"). Until it has seen a few rounds it
assumes 5 seconds.

The game's rounds are one server-wide beat (pMUD keeps its phase across fights and restarts), so once the
length is known it's refined over a long stretch of rounds and the phase carries across walking, resting and
a restart (saved to a small file). A round that lands well off the prediction re-syncs it at once.
"""
from __future__ import annotations

import json
import os
import re
import time

COMBAT_LINE = re.compile(
    r"\bfor \d+ damage\b|\bmiss(?:es)?\b|\bdodge\b|glances off|\bswipes at\b|\bclaws at\b|\blunges at\b|"
    r"\bswings at\b|\bstrikes\b|\bblasts\b|\bshocked for\b|absorbs the energy|\bbites at\b|\bkicks at\b|"
    r"\bpunches at\b|\bslashes at\b|\bstabs at\b", re.I)
GAP = 1.2           # lines closer together than this belong to the same round
RESYNC = 0.8        # a round this far off the predicted beat: take its phase instead
CARRY = 1800        # carry the phase across this long without a fight
SAVED_MAX_AGE = 6 * 3600
KEEP_GAPS = 40


class CombatClock:
    def __init__(self, path: str | None = None):
        self.last_line = 0.0
        self.last_round = 0.0
        self.gaps: list = []
        self.period = 5.0
        self.learned = False
        self.anchor = 0.0           # a round's time on the beat; rounds land at anchor + n × period
        self.path = path
        self._saved_at = 0.0
        self.load()

    def feed(self, text: str, now: float | None = None):
        if not COMBAT_LINE.search(text or ""):
            return
        now = now or time.time()
        if now - self.last_line > GAP:
            if self.last_round:
                gap = now - self.last_round
                if 2.0 <= gap <= 30:
                    self.gaps.append(gap)
                    self.gaps = self.gaps[-KEEP_GAPS:]
                    p = self.measure()
                    if p:
                        self.period, self.learned = p, True
            self._on_beat(now)
            self.last_round = now
        self.last_line = now

    def measure(self):
        """The round length from the gaps seen, or None while there aren't enough to tell."""
        g = self.gaps
        if len(g) < 4:
            return None
        # one round: the shortest gap that keeps coming back (a longer one is rounds nothing happened in)
        need = max(3, len(g) // 4)
        base = next((x for x in sorted(g) if sum(1 for y in g if abs(y - x) <= 0.12 * x) >= need), None)
        if not base:
            return None
        rounds = [max(1, round(x / base)) for x in g]
        fit = [(x, k) for x, k in zip(g, rounds) if abs(x - k * base) <= 0.15 * base]
        if len(fit) < need:
            return None
        p = sum(x for x, _k in fit) / sum(k for _x, k in fit)
        return p if 2.0 <= p <= 10 else None

    def _on_beat(self, now):
        if not self.learned:
            return
        if not self.anchor:
            self.anchor = now
            return
        n = round((now - self.anchor) / self.period)
        err = now - (self.anchor + n * self.period)
        if abs(err) > RESYNC or n <= 0:
            self.anchor = now                       # off the beat (or a stale saved one): re-sync on this round
        self.save(now)

    def _fresh(self, now) -> bool:
        if self.anchor and self.learned and now - max(self.last_round, self.anchor) <= CARRY:
            return True
        return bool(self.last_round) and now - self.last_round <= self.period * 6

    def _phase_from(self):
        return self.anchor if (self.anchor and self.learned) else self.last_round

    def left(self, now: float | None = None):
        """(seconds to the next round, fraction of the round left) — None if the beat isn't known."""
        now = now or time.time()
        if not self._fresh(now):
            return None
        since = (now - self._phase_from()) % self.period
        rem = self.period - since
        return rem, rem / self.period

    def same_round(self, t1: float, t2: float) -> bool | None:
        """Were t1 and t2 in the same game round? None = no fight seen lately to tell by."""
        if not self.learned or not self._fresh(t2):
            return None
        import math
        base = self._phase_from()
        a = math.floor((t1 - base) / self.period)
        b = math.floor((t2 - base) / self.period)
        return a == b

    # ------------------------------------------------------------ across restarts
    def save(self, now=None):
        now = now or time.time()
        if not self.path or not self.anchor or now - self._saved_at < 60:
            return
        self._saved_at = now
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"period": self.period, "anchor": self.anchor, "t": now}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            p, a, t = float(d["period"]), float(d["anchor"]), float(d["t"])
        except (OSError, ValueError, KeyError, TypeError):
            return
        if 2.0 <= p <= 10 and time.time() - t < SAVED_MAX_AGE:
            self.period, self.anchor, self.learned = p, a, True
            self.last_round = t
