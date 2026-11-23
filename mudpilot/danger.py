"""Danger check: before walking into a lair, how much could a full spawn hurt you?

For each lair MME lists the monsters that spawn there and how many at once ("Max 3").
Worst likely case = that many of the hardest hitter on the list. MME's monster attack simulator
gives its average damage per round against your AC/DR; your best spell (or melee) gives how
many rounds the fight takes. Expected damage ≈ dmg/round × count × rounds × ½ (they die one by
one), split across the party's front rank. If that wouldn't leave you above your safe floor,
the loop rests to enough HP first — or, if even full HP isn't enough, tells you (and can stop).

Rough by design: it's a guard rail, not a fight simulator. Results are cached per lair and AC.
"""
from __future__ import annotations

import math
import re

LAIR_RE = re.compile(r"\(Max (\d+)\):\s*([\d,]+)")


def lair_spawn(world, room) -> tuple[int, list]:
    """(max at once, [monster records]) for a lair room, or (0, [])."""
    r = world.room(room) if not hasattr(room, "lair") else room
    m = LAIR_RE.match((r.lair if r else "") or "")
    if not m:
        return 0, []
    mons = [world.monsters.get(int(x)) for x in m.group(2).split(",") if x.strip().isdigit()]
    return int(m.group(1)), [x for x in mons if x]


class Danger:
    def __init__(self, session):
        self.s = session
        self._hit_cache: dict = {}      # (mon, ac, dr) -> avg dmg / round
        self._said: dict = {}           # lair -> lap number we warned on

    def observe(self, room, lost: int):
        """What a fight in this lair really cost us — beats any simulation once we have a few.
        Kept with the lair refill data (lairs.json), so it lasts and syncs."""
        lc = self.s.lairclock
        r = lc._rec(room)
        r["dmg"] = (r.get("dmg", []) + [[max(0, int(lost)), round(__import__("time").time())]])[-12:]
        lc._dirty = lc._dirty or 1.0

    def observed(self, room):
        lc = self.s.lairclock
        lc._load()
        lst = (lc.data.get(lc.key(room)) or {}).get("dmg") or []
        if len(lst) < 3:
            return None
        xs = sorted(x[0] if isinstance(x, list) else x for x in lst)
        return xs[min(len(xs) - 1, int(len(xs) * 0.9))]       # a bad visit, not the average one

    def mob_dpr(self, mon) -> float:
        """Average damage per round this monster does to you."""
        st = self.s.state
        key = (mon["num"], st.ac, st.dr)
        if key not in self._hit_cache:
            # 0.8.180: the same monster at about the same AC/DR is about the same damage. A buff wearing off or
            # going back on changes AC by a few points, and re-simulating every lair on a 784-step Go to on the
            # window's thread froze Miserable PVE until it was closed (2026-11-12)
            for (ac, dr, v) in self.__dict__.setdefault("_hit_by_mon", {}).get(mon["num"], ()):
                if abs((ac or 0) - (st.ac or 0)) <= 10 and abs((dr or 0) - (st.dr or 0)) <= 3:
                    return v
            avg = 0.0
            try:
                from . import monattack
                res = monattack.simulate(self.s.world, mon["num"], {"ac": st.ac, "dr": st.dr}, rounds=600, seed=7,
                                         greatermud=(self.s.settings.exp_formula == "greatermud"))
                if res:
                    avg = float(res.get("avg") or 0)
            except Exception:
                avg = 0.0
            if not avg:
                avg = float((mon.get("attack_data") or {}).get("mme_avg") or 0)
            self._hit_cache[key] = avg
            self.__dict__.setdefault("_hit_by_mon", {}).setdefault(mon["num"], []).append((st.ac, st.dr, avg))
        return self._hit_cache[key]

    def my_dpr(self, mon) -> float:
        """What we do to it per round: the best attack spell we'd pick, else a modest melee guess."""
        s, cfg, st = self.s, self.s.settings, self.s.state
        # 0.8.181: remembered per monster for the spells you have now. Planning a Go to weighs every lair on the way
        # and this went through the whole spellbook for each one, every time; with buffs changing it ran thousands
        # of times on the window's thread (Miserable PVE locking up for 8 s at a time, 2026-11-12)
        try:
            key = (mon.get("num"), cfg.char_level or st.level or 1, s.bot.spellcasting() // 5,
                   tuple(cfg.attack_spells or ()), len(st.known_spells or ()), cfg.spell_dmg_bonus, cfg.spell_min_pct,
                   int(self._seen_dpr() // 25))
        except Exception:
            key = None
        c = self.__dict__.setdefault("_my_cache", {})
        if key is not None and key in c:
            return c[key]
        v = self._my_dpr(mon)
        if key is not None:
            if len(c) > 5000:
                c.clear()
            c[key] = v
        return v

    def _my_dpr(self, mon) -> float:
        s, cfg, st = self.s, self.s.settings, self.s.state
        try:
            cands = list(s.spell_candidates())
            if cands:
                rows = s.spellbook.evaluate(cands, mon, cfg.char_level or st.level or 1, s.bot.spellcasting(),
                                            cfg.spell_dmg_bonus)
                good = [r[2] for r in rows if r[3] >= cfg.spell_min_pct / 100]
                if good:
                    return float(max(max(good), self._seen_dpr()))
        except Exception:
            pass
        seen = self._seen_dpr()
        if seen:
            return seen
        # (0.8.224: no attack spell and nothing seen yet — a guess that grows with level, not a flat 60; the six
        #  characters' real rounds were 107-445 at L41-61)
        return float(max(60, 5 * int(cfg.char_level or st.level or 1)))

    def _seen_dpr(self) -> float:
        """Your own damage a round in this session's fights (10 rounds seen at least), else 0."""
        cl = getattr(self.s, "combatlog", None)
        if cl is None or getattr(cl, "my_rounds", 0) < 10:
            return 0.0
        return float(getattr(cl, "my_round_avg", 0.0) or 0.0)

    def assess(self, room) -> dict | None:
        """{'count', 'mob', 'dmg' (expected damage to you), 'rounds'} for the worst likely spawn."""
        w, st = self.s.world, self.s.state
        n, mons = lair_spawn(w, room)
        if not n or not mons:
            return None
        obs = self.observed(room)
        if obs is not None:
            worst = max(mons, key=lambda m: m.get("exp") or 0)
            return {"count": n, "mob": worst["name"], "dmg": round(obs * 1.2), "rounds": 0, "dpr": 0,
                    "observed": True}
        worst = max(mons, key=self.mob_dpr)
        dpr = self.mob_dpr(worst)
        if dpr <= 0:
            return {"count": n, "mob": worst["name"], "dmg": 0, "rounds": 0}
        hp_total = sum(int(m.get("hp") or 0) for m in [worst] * n) or n * 100
        rounds = math.ceil(hp_total / max(self.my_dpr(worst), 1))
        dmg = dpr * n * rounds * 0.5 * self.party_factor()
        return {"count": n, "mob": worst["name"], "dmg": round(dmg), "rounds": rounds, "dpr": round(dpr)}

    HEALERS = ("priest", "druid", "cleric", "missionary", "bard", "paladin")

    def party_factor(self) -> float:
        """How much of a fight's damage lands on you: the party soaks some, a healer makes it go further."""
        st = self.s.state
        me = (self.s.settings.my_name or "").lower()
        others = [(n, i) for n, i in st.party.items() if n.lower() != me]
        return 1.0 / (1 + 0.6 * len(others)) * self.healed()

    def healed(self) -> float:
        """0.75 with someone else in the party who heals (their heals make the damage go further), else 1."""
        st = self.s.state
        me = (self.s.settings.my_name or "").lower()
        return 0.75 if any(str((i or {}).get("class", "")).lower() in self.HEALERS
                           for n, i in st.party.items() if n.lower() != me) else 1.0

    def floor_hp(self) -> int:
        cfg, st = self.s.settings, self.s.state
        pct = max(int(cfg.run_pct or 0), int(cfg.hangup_hp_pct or 0) if cfg.hangup_low_hp else 0, 20)
        return int(st.max_hp * pct / 100)

    def needed_pct(self, room) -> tuple[float | None, dict | None]:
        """HP % you'd want before walking into this lair (None = no concern)."""
        st = self.s.state
        if not st.max_hp:
            return None, None
        a = self.assess(room)
        if not a or not a["dmg"]:
            return None, a
        need = (a["dmg"] * 1.25 + self.floor_hp()) / st.max_hp * 100
        return need, a


def fight_estimate(danger, recs) -> float:
    """Expected damage to you from the monsters in the room right now (rough, like assess)."""
    st = danger.s.state
    recs = [r for r in recs if r]
    if not recs:
        return 0.0
    room = st.room
    w = danger.s.world
    r = w.room(room) if room else None
    if r and r.lair:
        obs = danger.observed(room)
        if obs is not None:
            return obs * 1.2
    dpr = sum(danger.mob_dpr(m) for m in recs)
    hp = sum(int(m.get("hp") or 100) for m in recs)
    rounds = math.ceil(hp / max(danger.my_dpr(recs[0]), 1))
    return dpr * rounds * 0.5 * danger.party_factor()
