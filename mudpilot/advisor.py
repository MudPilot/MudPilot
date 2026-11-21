"""Loop advisor: is this still the right loop for you?

Every 10 laps (and whenever Loop stats is opened) it looks at:
  * your other loops at about your level (±3) — one paying 20%+ more gets named;
  * this loop's own trend — the last 10 laps vs the 10 before (down 25%+ = lairs emptying,
    competition, or you've outgrown it);
  * empty lairs (50%+ empty → lair pacing / rotation), deaths on it lately;
  * what the loop builder thinks a loop around here could do.
Advice goes in the log (only when it changes) and at the top of Loop stats.
"""
from __future__ import annotations

import time


class Advisor:
    def __init__(self, session):
        self.s = session
        self.latest: list = []
        self._said: set = set()

    def advise(self, mp=None, build=True) -> list:
        s = self.s
        ls, st = s.loopstats, s.state
        mp = mp or getattr(s.bot, "_lap_path", None)
        if not mp:
            return []
        key = s.bot.x.loop_key(mp)
        sm = ls.summary(key, last=10)
        if not sm or sm["laps"] < 3:
            return []
        out = []
        lvl = st.level or s.settings.char_level or sm.get("level") or 0
        # other loops at about this level
        best = None
        for k, o in ls.all_summaries():
            if k == key or o["laps"] < 3:
                continue
            if lvl and o.get("level") and abs(int(o["level"]) - int(lvl)) > 3:
                continue
            if best is None or o["exp_hr"] > best[1]["exp_hr"]:
                best = (k, o)
        if best and best[1]["exp_hr"] >= sm["exp_hr"] * 1.2:
            out.append(f"{best[1]['title']} has paid {best[1]['exp_hr'] / 1000:,.0f}k/hr at about your level vs "
                       f"{sm['exp_hr'] / 1000:,.0f}k/hr here — worth a switch")
        # this loop's trend
        laps = ((ls.data.get(key) or {}).get("by") or {}).get(ls.who(), [])
        if len(laps) >= 20:
            def rate(xs):
                return sum(x["exp"] for x in xs) / max(sum(x["secs"] for x in xs), 1) * 3600
            new, old = rate(laps[-10:]), rate(laps[-20:-10])
            if old and new < old * 0.75:
                out.append(f"This loop is paying {100 - 100 * new / old:.0f}% less than 10 laps ago "
                           f"({new / 1000:,.0f}k vs {old / 1000:,.0f}k/hr) — lairs emptying, company, or outgrown")
        if sm.get("empty_lairs") is not None and sm["empty_lairs"] >= 0.5:
            tips = []
            if not s.settings.lair_pace:
                tips.append("lair pacing")
            if not s.settings.rotate_on:
                tips.append("loop rotation")
            out.append(f"{sm['empty_lairs']:.0%} of lairs were empty when you got there — you lap faster than they refill"
                       + (f"; try {' or '.join(tips)}" if tips else ""))
        if sm.get("deaths"):
            out.append(f"{sm['deaths']} death{'s' if sm['deaths'] > 1 else ''} on this loop in the last 10 laps — "
                       "rest higher, or let the danger check stop the loop")
        # could a built loop around here do better?
        if build and mp.steps and mp.steps[0].room:
            try:
                cands = s.loopbuilder.build(mp.steps[0].room, max(20, len(mp.steps)))
            except Exception:
                cands = []
            if cands and cands[0]["exp_hr"] >= sm["exp_hr"] * 1.3:
                out.append(f"A loop built around here could do ~{cands[0]['exp_hr'] / 1000:,.0f}k/hr "
                           f"({cands[0]['steps']} steps, {len(cands[0]['lairs'])} lairs) — Paths → More → Build a loop")
        self.latest = out
        return out

    def lap_check(self, mp):
        """Called each lap; speaks every 10 laps, only new advice."""
        if self.s.bot.laps % 10:
            return
        for line in self.advise(mp):
            k = line.split(" — ")[0][:60]
            if k not in self._said:
                self._said.add(k)
                self.s.log("Advice: " + line)
