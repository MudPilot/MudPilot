"""Overnight helpers: the stuck watchdog, the morning summary and boss-due alerts.

Watchdog (off by default): if a loop/path has made no progress for a while (no new room, no exp,
not fighting, not resting up), or it stopped itself (lost, a locked door, couldn't find the path)
and nobody has touched it, it tries to get going again by itself: look, then Rego back onto the
loop. After a few tries in a short time it gives up, stays stopped and tells your phone.
It never restarts after you stop it, a hang-up, a death or a disconnect.

Morning summary (off by default): one phone message at the time you pick with how the night went.
"""
from __future__ import annotations

import time

from .bosses import fmt_dur

# stops it may undo by itself — getting lost or blocked; never your stop, a hang-up, a death,
# a missing key, or a board/character switch
RESTARTABLE = ("Stopped: lost", "Stopped: couldn't find the path", "Stopped: the door", "Stopped: watchdog unsticking",
               "Stopped: knocked off the path")


class Watchdog:
    def __init__(self, session):
        self.s = session
        self.reset_progress()
        self.tries: list = []               # times we nudged it
        self.gave_up = False
        # cumulative counters for the summary (the session counters reset when a loop starts)
        self.tot_exp = 0
        self.tot_kills = 0
        self.tot_deaths = 0
        self._was_dead = False
        self.drops = 0
        self.since = time.time()
        self._summary_day = None
        self._boss_warned: dict = {}
        session.state.on_exp.append(self._on_exp)

    def _on_exp(self, n):
        self.tot_exp += n
        self.tot_kills += 1
        self._progress_t = time.time()

    def reset_progress(self):
        self._progress_t = time.time()
        self._mark = None

    # ------------------------------------------------------------ stuck watchdog
    def _moving(self) -> bool:
        """Something is happening: a new room, a fight, or a rest that's actually filling us up."""
        st = self.s.state
        mark = (st.room, st.steps_walked, st.in_combat, st.hp if st.resting else None,
                st.ma if st.resting else None)
        if mark != self._mark:
            self._mark = mark
            return True
        return False

    def tick(self):
        s, cfg, bot = self.s, self.s.settings, self.s.bot
        now = time.time()
        st = s.state
        if st.dead and not self._was_dead:
            self.tot_deaths += 1
        self._was_dead = bool(st.dead)
        self._summary_tick(now)
        self._boss_tick(now)
        if not cfg.watchdog_on or not s.telnet.connected or not s._entered:
            self.reset_progress()
            return
        if self._moving() or st.in_combat:
            self._progress_t = now
        lim = max(1, int(cfg.watchdog_mins or 5)) * 60
        self.tries = [t for t in self.tries if now - t < 30 * 60]
        if bot.walking:
            self.gave_up = False
            if s.remote.holding() or bot.x.waiting_on or getattr(bot, "_boss_hold", None):
                self._progress_t = now           # held on purpose (@wait, party, boss room) — not stuck
                return
            if now - self._progress_t >= lim:
                self._nudge(f"no progress for {lim // 60} min on {bot.path.title if bot.path else 'the path'}")
            return
        # stopped by itself with something to go back to?
        why = bot.status or ""
        r = getattr(bot, "resume", None)
        if r and why.startswith(RESTARTABLE) and not self.gave_up:
            if now - self._progress_t >= min(lim, 120):
                self._nudge(f"it stopped ({why.replace('Stopped: ', '')})")
        else:
            self._progress_t = now

    def _nudge(self, why):
        s, bot = self.s, self.s.bot
        now = time.time()
        self._progress_t = now
        if len(self.tries) >= 3:
            self.gave_up = True
            if bot.walking:
                bot.stop(f"Stopped: watchdog gave up ({why})")
            msg = f"Stuck: {why}. Tried 3 times in 30 min — stopped and waiting for you."
            s.log(msg)
            s.notify.send("stuck", msg)
            s.on_alert("Stuck — watchdog gave up")
            return
        self.tries.append(now)
        s.log(f"Watchdog: {why} — trying to get going again (try {len(self.tries)}/3)")
        s.notify.send("stuck", f"Stuck: {why} — trying to get going again")
        if bot.walking:
            bot.stop("Stopped: watchdog unsticking")
        s.send("")                               # fresh look so the room is known
        s.bot._watchdog_rego_at = now + 2

    def after_tick(self):
        """Rego a moment after the look went out."""
        bot = self.s.bot
        at = getattr(bot, "_watchdog_rego_at", 0)
        if at and time.time() >= at:
            bot._watchdog_rego_at = 0
            if not bot.walking and bot.rego():
                bot.set_mode("auto")

    # ------------------------------------------------------------ morning summary
    def summary_text(self) -> str:
        s = self.s
        hrs = max((time.time() - self.since) / 3600, 1e-6)
        rests = [r for r in s.stats.rest_log if r["t"] >= self.since]
        bosses = []
        for rec in s.bosses.data.values():
            for k in rec.get("kills") or []:
                if k.get("t", 0) >= self.since:
                    bosses.append(rec.get("name", "?"))
        bot = s.bot
        lines = [f"Since {time.strftime('%I:%M %p', time.localtime(self.since)).lstrip('0')} "
                 f"({fmt_dur(time.time() - self.since)}): {self.tot_exp:,} exp, {self.tot_exp / hrs / 1000:,.0f}k/hr",
                 f"{self.tot_kills} kills · {self.tot_deaths} deaths · {len(rests)} rests"
                 + (f" ({sum(r['secs'] for r in rests) / 60:.0f} min resting)" if rests else "")
                 + (f" · line dropped {self.drops}×" if self.drops else ""),
                 ("Bosses: " + ", ".join(sorted(set(bosses)))) if bosses else "",
                 ("Advice: " + s.advisor.latest[0]) if getattr(s, "advisor", None) and s.advisor.latest else "",
                 f"Now: {'connected' if s.telnet.connected else 'NOT connected'} — {bot.status}"
                 + (f" (lap {bot.laps})" if bot.walking and bot.loop else "")]
        return "\n".join(l for l in lines if l)

    def _summary_tick(self, now):
        cfg = self.s.settings
        if not cfg.summary_on:
            return
        try:
            hh, mm = (int(x) for x in (cfg.summary_time or "07:00").split(":")[:2])
        except ValueError:
            return
        lt = time.localtime(now)
        day = time.strftime("%Y%m%d", lt)
        if self._summary_day == day or (lt.tm_hour, lt.tm_min) < (hh, mm):
            return
        if (lt.tm_hour * 60 + lt.tm_min) - (hh * 60 + mm) > 120:
            self._summary_day = day           # opened MudPilot hours later: not a morning summary
            return
        self._summary_day = day
        txt = self.summary_text()
        self.s.log("Morning summary: " + txt.replace("\n", " · "))
        if cfg.ntfy_on:
            self.s.notify.send("summary", txt, force=True)     # its own switch is the one that counts
        self.since, self.tot_exp, self.tot_kills, self.tot_deaths, self.drops = now, 0, 0, 0, 0

    # ------------------------------------------------------------ boss due alerts
    def _boss_tick(self, now):
        cfg, b = self.s.settings, self.s.bosses
        mins = int(cfg.boss_warn_mins or 0)
        if "boss" not in (cfg.ntfy_kinds or []) or not cfg.ntfy_on:
            return
        for num, r in b.data.items():
            mon = self.s.world.monsters.get(int(num))
            dead = r.get("dead_since")
            if not mon or not dead or not b.killable(mon):
                continue
            due = dead + mon.get("regen_h", 0) * 3600
            key = (num, dead)
            if mins and 0 < due - now <= mins * 60 and self._boss_warned.get(key) != "soon":
                self._boss_warned[key] = "soon"
                self.s.notify.send("boss", f"{mon['name']} due back in {max(1, round((due - now) / 60))} min")
            elif 0 <= now - due < 600 and self._boss_warned.get(key) != "up":
                self._boss_warned[key] = "up"
                self.s.notify.send("boss", f"{mon['name']} should be back up now")
