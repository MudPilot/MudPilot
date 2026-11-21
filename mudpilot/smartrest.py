"""Smart resting (0.8.207, Dan + Revolution's druid): pick the quickest way back to 'rest until' HP and mana.

Four ways, judged on this character's own learned numbers:
  rest              — sit; HP comes back fast, mana slower
  meditate + heals  — the heal spell turns mana into HP (Revolution: greater mend, 34.5 HP for 9 mana ≈ 14 HP
                      for each second of meditating, against ~2 HP/s resting)
  rgen + meditate   — one regeneration cast, HP ticks up while meditating for mana
  heals → rgen      — a few heals out of the danger zone, one rgen, then meditate

Each cast stands you up and costs a round. Rates are learned from finished rests (Stats → Rest log): uninterrupted
rests of 20 s or more, per kind. The heal's size from the game's own 'healing N damage' lines; rgen's from rests
meditated with it running. Until enough is known it does nothing and the usual rest / meditate rules apply.
"""
from __future__ import annotations

import time

EMA = 0.25
MIN_N = 3


def spell_avg(sp, level: int) -> float:
    """Average heal per cast (or per round, for a heal over time) from MME's spell data at this level.
    (Checks out on greater mend at level 52: 25-45, seen 25-45 in 560 casts.)"""
    lv = min(int(level or 1), int(sp.get("Cap") or 999) or 999)
    lo = int(sp.get("MinBase") or 0) + (lv // int(sp.get("MinIncLVLs") or 0) * int(sp.get("MinInc") or 0)
                                        if sp.get("MinIncLVLs") else 0)
    hi = int(sp.get("MaxBase") or 0) + (lv // int(sp.get("MaxIncLVLs") or 0) * int(sp.get("MaxInc") or 0)
                                        if sp.get("MaxIncLVLs") else 0)
    return max(0.0, (lo + max(lo, hi)) / 2)


def spell_rounds(sp, level: int) -> int:
    lv = min(int(level or 1), int(sp.get("Cap") or 999) or 999)
    d = int(sp.get("Dur") or 0)
    if sp.get("DurIncLVLs") and sp.get("DurInc"):
        d += lv // int(sp["DurIncLVLs"]) * int(sp["DurInc"])
    return d


class SmartRest:
    def __init__(self, bot):
        self.b = bot
        self._rgen_until = 0.0
        self._rgen_cast = 0.0
        self.last_plan = None

    # ------------------------------------------------------------------ learned numbers
    @property
    def cfg(self):
        return self.b.cfg

    def _r(self) -> dict:
        r = getattr(self.cfg, "smart_rest_rates", None)
        if not isinstance(r, dict):
            r = {}
            self.cfg.smart_rest_rates = r
        return r

    def _ema(self, key, val):
        r = self._r()
        old, n = r.get(key), int(r.get(key + "_n", 0))
        r[key] = val if old is None else old + EMA * (val - old)
        r[key + "_n"] = n + 1

    def learn_rest(self, row, max_hp, max_ma):
        """A finished rest from stats: {'kind', 'secs', 'start': {hp, ma}, 'end': {hp, ma}, 'breaks', 'ended'}."""
        try:
            secs = float(row.get("secs") or 0)
            if secs < 20 or row.get("breaks") or row.get("ended") == "a fight broke it up":
                return
            kind = "med" if row.get("kind") == "meditate" else "rest"
            s, e = row["start"], row["end"]
            if max_hp and e["hp"] > s["hp"] and e["hp"] < 100:
                hps = (e["hp"] - s["hp"]) * max_hp / 100 / secs
                if row.get("rgen") and kind == "med":
                    base = self._r().get("med_hp")
                    if base is not None:
                        self._ema("rgen_hps", max(0.0, hps - base))
                else:
                    self._ema(kind + "_hp", hps)
            if max_ma and e["ma"] > s["ma"] and e["ma"] < 100:
                self._ema(kind + "_ma", (e["ma"] - s["ma"]) * max_ma / 100 / secs)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass

    def learn_heal(self, amount: int):
        self._ema("heal", float(amount))

    # ------------------------------------------------------------------ spells
    def _spell(self, cmd):
        w = (cmd or "").split()
        if not w:
            return None
        return self.b.s.spellbook.find(w[1] if w[0].lower() in ("cast", "c") and len(w) > 1 else w[0])

    def _level(self):
        return int(self.b.st.level or self.cfg.char_level or 1)

    def heal(self):
        """(HP per cast, mana per cast) for the heal command, or None."""
        sp = self._spell(self.cfg.heal_cmd)
        if not sp or not int(sp.get("ManaCost") or 0):
            return None
        r = self._r()
        amt = r["heal"] if int(r.get("heal_n", 0)) >= MIN_N else spell_avg(sp, self._level())
        return (amt, int(sp["ManaCost"])) if amt > 0 else None

    def rgen(self):
        """(HP per second, seconds it lasts, mana) for the HP regen spell, or None."""
        sp = self._spell(self.cfg.hp_regen_cmd)
        if not sp or not int(sp.get("ManaCost") or 0):
            return None
        rnd = float(getattr(getattr(self.b.s, "clock", None), "period", 5.0) or 5.0)
        rounds = spell_rounds(sp, self._level())
        if rounds <= 0:
            return None
        r = self._r()
        hps = r["rgen_hps"] if int(r.get("rgen_hps_n", 0)) >= MIN_N else spell_avg(sp, self._level()) / rnd
        return (hps, rounds * rnd, int(sp["ManaCost"])) if hps > 0 else None

    def rgen_active(self, now=None) -> bool:
        return (now or time.time()) < self._rgen_until

    def cast_rgen(self):
        g = self.rgen()
        now = time.time()
        self._rgen_cast = now
        self._rgen_until = now + (g[1] if g else 60)

    def rgen_fizzled(self):
        if time.time() - self._rgen_cast < 4:
            self._rgen_until = 0.0

    # ------------------------------------------------------------------ plan
    def rates(self):
        r = self._r()
        if int(r.get("med_hp_n", 0)) < MIN_N or int(r.get("med_ma_n", 0)) < MIN_N:
            return None
        med_hp, med_ma = r["med_hp"], r["med_ma"]
        # resting is learned more slowly (a caster mostly meditates): until then, Revolution's measured ratios
        rest_hp = r["rest_hp"] if int(r.get("rest_hp_n", 0)) >= 2 else med_hp * 3.2
        rest_ma = r["rest_ma"] if int(r.get("rest_ma_n", 0)) >= 2 else med_ma * 0.82
        return rest_hp, rest_ma, med_hp, med_ma

    def plan(self, hp, max_hp, ma, max_ma, tgt_hp, tgt_ma):
        """The quickest way to tgt_hp % / tgt_ma %: {'name', 'secs', 'heals', 'rgens', 'rest_secs'}, or None when
        it doesn't know enough (the usual rules apply)."""
        rt = self.rates()
        if not rt or not max_hp or not max_ma:
            return None
        rest_hp, rest_ma, med_hp, med_ma = rt
        hd = max(0.0, tgt_hp * max_hp / 100 - hp)
        md = max(0.0, tgt_ma * max_ma / 100 - ma)
        if hd <= 0:
            return None                        # mana only: meditate, as before
        rest_secs = max(hd / rest_hp if rest_hp else 9e9, md / rest_ma if rest_ma else 0)
        best = {"name": "rest", "secs": rest_secs, "heals": 0, "rgens": 0, "rest_secs": rest_secs}
        rnd = float(getattr(getattr(self.b.s, "clock", None), "period", 5.0) or 5.0)
        he = self.heal()
        rg = self.rgen()
        active = self.rgen_active()
        rg_left = max(0.0, self._rgen_until - time.time()) if active and rg else 0.0

        def solve(n, k):
            for T in range(0, 1800, 2):
                t = max(0.0, T - rnd * (n + k))
                got = med_hp * t + (he[0] * n if he else 0)
                if rg:
                    got += min(rg[0] * rg[1] * k, rg[0] * t) + min(rg_left, t) * rg[0]
                need_ma = md + (he[1] * n if he else 0) + (rg[2] * k if rg else 0)
                if got >= hd and med_ma * t >= need_ma:
                    return float(T)
            return 9e9
        ns = range(0, 25) if he else [0]
        ks = range(0, 3) if rg and not active else [0]
        for k in ks:
            for n in ns:
                # can't spend mana we don't have on the casts up front
                if (he[1] * n if he else 0) + (rg[2] * k if rg else 0) > ma:
                    continue
                T = solve(n, k)
                if T < best["secs"] - 1:
                    nm = ("heals → rgen + meditate" if n and k else "rgen + meditate" if k else
                          "meditate + heals" if n else "meditate")
                    best = {"name": nm, "secs": T, "heals": n, "rgens": k, "rest_secs": rest_secs}
        self.last_plan = best
        return best

    def next_action(self, hp, max_hp, ma, max_ma, tgt_hp, tgt_ma):
        """'heal' / 'rgen' first (heals go before rgen), then 'meditate' or 'rest'; None = not enough known."""
        key, now = (hp, ma, tgt_hp, tgt_ma, self.rgen_active()), time.time()
        c = getattr(self, "_cache", None)
        if c and c[0] == key and now - c[1] < 3:
            p = c[2]
        else:
            p = self.plan(hp, max_hp, ma, max_ma, tgt_hp, tgt_ma)
            self._cache = (key, now, p)
        if not p:
            return None
        if p["heals"]:
            return "heal"
        if p["rgens"]:
            return "rgen"
        return "rest" if p["name"] == "rest" else "meditate"
