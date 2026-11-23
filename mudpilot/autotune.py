"""Auto-tune resting: try a few 'rest below / rest until' settings on the loop you're running and
keep whichever makes the most exp per hour.

Variants come from your current settings:
  current · rest less often (trigger 10 lower) · rest longer (until 10 higher) · both
Each runs for N minutes of actual looping (time stopped, walking to the loop or disconnected
doesn't count), in turn; with 2 rounds each runs twice (A B C D A B C D) and the two are added up.
Every trial starts from full HP and mana (the top-up isn't timed), and what a trial ends short of
full is charged to it as the resting time that would take (from the learned regen tick), so a
setting can't look good by leaving you drained for the next one.
Then the best one is kept, and you get the table (Health tab → Auto-tune resting…) and a phone note.

Safety: the HP trigger never goes below max(35%, hang-up % + 10, run % + 10). A death during the
test puts your original settings straight back and stops the test. If MudPilot closes mid-test,
your originals are restored the next time it starts.
"""
from __future__ import annotations

import json
import os
import time

from . import config

KEYS = ("rest_below_hp", "rest_until_hp", "rest_below_ma", "rest_until_ma")


class AutoTune:
    _off_since = 0.0
    _off_said = False
    def __init__(self, session):
        self.s = session
        self.active = False
        self.variants: list = []
        self.order: list = []          # variant index per trial
        self.trial = 0
        self.results: dict = {}        # variant index -> {"exp", "secs", "rests"}
        self._last = time.time()
        self._rests0 = 0
        self.on_change = lambda: None
        session.state.on_exp.append(self._on_exp)
        session.state.on_event.append(lambda k, d: k == "death" and self.active and self.abort("you died"))
        self._restore_if_interrupted()

    # ------------------------------------------------------------ setup
    def _floor_hp(self):
        cfg = self.s.settings
        return max(35, int(cfg.hangup_hp_pct or 0) + 10 if cfg.hangup_low_hp else 0, int(cfg.run_pct or 0) + 10)

    def make_variants(self) -> list:
        cfg = self.s.settings
        bh, uh, bm, um = (int(getattr(cfg, k) or 0) for k in KEYS)
        fl = self._floor_hp()
        mana = bm > 0

        def v(name, a, b, c, d):
            a = max(fl, min(a, 95))
            b = max(a + 5, min(100, b))
            if mana:
                c = max(10, min(c, 90))
                d = max(c + 5, min(100, d))
            else:
                c, d = bm, um
            return {"name": name, "rest_below_hp": a, "rest_until_hp": b, "rest_below_ma": c, "rest_until_ma": d}
        out = [v("current", bh, uh, bm, um),
               v("rest less often", bh - 10, uh, bm - 10, um),
               v("rest longer", bh, uh + 10, bm, um + 10),
               v("both", bh - 10, uh + 10, bm - 10, um + 10)]
        seen, uniq = set(), []
        for x in out:
            key = tuple(x[k] for k in KEYS)
            if key not in seen:
                seen.add(key)
                uniq.append(x)
        return uniq

    def _apply(self, v):
        cfg = self.s.settings
        for k in KEYS:
            setattr(cfg, k, v[k])
        cfg.save()
        self.s.on_settings_changed()

    # ------------------------------------------------------------ control
    def start(self, minutes=30, rounds=1):
        cfg, b = self.s.settings, self.s.bot
        if self.active:
            return "already running"
        if not (b.walking and b.loop and b.path):
            return "start a loop first — the test runs on the loop you're on"
        self.variants = self.make_variants()
        if len(self.variants) < 2:
            return "your settings leave nothing to try (already at the safe limits)"
        cfg.tune_baseline = {k: getattr(cfg, k) for k in KEYS}
        cfg.tune_mins, cfg.tune_rounds = (minutes if minutes < 1 else int(minutes)), int(rounds)
        cfg.save()
        self.order = list(range(len(self.variants))) * max(1, int(rounds))
        self.trial = 0
        self.results = {i: {"exp": 0, "secs": 0.0, "rests": 0} for i in range(len(self.variants))}
        self.loop_title = b.path.title
        self.active = True
        self._begin_trial()
        return f"testing {len(self.variants)} settings × {rounds}, {minutes} min each on {self.loop_title}"

    def _begin_trial(self):
        v = self.variants[self.order[self.trial]]
        self._apply(v)
        self._trial_secs = 0.0
        self._rests0 = self.s.stats.rests
        self._last = time.time()
        # every trial starts in the loop's first room, from full HP and mana — none of that is counted
        b = self.s.bot
        at_start = b.walking and b.path and b.idx == 0 and b.path.steps and self.s.state.room == b.path.steps[0].room
        self.prep, self._prep_since = True, time.time()
        self.phase = "topup" if at_start else "to_start"
        self.s.bot._rest_full = at_start
        self.s.log(f"Auto-tune {self.trial + 1}/{len(self.order)}: "
                   f"{'topping up' if at_start else 'back to the start of the loop, top up'} first, then '{v['name']}' — "
                   f"rest HP {v['rest_below_hp']}→"
                   f"{v['rest_until_hp']}%" + (f", MA {v['rest_below_ma']}→{v['rest_until_ma']}%"
                                               if v['rest_below_ma'] else ""))
        self.on_change()

    def abort(self, why="cancelled"):
        cfg = self.s.settings
        self.active = False
        self.prep = False
        self.s.bot._rest_full = False
        base = cfg.tune_baseline or {}
        if base:
            for k in KEYS:
                if k in base:
                    setattr(cfg, k, base[k])
        cfg.tune_baseline = {}
        cfg.save()
        self.s.on_settings_changed()
        self.s.log(f"Auto-tune stopped ({why}) — your original rest settings are back")
        if cfg.ntfy_on:
            self.s.notify.send("tune", f"Auto-tune stopped ({why}) — original rest settings restored", force=True)
        self.on_change()

    def _restore_if_interrupted(self):
        cfg = self.s.settings
        base = getattr(cfg, "tune_baseline", None) or {}
        if base:
            for k in KEYS:
                if k in base:
                    setattr(cfg, k, base[k])
            cfg.tune_baseline = {}
            cfg.save_quietly(self.s.log)

    # ------------------------------------------------------------ measuring
    def hunting(self) -> bool:
        b, s = self.s.bot, self.s
        return bool(s.telnet.connected and b.walking and b.loop and b.path and b.path.title == self.loop_title)

    def _on_exp(self, n):
        if self.active and self.hunting() and not getattr(self, "prep", False):
            self.results[self.order[self.trial]]["exp"] += n

    def tick(self):
        if not self.active:
            return
        now = time.time()
        dt = min(now - self._last, 5.0)
        self._last = now
        if not self.hunting():
            # the loop stopped and nothing's restarting it: say so once (phone too) instead of waiting all night
            if not self._off_since:
                self._off_since = now
            elif now - self._off_since > 600 and not self._off_said and not self.s.bot.walking:
                self._off_said = True
                why = (getattr(self.s.bot, "status", "") or "stopped")[:80]
                msg = (f"Auto-tune is paused: the loop stopped ({why}). It carries on when you Rego the loop.")
                self.s.log(msg)
                self.s.notify.send("stop", msg, force=bool(self.s.settings.ntfy_on))
            return
        self._off_since, self._off_said = 0.0, False
        st = self.s.state
        phase = getattr(self, "phase", "timing")
        if phase == "to_start":
            return                                    # walking on to the loop's first room (lap_end moves us on)
        if phase == "topup":
            full = st.max_hp and st.hp >= st.max_hp and (not st.max_ma or st.ma >= st.max_ma)
            if (full and not st.in_combat) or now - self._prep_since > 20 * 60:
                self.prep, self.phase = False, "timing"
                self.s.bot._rest_full = False
                self._rests0 = self.s.stats.rests
                self.s.log(f"Auto-tune: full, at the start of the loop — trial {self.trial + 1} timing starts now")
            return
        i = self.order[self.trial]
        self.results[i]["secs"] += dt
        self._trial_secs += dt
        if phase == "timing" and self._trial_secs >= float(self.s.settings.tune_mins or 30) * 60:
            self.phase = "finishing"                  # time's up: finish this lap (counted), then stop
            self.s.log("Auto-tune: time's up — finishing this lap, then the next setting")

    def lap_end(self):
        """The loop just came round to its first room (called by the bot at every lap end)."""
        if not self.active or not self.hunting():
            return
        phase = getattr(self, "phase", "timing")
        if phase == "to_start":
            self.phase = "topup"
            self._prep_since = time.time()
            self.s.bot._rest_full = True
            self.s.log("Auto-tune: at the start of the loop — topping up to full")
        elif phase == "finishing":
            self._end_trial()

    def _end_trial(self):
        st = self.s.state
        i = self.order[self.trial]
        owed = self.owed_secs()
        self.results[i]["secs"] += owed                     # what it would take to get back to full
        self.results[i]["owed"] = self.results[i].get("owed", 0) + owed
        if owed:
            self.s.log(f"Auto-tune: trial ended {100 - st.hp_pct():.0f}% HP / "
                       f"{(100 - st.ma_pct()) if st.max_ma else 0:.0f}% mana short of full — "
                       f"charged {owed:.0f} s of resting")
        self.results[i]["rests"] += max(0, self.s.stats.rests - self._rests0)
        self.trial += 1
        if self.trial >= len(self.order):
            self._finish()
        else:
            self._begin_trial()

    def owed_secs(self) -> float:
        """Resting time to get back to full from where the trial ended (from the learned regen tick)."""
        st, rc = self.s.state, self.s.bot.regen
        if not st.max_hp:
            return 0.0
        miss_hp = max(0.0, 100 - st.hp_pct())
        miss_ma = max(0.0, 100 - st.ma_pct()) if st.max_ma else 0.0
        if rc.learned:
            ticks = max(miss_hp / rc.gain("hp") if rc.gain("hp") else 0, miss_ma / rc.gain("ma") if rc.gain("ma") else 0)
            return ticks * rc.period
        return max(miss_hp, miss_ma) * 3.0           # not learned yet: ~3 s per % (a typical rest)

    def rate(self, i) -> float:
        r = self.results.get(i) or {}
        return r.get("exp", 0) / max(r.get("secs", 0), 1) * 3600

    def progress(self) -> str:
        if not self.active:
            return ""
        mins = int(self.s.settings.tune_mins or 30)
        phase = getattr(self, "phase", "timing")
        if phase == "to_start":
            return f"Trial {self.trial + 1}/{len(self.order)}: walking on to the start of the loop (not timed)"
        if phase == "topup":
            return f"Trial {self.trial + 1}/{len(self.order)}: topping up to full at the start of the loop (not timed)"
        if phase == "finishing":
            return (f"Trial {self.trial + 1}/{len(self.order)}: time's up — finishing this lap "
                    f"({self._trial_secs / 60:.0f} min so far)")
        return (f"Trial {self.trial + 1}/{len(self.order)} '{self.variants[self.order[self.trial]]['name']}': "
                f"{self._trial_secs / 60:.0f}/{mins} min" + ("" if self.hunting() else " (paused — not on the loop)"))

    def _finish(self):
        cfg = self.s.settings
        self.active = False
        self.prep = False
        self.s.bot._rest_full = False
        best = max(range(len(self.variants)), key=self.rate)
        v = self.variants[best]
        self._apply(v)
        cfg.tune_baseline = {}
        cfg.save()
        table = "; ".join(f"{x['name']} {self.rate(i) / 1000:,.0f}k/hr" for i, x in enumerate(self.variants))
        msg = (f"Auto-tune done on {self.loop_title}: keeping '{v['name']}' (rest HP {v['rest_below_hp']}→"
               f"{v['rest_until_hp']}%" + (f", MA {v['rest_below_ma']}→{v['rest_until_ma']}%" if v['rest_below_ma'] else "")
               + f"). {table}")
        self.s.log(msg)
        if cfg.ntfy_on:
            self.s.notify.send("tune", msg, force=True)
        self._save_results(best)
        self.on_change()

    def _save_results(self, best):
        p = os.path.join(config.board_dir(self.s.settings.board), "autotune.json")
        try:
            with open(p, encoding="utf-8") as f:
                hist = json.load(f)
        except (OSError, ValueError):
            hist = []
        hist.append({"t": round(time.time()), "loop": self.loop_title, "who": self.s.settings.my_name,
                     "best": best, "variants": [{**v, "exp_hr": round(self.rate(i)),
                                                 "mins": round(self.results[i]["secs"] / 60, 1),
                                                 "rests": self.results[i]["rests"]}
                                                for i, v in enumerate(self.variants)]})
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(hist[-50:], f, indent=1)
        except OSError:
            pass

    def last_results(self):
        p = os.path.join(config.board_dir(self.s.settings.board), "autotune.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)[-1]
        except (OSError, ValueError, IndexError):
            return None
