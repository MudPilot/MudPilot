"""Daily history: exp/hr by day and by loop, kept for months, so you can see whether a change
(new settings, a different loop, a new build) actually helped.

Per board and character in data\\boards\\<board>\\history.json:
  {char: {"2026-10-26": {exp, kills, deaths, rests, drops, on (secs connected), hunt (secs on a loop),
                         rest (secs resting), lag_sum, lag_n, loops: {title: {exp, secs}}}}}
Saved every minute (and when MudPilot closes).
"""
from __future__ import annotations

import json
import os
import time

from . import config

KEEP_DAYS = 400


def day_key(t=None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t or time.time()))


class History:
    def __init__(self, session):
        self.s = session
        self.data: dict = {}
        self._for = None
        self._last = time.time()
        self._saved = time.time()
        self._lag_t = 0.0
        self._rests = 0
        session.state.on_exp.append(self.on_exp)
        session.state.on_event.append(lambda k, d: k == "death" and self._add("deaths", 1))

    # ------------------------------------------------------------ storage
    def path(self):
        return os.path.join(config.board_dir(self.s.settings.board), "history.json")

    def _load(self):
        if self._for == self.s.settings.board:
            return
        if self._for is not None:
            self.save()
        self._for = self.s.settings.board
        try:
            with open(self.path(), encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        if self._for is None:
            return
        self._saved = time.time()
        try:
            os.makedirs(os.path.dirname(self.path()), exist_ok=True)
            tmp = self.path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path())
        except OSError:
            pass

    def who(self):
        return (self.s.settings.my_name or self.s.settings.profile or "?").lower()

    def today(self, t=None) -> dict:
        self._load()
        days = self.data.setdefault(self.who(), {})
        k = day_key(t)
        if k not in days:
            days[k] = {"exp": 0, "kills": 0, "deaths": 0, "rests": 0, "drops": 0, "on": 0.0, "hunt": 0.0,
                       "rest": 0.0, "lag_sum": 0.0, "lag_n": 0, "loops": {}}
            cutoff = day_key(time.time() - KEEP_DAYS * 86400)
            for old in [d for d in days if d < cutoff]:
                del days[old]
        return days[k]

    def _add(self, key, n):
        d = self.today()
        d[key] = d.get(key, 0) + n

    def _loop_title(self):
        b = self.s.bot
        if b.walking and b.loop and b.path and not b.path.title.startswith("Go to "):
            return b.path.title
        return None

    # ------------------------------------------------------------ recording
    def on_exp(self, n):
        d = self.today()
        d["exp"] += n
        d["kills"] += 1
        t = self._loop_title() or getattr(getattr(self.s.bot, "_lap_path", None), "title", None)
        if t:
            lp = d["loops"].setdefault(t, {"exp": 0, "secs": 0.0})
            lp["exp"] += n

    def note_drop(self):
        self._add("drops", 1)

    def tick(self):
        now = time.time()
        dt = min(now - self._last, 5.0)
        self._last = now
        s = self.s
        if s.telnet.connected and dt > 0:
            d = self.today(now)
            d["on"] += dt
            st = s.state
            if st.resting:
                d["rest"] += dt
            t = self._loop_title()
            if t:
                d["hunt"] += dt
                lp = d["loops"].setdefault(t, {"exp": 0, "secs": 0.0})
                lp["secs"] += dt
            for t_, lag in reversed(st.lag_samples):
                if t_ <= self._lag_t:
                    break
                d["lag_sum"] += lag
                d["lag_n"] += 1
            if st.lag_samples:
                self._lag_t = max(self._lag_t, st.lag_samples[-1][0])
            if s.stats.rests > self._rests:
                d["rests"] += s.stats.rests - self._rests
            self._rests = s.stats.rests
        else:
            self._rests = s.stats.rests
        if now - self._saved > 60:
            self.save()

    # ------------------------------------------------------------ reading
    def days(self, who=None) -> list:
        """[(date, day dict)] newest first."""
        self._load()
        return sorted((self.data.get(who or self.who()) or {}).items(), reverse=True)
