"""The server tick (pMUD's Enter on Tick and Cadence commands).

MajorMUD runs everything — combat rounds, regen — off one clock that goes off every ~5 seconds. We learn
where it falls from two things we see anyway: a combat round going off (CombatClock) and your HP/mana
going up by themselves while you're out of combat (a regen tick). With that:

* Enter on tick: entering the realm ~0.3 s after a tick gives you a whole round before anything acts.
* Commands timed to the tick: "0.3 resting look" sends 'look' 0.3 s after every tick while resting.
  Modes: combat, resting, idle, any — and pvp (only while fighting a player).
"""
from __future__ import annotations

import time

MODES = ("any", "combat", "resting", "idle", "pvp")


def parse_cmds(lines) -> list:
    """['0.3 resting look', '1 combat bs'] → [(0.3, 'resting', 'look'), …] (bad lines skipped)."""
    out = []
    for ln in lines or []:
        parts = str(ln).strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            off = float(parts[0])
        except ValueError:
            continue
        mode = parts[1].lower()
        if mode not in MODES or not (0 <= off < 5) or not parts[2].strip():
            continue
        out.append((off, mode, parts[2].strip()))
    return out


class ServerTick:
    def __init__(self, session):
        self.s = session
        self.anchor = 0.0             # a moment a tick went off
        self._hp = None
        self._sent: dict = {}         # command line -> tick index it last went out on
        self._enter_at = 0.0

    @property
    def period(self) -> float:
        c = getattr(self.s, "clock", None)
        return float(c.period) if c is not None and getattr(c, "learned", False) else 5.0

    def note(self, t: float):
        self.anchor = t

    def fresh(self, now=None) -> bool:
        now = now or time.time()
        return bool(self.anchor) and now - self.anchor < 15 * 60

    def phase_now(self, now=None):
        """(index of the tick we're in, seconds since it went off) or None."""
        now = now or time.time()
        c = getattr(self.s, "clock", None)
        if c is not None and c.last_round and c.last_round > self.anchor:
            self.anchor = c.last_round          # a combat round is the best mark there is
        if not self.fresh(now):
            return None
        p = self.period
        k, since = divmod(now - self.anchor, p)
        return int(k), since

    def delay_to(self, offset: float, now=None) -> float | None:
        """Seconds from now until `offset` seconds past the next tick (None = tick not known)."""
        ph = self.phase_now(now)
        if ph is None:
            return None
        _k, since = ph
        d = offset - since
        return d if d > 0.05 else d + self.period

    def on_prompt(self):
        """Every HP prompt: HP or mana up by itself, out of combat = a regen tick."""
        st = self.s.state
        now = time.time()
        cur = (st.hp, st.ma)
        prev, self._hp = self._hp, cur
        if prev is None or st.in_combat:
            return
        if (cur[0] or 0) > (prev[0] or 0) or (cur[1] or 0) > (prev[1] or 0):
            b = self.s.bot
            if now - getattr(b, "_last_spell_at", 0) > 2:     # not one of our heals
                self.note(now)

    def tick(self):
        """Send the commands timed to the tick (Other tab)."""
        cfg = self.s.settings
        cmds = parse_cmds(getattr(cfg, "tick_cmds", None))
        if not cmds or not self.s.telnet.connected or not getattr(self.s, "_entered", False):
            return
        ph = self.phase_now()
        if ph is None:
            return
        k, since = ph
        st, b = self.s.state, self.s.bot
        pvp = bool(getattr(b.x, "pvp_target", None))
        now_mode = {"combat": st.in_combat and not pvp, "resting": bool(st.resting) and not st.in_combat,
                    "idle": not st.in_combat and not st.resting and not b.walking, "any": True, "pvp": pvp}
        for off, mode, cmd in cmds:
            key = f"{off} {mode} {cmd}"
            if not now_mode.get(mode):
                continue
            # once per tick: the anchor moves with every round / regen we see, so go by time since the last send
            if off <= since < off + 1.0 and time.time() - self._sent.get(key, 0) > 0.6 * self.period:
                self._sent[key] = time.time()
                self.s.send(cmd, from_bot=True)

    # ------------------------------------------------------------ entering the realm
    def enter_delay(self) -> float | None:
        if not getattr(self.s.settings, "enter_on_tick", False):
            return None
        return self.delay_to(0.3)
