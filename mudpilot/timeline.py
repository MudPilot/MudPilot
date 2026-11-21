"""Session timeline and death replay.

Timeline: second by second, what the bot was doing — fighting, resting, walking, waiting on
someone, idle or offline — plus events (deaths, dropped lines, hang-ups, level-ups, boss kills),
and a time-stamped copy of the screen (last ~30,000 lines) so any moment can be looked at again.
Window → Timeline.

Death replay: when you die, the last 60 s are saved to data\\deaths\\: your HP over time, every
hit you took (who, how much), what was sent, the screen — and a short read of what went wrong
with what might have saved it. Window → Deaths.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque

from . import config

KEEP_SECS = 48 * 3600
# to the end of the line, not the end of the text: a recording has more lines after it, so the raw
# "Recover Password:    …\r\n" used to stay in the trace files
SECRET_RE = re.compile(r"((?:recover|suicide|reroll)\s+password\s*:\s*)(\S[^\r\n]*)|(\bpassword\s*:\s*)(\S[^\r\n]*)",
                       re.I)


def scrub(text: str) -> str:
    """Never keep a password the game prints (e.g. 'pro' shows 'Recover Password: …')."""
    return SECRET_RE.sub(lambda m: (m.group(1) or m.group(3)) + "(hidden)", text or "")
HIT_RE = re.compile(r"^(?:The |An? )?(.+?) .*?\byou\b.*? for (\d+) damage", re.I)
HEAL_WORDS = re.compile(r"\b(?:heal|cure|mend|regenerat)", re.I)


class Timeline:
    def __init__(self, session):
        self.s = session
        self.segs: list = []                  # [start, end, kind]
        self.events: list = []                # (t, kind, text)
        self.screen: deque = deque(maxlen=30000)
        self.hp: deque = deque(maxlen=4000)   # (t, hp, max_hp, ma, max_ma)
        self.sent: deque = deque(maxlen=400)  # (t, cmd)
        self._last_t = 0.0
        session.state.on_event.append(self._on_state_event)

    # ------------------------------------------------------------ recording
    def kind_now(self) -> str:
        s = self.s
        st, b = s.state, s.bot
        if not s.telnet.connected:
            return "offline"
        if st.in_combat:
            return "fighting"
        if st.resting:
            return "resting"
        if s.remote.holding() or b.x.waiting_on or getattr(b, "_pace_until", 0) > time.time():
            return "waiting"
        if b.walking:
            return "walking"
        return "idle"

    def tick(self):
        now = time.time()
        if now - self._last_t < 1:
            return
        self._last_t = now
        k = self.kind_now()
        if self.segs and self.segs[-1][2] == k and now - self.segs[-1][1] < 5:
            self.segs[-1][1] = now
        else:
            self.segs.append([now, now, k])
        while self.segs and now - self.segs[0][1] > KEEP_SECS:
            self.segs.pop(0)
        st = self.s.state
        if st.max_hp and (not self.hp or self.hp[-1][1] != st.hp or self.hp[-1][3] != st.ma):
            self.hp.append((now, st.hp, st.max_hp, st.ma, st.max_ma))

    def line(self, text):
        if text.strip():
            self.screen.append((time.time(), scrub(text)))
        st = self.s.state
        if st.max_hp and (not self.hp or self.hp[-1][1] != st.hp):
            self.hp.append((time.time(), st.hp, st.max_hp, st.ma, st.max_ma))
        if re.search(r"you are now level|you have gained a level", text, re.I):
            self.event("level", text.strip())

    def note_sent(self, cmd):
        self.sent.append((time.time(), cmd))

    def event(self, kind, text):
        self.events.append((time.time(), kind, text))
        del self.events[:-2000]

    def _on_state_event(self, kind, data):
        if kind == "death":
            self.event("death", "died")
            try:
                self.death_replay()
            except Exception as ex:
                self.s.log(f"Death replay not saved: {ex}")

    def screen_around(self, t, before=60, after=60) -> list:
        return [(tt, x) for tt, x in self.screen if t - before <= tt <= t + after]

    # ------------------------------------------------------------ death replay
    def death_replay(self, now=None) -> dict:
        s, cfg = self.s, self.s.settings
        now = now or time.time()
        t0 = now - 60
        lines = [(t, x) for t, x in self.screen if t >= t0]
        hp = sorted(h for h in self.hp if h[0] >= t0)
        hits = []
        for t, x in lines:
            m = HIT_RE.match(x.strip())
            if m and "you hit" not in x.lower() and not x.lower().startswith("you "):
                hits.append((t, m.group(1).strip(), int(m.group(2))))
        by = {}
        for _t, who, n in hits:
            by[who] = by.get(who, 0) + n
        period = getattr(s.clock, "period", 5.0) or 5.0
        rounds = {}
        for t, _w, n in hits:
            rounds[int(t / period)] = rounds.get(int(t / period), 0) + n
        worst_round = max(rounds.values()) if rounds else 0
        max_hp = (hp[-1][2] if hp else s.state.max_hp) or 1
        fight_t = next((t for t, x in lines if "combat engaged" in x.lower()), None)
        hp_start = next((h[1] for h in hp if fight_t and h[0] >= fight_t), hp[0][1] if hp else None)
        sent = [(t, c) for t, c in self.sent if t >= t0]
        heals = [c for _t, c in sent if (cfg.heal_cmd and c.startswith(cfg.heal_cmd)) or
                 (cfg.major_heal_cmd and c.startswith(cfg.major_heal_cmd))]
        low_seen = min((h[1] for h in hp), default=None)
        tips = []
        if hp_start is not None and hp_start / max_hp < 0.7:
            tips.append(f"The fight started at {100 * hp_start / max_hp:.0f}% HP — rest higher before lairs "
                        "(or keep the danger check on)")
        if worst_round and worst_round > 0.35 * max_hp:
            tips.append(f"One round did {worst_round} damage ({100 * worst_round / max_hp:.0f}% of your HP) — "
                        "that spawn is too much at this HP/AC")
        if (cfg.heal_cmd or cfg.major_heal_cmd) and not heals and low_seen is not None \
                and low_seen / max_hp * 100 < cfg.heal_pct:
            tips.append("Your heal never went out even though HP was under the heal line — is Heal switched on?")
        if not cfg.run_pct and hp_start and low_seen is not None and len(hp) >= 3:
            tips.append("Run is off (0%). Running at ~25% might have got you out")
        if not tips:
            tips.append("Nothing obvious — a bad run of hits. The danger check learns from this lair now.")
        rec = {"t": round(now), "who": cfg.my_name, "room": list(getattr(s.bot, "_last_room", None) or []),
               "max_hp": max_hp, "hp": [[round(h[0] - now, 1), h[1]] for h in hp],
               "hits": [[round(t - now, 1), w, n] for t, w, n in hits], "by": by, "worst_round": worst_round,
               "hp_start": hp_start, "heals": len(heals),
               "sent": [[round(t - now, 1), c] for t, c in sent if c.strip() and not c.startswith("/")][-60:],
               "lines": [[round(t - now, 1), x] for t, x in lines][-300:], "tips": tips}
        d = os.path.join(config.DATA_DIR, "deaths")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("death-%Y%m%d-%H%M%S.json", time.localtime(now))), "w",
                  encoding="utf-8") as f:
            json.dump(rec, f)
        files = sorted(fn for fn in os.listdir(d) if fn.startswith("death-"))
        for fn in files[:-30]:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass
        s.log("Death replay saved (Window → Deaths): " + " · ".join(tips))
        return rec


def load_deaths() -> list:
    d = os.path.join(config.DATA_DIR, "deaths")
    out = []
    try:
        for fn in sorted(os.listdir(d), reverse=True):
            if fn.startswith("death-") and fn.endswith(".json"):
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
    except (OSError, ValueError):
        pass
    return out
