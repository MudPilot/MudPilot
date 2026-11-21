"""Session statistics: exp over time (for the exp chart), time split between fighting,
resting, walking and idle, kills and exp per monster, cash, deaths."""
from __future__ import annotations

import re
import time

REASON_KEY = re.compile(r"\s*\(.*\)$")      # "mana below 40% (31%)" → "mana below 40%"
ATTACK_RE = re.compile(r"^(?:a|at|att|attack|aa|bs|backstab)\s+(\S+)", re.I)


class SessionStats:
    SAMPLE_SECS = 20

    def __init__(self, session):
        self.s = session
        self.reset()
        session.state.on_exp.append(self.on_exp)

    def reset(self):
        self.start = time.time()
        self.samples = [(self.start, 0, 0)]      # (t, cumulative exp, kills)
        self.time_in = {"fighting": 0.0, "resting": 0.0, "walking": 0.0, "idle": 0.0}
        self.mobs: dict = {}                       # name -> {"kills", "exp"}
        self.last_target = ""
        self._last_tick = time.time()
        self._last_sample = 0.0
        self.rests = 0
        self._was_resting = False
        self.rest_log: list = []         # finished rests: why it sat down, how long, what it gained, why it got up
        self._rest = None                # the rest in progress
        self._rest_gap = None            # (t, snapshot) — got up; finalised unless it sits right back down

    def note_command(self, cmd: str):
        m = ATTACK_RE.match(cmd.strip())
        if m:
            self.last_target = m.group(1).lower()
        else:
            parts = cmd.strip().split()
            if len(parts) == 2 and self.s.spellbook.find(parts[0]):
                self.last_target = parts[1].lower()

    def on_exp(self, n):
        st = self.s.state
        name = "unknown"
        mons = [rec["name"] if rec else shown for shown, rec in (st.view.monsters if st.view else [])]
        if getattr(st, "last_kill_name", None):
            name = st.last_kill_name                  # its own death line said which one died
        elif self.last_target:
            hit = [m for m in mons if self.last_target in m.lower()]
            if hit:
                name = hit[0]
            else:
                name = self.last_target
        elif mons:
            name = mons[0]
        d = self.mobs.setdefault(name, {"kills": 0, "exp": 0})
        d["kills"] += 1
        d["exp"] += n
        self.sample(force=True)

    def sample(self, force=False):
        now = time.time()
        if force or now - self._last_sample >= self.SAMPLE_SECS:
            self._last_sample = now
            st = self.s.state
            self.samples.append((now, st.exp_gained, st.kills))
            if len(self.samples) > 5000:
                self.samples = self.samples[::2]

    def tick(self):
        now = time.time()
        dt = min(now - self._last_tick, 5)
        self._last_tick = now
        st, bot = self.s.state, self.s.bot
        if not self.s.telnet.connected:
            return
        if st.in_combat:
            k = "fighting"
        elif st.resting:
            k = "resting"
        elif bot.walking:
            k = "walking"
        else:
            k = "idle"
        self.time_in[k] += dt
        self._rest_track(now)
        if now - getattr(self, "_lag_t", 0) > 30:
            self._lag_t = now
            self.lag_check()
        self._was_resting = st.resting
        self.sample()

    # ------------------------------------------------------------ rest diagnosis
    REJOIN = 4.0        # up and back down within this = the same rest (an interruption), not a new one

    def _snap(self):
        st = self.s.state
        return {"hp": st.hp_pct() if st.max_hp else 100, "ma": st.ma_pct() if st.max_ma else 100}

    def _rest_track(self, now):
        st, bot = self.s.state, self.s.bot
        if st.resting and not self._was_resting:
            gap = self._rest_gap
            if self._rest and gap and now - gap[0] <= self.REJOIN:
                self._rest["breaks"] += 1          # sat straight back down: same rest
                self._rest_gap = None
                return
            if self._rest and gap:
                self._rest_finish(*gap)
            why = getattr(bot, "_rest_reason", None) or "you (or a trigger) sat down"
            bot._rest_reason = None
            self._rest = {"t": now, "why": why, "start": self._snap(), "breaks": 0,
                          "kind": "meditate" if st.meditating else "rest",
                          "rgen": bool(getattr(getattr(bot, "smart", None), "rgen_active", lambda: False)()),
                          "room": list(st.room) if st.room else None}
            self.rests += 1
        elif not st.resting and self._was_resting and self._rest:
            if st.in_combat:
                end = "a fight broke it up"
            else:
                end = getattr(bot, "_rest_end", None) or "got up"
            bot._rest_end = None
            self._rest_gap = (now, self._snap(), end)
        elif self._rest_gap and not st.resting and now - self._rest_gap[0] > self.REJOIN:
            self._rest_finish(*self._rest_gap)

    def _rest_finish(self, t_end, snap, end):
        r, self._rest, self._rest_gap = self._rest, None, None
        if not r:
            return
        r.update({"secs": round(t_end - r["t"]), "end": snap, "ended": end})
        self.rest_log.append(r)
        sm = getattr(self.s.bot, "smart", None)
        if sm is not None:
            st = self.s.state
            sm.learn_rest(r, st.max_hp, st.max_ma)        # smart resting's rates (smartrest.py)
        del self.rest_log[:-300]
        gained = []
        if snap["hp"] != r["start"]["hp"]:
            gained.append(f"HP {r['start']['hp']:.0f}%→{snap['hp']:.0f}%")
        if snap["ma"] != r["start"]["ma"]:
            gained.append(f"MA {r['start']['ma']:.0f}%→{snap['ma']:.0f}%")
        self.s.log(f"Rest {r['secs']} s ({r['kind']}{', ' + ', '.join(gained) if gained else ''}) — "
                   f"why: {r['why']}; ended: {end}" + (f"; interrupted {r['breaks']}×" if r["breaks"] else ""))

    def rest_summary(self) -> list:
        """[(reason, count, avg secs, total secs, interrupted)] — biggest time sink first."""
        by = {}
        for r in self.rest_log:
            key = REASON_KEY.sub("", r["why"]).strip()
            d = by.setdefault(key, [0, 0, 0])
            d[0] += 1
            d[1] += r["secs"]
            d[2] += 1 if (r["breaks"] or r["ended"] == "a fight broke it up") else 0
        return sorted(((k, n, tot / n, tot, br) for k, (n, tot, br) in by.items()), key=lambda x: -x[3])

    # ------------------------------------------------------------ lag meter
    def lag_stats(self, window=600):
        """Board response time over the last `window` s: (avg, 90th percentile, worst, samples)."""
        now = time.time()
        xs = sorted(l for t, l in self.s.state.lag_samples if now - t <= window)
        if not xs:
            return None
        return (sum(xs) / len(xs), xs[min(len(xs) - 1, int(len(xs) * 0.9))], xs[-1], len(xs))

    def lag_check(self):
        """Slow board for 10 minutes straight → say so (once an hour): it costs rounds and steps."""
        ls = self.lag_stats(600)
        now = time.time()
        if ls and ls[3] >= 40 and ls[0] >= 1.5 and now - getattr(self, "_lag_warned", 0) > 3600:
            self._lag_warned = now
            self.s.log(f"Lag: the board has averaged {ls[0]:.1f} s to answer for 10 min (worst {ls[2]:.1f} s) — "
                       "that slows every step and fight")

    # ------------------------------------------------------------ derived
    def elapsed(self) -> float:
        return max(time.time() - self.start, 1)

    def exp_rate(self, window: float | None = None) -> float:
        """Exp per hour over the whole session, or over the last `window` seconds."""
        if not self.samples:
            return 0.0
        now = time.time()
        if window is None:
            return self.s.state.exp_gained / (self.elapsed() / 3600)
        base = next((smp for smp in self.samples if smp[0] >= now - window), self.samples[0])
        span = max(now - base[0], 60)
        return (self.s.state.exp_gained - base[1]) / (span / 3600)

    def time_to_level(self) -> float | None:
        st = self.s.state
        rate = self.exp_rate(1800) or self.exp_rate()
        if not st.exp_needed or rate <= 0:
            return None
        need = max(0, st.exp_needed - st._exp_since_line)
        return need / rate * 3600
