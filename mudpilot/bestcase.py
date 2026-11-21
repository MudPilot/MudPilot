"""Best case: the gear that would make the most exp/hr in one hunting area (Best spots → Best case…).

Dan, 2026-10-28: "what gear/stats would give you the best exp rate in a given area" — from anything in the game,
with where each piece comes from.

How it works (rough, and says so):
  * the area's monsters (Best spots' list) are what you'd fight;
  * a small model turns your numbers into exp/hr there: rounds to kill each monster (your best attack spell —
    Spellcasting counts — or your weapon), the damage it does you meanwhile (MME's attack simulator at your AC,
    DR, dodge, magic resist and resists), then the rest that damage and the mana you spent cost you (HP and mana
    regen, max HP, max mana);
  * every worn item and weapon in the game you could use (class, race, level, alignment, strength — MME's own
    rules) is tried slot by slot, keeping the one that raises that exp/hr most, twice over (a better weapon can
    change what's worth wearing);
  * the model is only compared with itself: Best spots' own estimate for the area is scaled by how much better
    the kit does than what you wear now.
"""
from __future__ import annotations

import math

from . import gearcalc as G

ROUND_SECS = 5.0          # a combat round
WALK_SECS = 8.0           # walking and looking, per kill (only matters relative to the rest)
ABILS = {"spc": 70, "mreg": 145, "mmax": 69, "hmax": 88, "hreg": 123, "mr": 36, "acc": 22, "crit": 58,
         "dodge": 34, "rfir": 5, "rcol": 3, "rlit": 66, "rsto": 65, "rwat": 147}
GOAL_KEYS = ["AC + DR", "Spellcasting (70)", "Mana regen (145)", "Max mana (69)", "Max HP (88)", "HP regen (123)",
             "Magic resist (36)", "Accuracy (22)", "Crits (58)", "Dodge (34)"]
PER_GOAL = 5              # candidates per slot per goal


def _ab(g, aid) -> float:
    return float((g or {}).get("abils", {}).get(aid, 0) or 0)


class BestCase:
    def __init__(self, session, mons: list, progress=None):
        self.s = session
        self.w = session.world
        self.mons = [m for m in mons if m and m.get("hp")]
        self.progress = progress or (lambda msg: None)
        self._sim = {}
        st, cfg, w = session.state, session.settings, self.w
        self.level = st.level or cfg.char_level or 30
        cname = (st.char_class or cfg.char_class or "").lower()
        self.cls = next((k for k, c in w.classes.items() if (c.get("Name") or "").lower() == cname), 0)
        rname = (st.race or cfg.char_race or "").lower()
        self.race = next((k for k, r in w.races.items() if (r.get("Name") or "").lower() == rname), 0)
        self.ch = G.Char(cls=self.cls, race=self.race, level=self.level, align=cfg.char_alignment or "Any",
                         strength=st.strength or 0, include_limited=True)
        c = w.classes.get(self.cls, {})
        self.combat = max(int(c.get("CombatLVL") or 3) - 2, 0)
        self.worn = G.worn_items(w, st.carrying or "")
        from .gamestate import wielded
        wn = wielded(st.carrying or "").lower()
        self.weapon = next((g for g in w.gear.values() if (g.get("name") or "").lower() == wn), None) if wn else None
        # your numbers with nothing worn: what the game shows, less what your gear adds
        base = {"ac": st.ac or 0, "dr": st.dr or 0, "mr": st.magic_res or 50, "spc": st.spellcasting or 0,
                "hmax": st.max_hp or 300, "mmax": st.max_ma or 0, "mreg": 0, "hreg": 0, "acc": 0, "crit": 0,
                "dodge": 0, "rfir": 0, "rcol": 0, "rlit": 0, "rsto": 0, "rwat": 0}
        try:
            v = st.abil_value(145, "total")
            base["mreg"] = float(v[0]) if v else 0
        except Exception:
            pass
        for g in list(self.worn.values()):
            for k, d in self._delta(g).items():
                base[k] -= d
        self.base = base

    # ------------------------------------------------------------ model
    @staticmethod
    def _delta(g) -> dict:
        if not g:
            return {}
        d = {"ac": G.ac(g), "dr": G.dr(g)}
        for k, aid in ABILS.items():
            v = _ab(g, aid)
            if v:
                d[k] = d.get(k, 0) + v
        if 36 in g.get("abils", {}):
            d["mr"] = d.get("mr", 0) + _ab(g, 36)
        return d

    def stats(self, kit: dict, weapon) -> dict:
        st = dict(self.base)
        for g in kit.values():
            for k, d in self._delta(g).items():
                st[k] = st.get(k, 0) + d
        st["weapon"] = weapon
        return st

    def _hits(self, mon, st) -> float:
        from . import monattack
        key = (mon["num"], round(st["ac"] / 5), round(st["dr"] / 2), round(st["dodge"] / 5), round(st["mr"] / 5),
               round(st["rfir"] / 10), round(st["rcol"] / 10), round(st["rlit"] / 10))
        if key not in self._sim:
            user = {"ac": st["ac"], "dr": st["dr"], "dodge": st["dodge"], "mr": st["mr"], "rfir": st["rfir"],
                    "rcol": st["rcol"], "rlit": st["rlit"], "rsto": st["rsto"], "rwat": st["rwat"],
                    "antimagic": False, "prot_evil": 0}
            try:
                r = monattack.simulate(self.w, mon["num"], user, rounds=300, seed=1,
                                       greatermud=(self.s.settings.exp_formula == "greatermud"))
                self._sim[key] = r["avg"] if r else float((mon.get("attack_data") or {}).get("mme_avg") or 0)
            except Exception:
                self._sim[key] = float((mon.get("attack_data") or {}).get("mme_avg") or 0)
        return self._sim[key]

    def _spell(self, mon, spc):
        """(damage a round, mana a round) for your best attack spell at this Spellcasting."""
        s, cfg = self.s, self.s.settings
        key = ("sp", mon["num"], round(spc / 5))
        if key not in self._sim:
            best = (0, 0)
            try:
                cands = list(s.spell_candidates())
                rows = s.spellbook.evaluate(cands, mon, self.level, int(spc), cfg.spell_dmg_bonus) if cands else []
                for sp, _r, eff, ratio, _c, _src in rows:
                    if ratio >= cfg.spell_min_pct / 100 and eff > best[0]:
                        best = (eff, int(sp.get("ManaCost") or 0))
            except Exception:
                pass
            self._sim[key] = best
        return self._sim[key]

    def _melee(self, mon, st) -> float:
        g = st["weapon"] or {"name": "fists", "abils": {}, "Speed": 1000, "Min": 1, "Max": 4, "StrReq": 0, "Accy": 0}
        st_ = self.s.state
        f = G.Fighter(level=self.level, combat=self.combat, agility=st_.agility or 50, strength=st_.strength or 50,
                      encum_pct=int(st_.enc[3]) if st_.enc else 33, accuracy=int(st["acc"]), crit=int(st["crit"]))
        try:
            return G.weapon_round(g, f, mon).round_dmg
        except Exception:
            return 0

    def exp_hr(self, st) -> float:
        """Exp an hour against this area's monsters (one at a time, equally often) — for comparing kits."""
        exp = secs = 0.0
        hreg = max(0.2, st["hmax"] * 0.004 + st["hreg"] / 50)        # HP a second resting (rough)
        mreg = max(0.05, max(st["mmax"], 1) * 0.004 + st["mreg"] / 50)  # mana a second resting (rough)
        for mon in self.mons:
            sd, sm = self._spell(mon, st["spc"]) if st["mmax"] else (0, 0)
            md = self._melee(mon, st)
            dmg, mana = (sd, sm) if sd >= md else (md, 0)
            if dmg <= 0:
                continue
            rounds = math.ceil(mon["hp"] / dmg)
            hp_lost = self._hits(mon, st) * rounds
            if hp_lost >= st["hmax"]:
                continue                                # you'd die: this kit can't take this one
            rest = hp_lost / hreg + (mana * rounds) / mreg if st["mmax"] else hp_lost / hreg
            exp += float(mon.get("exp") or 0)
            secs += rounds * ROUND_SECS + rest + WALK_SECS
        return exp * 3600 / secs if secs else 0.0

    # ------------------------------------------------------------ search
    def _candidates(self):
        """{slot base: [gear]} — the most promising worn items per slot, for anything that matters here."""
        out = {}
        for goal in GOAL_KEYS:
            for r in G.optimize(self.w, goal, self.ch, alts=PER_GOAL - 1):
                base = r.slot.split(" ")[0]
                for g in ([r.best] if r.best else []) + [a for a, _v in r.alts]:
                    lst = out.setdefault(base, [])
                    if g not in lst:
                        lst.append(g)
        return out

    def _weapons(self):
        st_ = self.s.state
        f = G.Fighter(level=self.level, combat=self.combat, agility=st_.agility or 50, strength=st_.strength or 50,
                      encum_pct=int(st_.enc[3]) if st_.enc else 33)
        seen, out = set(), []
        for mon in self.mons[:4]:
            for sw in G.best_weapons(self.w, self.ch, f, mon, limit=8):
                if sw.weapon["name"] not in seen:
                    seen.add(sw.weapon["name"])
                    out.append(sw.weapon)
        # a caster's staff that adds Spellcasting doesn't win on melee damage — keep them in the running
        for g in self.w.gear.values():
            if int(g.get("ItemType") or 0) == 1 and _ab(g, 70) > 0 and g["name"] not in seen:
                ok, _ = G.usable(self.w, g, self.ch)
                ok2, _ = G.class_can_wield(self.w, g, self.cls)
                if ok and ok2:
                    seen.add(g["name"])
                    out.append(g)
        return out

    def run(self) -> dict:
        if not self.mons:
            return {"error": "No monsters to size up in this area."}
        kit = {slot: g for slot, g in self.worn.items() if slot in G.SLOTS}
        weapon = self.weapon
        now_hr = self.exp_hr(self.stats(kit, weapon))
        self.progress("Looking through every item you could use…")
        cands = self._candidates()
        weapons = self._weapons()
        best_hr = now_hr
        for _pass in range(2):
            self.progress(f"Trying weapons ({len(weapons)})…")
            for g in weapons:
                if int(g.get("WeaponType") or 0) in (1, 3) and kit.get("Off-Hand"):
                    k2 = {s: x for s, x in kit.items() if s != "Off-Hand"}   # a two-hander frees the off-hand
                else:
                    k2 = kit
                hr = self.exp_hr(self.stats(k2, g))
                if hr > best_hr * 1.001:
                    best_hr, weapon, kit = hr, g, dict(k2)
            for slot in G.SLOTS:
                base = slot.split(" ")[0]
                if base == "Off-Hand" and weapon and int(weapon.get("WeaponType") or 0) in (1, 3):
                    continue
                self.progress(f"Trying {slot}…")
                for g in cands.get(base, []):
                    if slot.endswith("2") and int(g.get("Limit") or 0) and kit.get(base + " 1") is g:
                        continue                    # a limited item can't be worn twice
                    k2 = dict(kit)
                    k2[slot] = g
                    hr = self.exp_hr(self.stats(k2, weapon))
                    if hr > best_hr * 1.001:
                        best_hr, kit = hr, k2
        rows = []
        if weapon is not self.weapon:
            rows.append(self._row("Weapon", self.weapon, weapon))
        for slot in G.SLOTS:
            if kit.get(slot) is not self.worn.get(slot):
                rows.append(self._row(slot, self.worn.get(slot), kit.get(slot)))
        return {"now": now_hr, "best": best_hr, "rows": rows,
                "stats_now": self.stats({s: g for s, g in self.worn.items() if s in G.SLOTS}, self.weapon),
                "stats_best": self.stats(kit, weapon)}

    def _row(self, slot, cur, new):
        src = "; ".join(t for t, _r in G.sources(self.w, new, 2)) if new else ""
        return {"slot": slot, "now": (cur or {}).get("name") or "—", "best": (new or {}).get("name") or "(nothing)",
                "from": src, "item": new}
