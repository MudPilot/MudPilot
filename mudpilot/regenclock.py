"""Regen clock: learns MajorMUD's regen tick while you rest — how often HP/mana come back and
how much each tick gives (as % of max) — so a rest can end on a tick instead of sitting through
one more full tick for the last 1-2%.

A tick is an HP or mana rise on the prompt while resting/meditating with no heal cast just
before it. The period is the median gap between ticks in one sitting; the gain is the median
rise per tick. Until it has seen a few ticks it knows nothing and changes nothing.
"""
from __future__ import annotations

import statistics
import time


class RegenClock:
    def __init__(self):
        self.last = None              # (hp, ma) on the previous prompt
        self.last_tick = 0.0
        self.gaps: list = []
        self.hp_gain: list = []       # % of max per tick
        self.ma_gain: list = []
        self.period = None
        # (0.8.227, PVE logs: meditating, HP ticks every ~5-10 s but mana only every ~15-30 s — one shared period
        #  made the top-off wait 7 s for a mana tick that never came) — each stat's own tick gap too
        self.last_stat = {"hp": 0.0, "ma": 0.0}
        self.stat_gaps = {"hp": [], "ma": []}
        self._sat_at = 0.0

    @property
    def learned(self) -> bool:
        return self.period is not None and (len(self.hp_gain) >= 3 or len(self.ma_gain) >= 3)

    def gain(self, which) -> float:
        lst = self.hp_gain if which == "hp" else self.ma_gain
        return statistics.median(lst) if len(lst) >= 3 else 0.0

    def feed(self, resting: bool, hp, max_hp, ma, max_ma, healed_recently=False, now=None):
        now = now or time.time()
        cur = (hp, ma)
        prev, self.last = self.last, cur
        if not resting:
            self._sat_at = 0.0
            return False
        if not self._sat_at:
            self._sat_at = now
            self.last_tick = 0.0
            self.last_stat = {"hp": 0.0, "ma": 0.0}
            return False
        if prev is None or healed_recently:
            return False
        dhp = (hp - prev[0]) if hp is not None and prev[0] is not None else 0
        dma = (ma - prev[1]) if ma is not None and prev[1] is not None else 0
        if dhp <= 0 and dma <= 0:
            return False
        # a tick
        if self.last_tick:
            gap = now - self.last_tick
            if 2.0 <= gap <= 90:
                self.gaps = (self.gaps + [gap])[-20:]
                if len(self.gaps) >= 2:
                    self.period = statistics.median(self.gaps)
        for k, dv in (("hp", dhp), ("ma", dma)):
            if dv > 0:
                if self.last_stat[k] and 2.0 <= now - self.last_stat[k] <= 90:
                    self.stat_gaps[k] = (self.stat_gaps[k] + [now - self.last_stat[k]])[-20:]
                self.last_stat[k] = now
        if dhp > 0 and max_hp:
            self.hp_gain = (self.hp_gain + [100.0 * dhp / max_hp])[-20:]
        if dma > 0 and max_ma:
            self.ma_gain = (self.ma_gain + [100.0 * dma / max_ma])[-20:]
        self.last_tick = now
        return True

    def stat_period(self, which):
        """Median gap between ticks that raised this stat ('hp' / 'ma'), or None until seen twice."""
        g = self.stat_gaps.get(which) or []
        return statistics.median(g) if len(g) >= 2 else None

    def just_ticked(self, now=None, within=2.0) -> bool:
        return bool(self.last_tick) and (now or time.time()) - self.last_tick <= within

    def next_in(self, now=None):
        if not self.learned or not self.last_tick:
            return None
        return max(0.0, self.last_tick + self.period - (now or time.time()))
