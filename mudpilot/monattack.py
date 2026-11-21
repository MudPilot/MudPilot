"""Monster attack simulator — a port of MajorMUD Explorer's clsMonsterAttackSim
(RunSim / GetMaxDamage / IsSpellResisted / CalcResistedDamage) plus the
modMMudDatabase.PopulateMonsterDataToAttackSim loader and the hit/dodge cap
helpers from modMMudFunc (GetHitMin, GetHitCap, GetSpellHitCap, GetDodgeCap).

Usage:
    from mudpilot.monattack import simulate
    res = simulate(world, mon_num, {"ac": 40, "dr": 5, "dodge": 20, "mr": 60})

The monster needs ``world.monsters[num]["attack_data"]`` (written by
WorldDB.import_mdb); without it simulate() returns None.

VB numeric behaviour that matters is reproduced: VB ``Round`` / Integer
assignment use banker's rounding (Python ``round``), ``Int`` floors, ``Fix``
truncates, Currency keeps 4 decimals.
"""
from __future__ import annotations

import math
import random

# modMMudFunc constants
STOCK_HIT_MIN, GMUD_HIT_MIN = 8, 2
STOCK_HIT_CAP, GMUD_HIT_CAP = 99, 100
STOCK_SPELL_HIT_CAP, GMUD_SPELL_HIT_CAP = 98, 100
STOCK_DODGE_CAP, GMUD_DODGE_SOFTCAP, GMUD_DODGE_CAP = 95, 55, 98

KIND = {1: "melee", 2: "spell", 3: "rob"}
_NOT_RESISTABLE = (4, 6)            # spell AttType: 4 = normal, 6 = poison (no elemental resist)


# ------------------------------------------------------------------ cap helpers
def get_hit_min(greatermud: bool = False, armour_type: int | None = None) -> int:
    """GetHitMin. MME's GMUD variant drops 1 for armour types <= 6 when a class is
    given; the sim itself never passes a class, so armour_type is optional."""
    if greatermud:
        v = GMUD_HIT_MIN
        if armour_type is not None and armour_type <= 6:
            v -= 1
        return v
    return STOCK_HIT_MIN


def get_hit_cap(greatermud: bool = False) -> int:
    return GMUD_HIT_CAP if greatermud else STOCK_HIT_CAP


def get_spell_hit_cap(greatermud: bool = False) -> int:
    return GMUD_SPELL_HIT_CAP if greatermud else STOCK_SPELL_HIT_CAP


def get_dodge_cap(greatermud: bool = False, soft: bool = False) -> int:
    if soft and greatermud:
        return GMUD_DODGE_SOFTCAP
    if greatermud:
        return GMUD_DODGE_CAP
    return STOCK_DODGE_CAP


def gmud_diminishing_returns(value: float, scale: float) -> float:
    """Apply_GMUD_DiminishingReturns (inverse triangular number)."""
    if scale <= 0:
        return value
    neg = value < 0
    if neg:
        value = -value
    tri = (math.sqrt(8.0 * (value / scale) + 1.0) - 1.0) / 2.0
    return -tri * scale if neg else tri * scale


# ------------------------------------------------------------------ spell helpers (modMMudDatabase)
def _clamp_level(sp: dict, lvl: int) -> int:
    if lvl > sp.get("Cap", 0) and sp.get("Cap", 0) > 0:
        lvl = sp["Cap"]
    if lvl < sp.get("ReqLevel", 0):
        lvl = sp["ReqLevel"]
    return lvl


def spell_has_ability(sp: dict | None, abil: int) -> int:
    """SpellHasAbility: -1 = does not have, otherwise the ability value."""
    if not sp or abil <= 0:
        return -1
    for a, v in sp.get("abils", []):
        if a == abil:
            return v
    return -1


def spell_duration(sp: dict | None, lvl: int = 0, for_monster: bool = False) -> int:
    if not sp:
        return 0
    if not for_monster or lvl == 0:
        lvl = _clamp_level(sp, lvl)
    if sp.get("DurIncLVLs", 0) == 0 or lvl < 1:
        return int(sp.get("Dur", 0))
    return int(sp["Dur"] + math.trunc((sp["DurInc"] / sp["DurIncLVLs"]) * lvl))


def spell_damage(spells: dict, num: int, which: str, lvl: int = 0, energy_rem: int = 0,
                 for_monster: bool = False, _depth: int = 0) -> int:
    """GetSpellMinDamage / GetSpellMaxDamage (which = 'Min' | 'Max'), heals not supported."""
    sp = spells.get(str(num)) if num else None
    if not sp:
        return 0
    val, does, end_cast = 0, False, 0
    for a, v in sp.get("abils", []):
        if a in (1, 8, 17, 18):
            if a == 18:                 # heals -> skipped when asking for damage
                continue
            does = True
            if v != 0:
                val = v
        elif a == 151:
            end_cast = v
    if val == 0:
        if not does:
            return 0
        if not for_monster or lvl == 0:
            lvl = _clamp_level(sp, lvl)
        inc_lvls = sp.get(which + "IncLVLs", 0)
        if inc_lvls == 0 or lvl < 1:
            val = sp.get(which + "Base", 0)
        else:
            val = sp.get(which + "Base", 0) + math.trunc((sp.get(which + "Inc", 0) / inc_lvls) * lvl)
    if for_monster:
        return int(val)
    cost = sp.get("EnergyCost", 0)
    if energy_rem == 0:
        energy_rem = 1000
    energy_rem -= cost
    if energy_rem < 1:
        energy_rem = 1
    if energy_rem >= 143 and cost >= 143:
        if end_cast == 0:
            if cost <= 500:
                val = val + val * math.trunc(energy_rem / cost)
        elif _depth < 10:
            val = val + spell_damage(spells, end_cast, which, lvl, energy_rem, for_monster, _depth + 1)
    return int(val)


# ------------------------------------------------------------------ sim state
class MonsterAttackSim:
    """Field-for-field mirror of clsMonsterAttackSim (arrays are 0..4)."""

    def __init__(self):
        self.reset_values()

    def reset_values(self):
        r5 = lambda v=0: [v] * 5
        self.HIT_MIN, self.HIT_CAP, self.SPELL_HIT_CAP = 8, 99, 98
        self.DODGE_CAP, self.DODGE_SOFTCAP = 95, 0
        self.user_ac = self.user_dr = self.user_dodge = self.user_mr = 0
        self.user_antimagic = 0
        self.dodge_before_ac = False
        self.user_prot_evil = 0
        self.mob_is_evil = True
        self.user_rfir = self.user_rcol = self.user_rlit = self.user_rwat = self.user_rsto = 0
        self.energy_per_round = 0
        self.greatermud = False

        self.atk_name = r5("")
        self.atk_type = r5()
        self.atk_energy = r5()
        self.atk_spell_type = r5(4)
        self.atk_min = r5()
        self.atk_max = r5()
        self.atk_chance = r5()
        self.atk_success = r5()
        self.atk_hs_min = r5()
        self.atk_hs_max = r5()
        self.atk_hs_type = r5(4)
        self.atk_hs_name = r5("")
        self.atk_resist = r5()
        self.atk_mr_dmg_resist = r5()
        self.atk_duration = r5()

        self.br_name = r5("")
        self.br_min = r5()
        self.br_max = r5()
        self.br_spell_type = r5(4)
        self.br_chance = r5()
        self.br_resist_type = r5()
        self.br_resist_dmg_mr = r5()
        self.br_duration = r5()

    # -------------------------------------------------------------- formulas
    @staticmethod
    def calc_resisted_damage(dmg: float, mr: int, antimagic: int) -> float:
        if mr > 150:
            mr = 150
        if antimagic == 0:
            pct = round((mr - 50) / 100, 2) if mr < 50 else round((mr - 50) / 200, 2)
        else:
            pct = round(mr / 200, 2)
        return round(dmg - dmg * pct, 4)                     # Currency

    def _elemental_reduction(self, spell_type: int, dmg: float) -> float:
        """The Select Case on spell AttType.  NOTE: VB keeps nResist_Reduction across
        attacks (never reset); here it is computed fresh each time (bug fix)."""
        r = {0: self.user_rcol, 1: self.user_rfir, 2: self.user_rsto,
             3: self.user_rlit, 5: self.user_rwat}.get(spell_type, 0)
        return round(dmg * (r / 100), 4) if r > 0 else 0

    def get_max_damage(self) -> int:
        """GetMaxDamage — theoretical worst round."""
        if not self._anything_to_sim():
            return 0
        total = 0
        low_cost, max_cost = 0, 0
        max_energy_round = None
        for k in range(5):
            if self.atk_type[k] > 0 and self.atk_energy[k] > 0:
                low = self.atk_energy[k]
                if self.atk_type[k] == 2:
                    if ((self.atk_resist[k] == 1 and self.user_antimagic == 1) or self.atk_resist[k] == 2) \
                            or self.atk_success[k] < 100:
                        low = round(self.atk_energy[k] / 2)
                if (low_cost == 0 or low < low_cost) and low > 0:
                    low_cost = low
                if max_cost == 0 or self.atk_energy[k] > max_cost:
                    max_cost = self.atk_energy[k]
            elif self.atk_type[k] > 0 and self.atk_energy[k] == 0 and self.atk_chance[k] > 0:
                low_cost = 0
                max_energy_round = self.energy_per_round * 2
                break
        if max_energy_round is None:
            if low_cost == 0:
                return 0
            least = low_cost
            while least + max_cost <= self.energy_per_round:
                least += low_cost
            rem = self.energy_per_round - least
            if rem < low_cost:
                rem += low_cost - 1
            max_energy_round = self.energy_per_round + rem

        rem = max_energy_round
        x = 1
        while rem >= low_cost and x <= 6:
            best_dmg, best_energy, best_dpe = 0, 0, 0
            for k in range(5):
                e = self.atk_energy[k]
                if 0 < e <= rem and (self.atk_type[k] != 2 or self.atk_success[k] > 0) and self.atk_type[k] > 0:
                    dmg = self.atk_max[k]
                    if self.atk_type[k] == 1 and not self.atk_duration[k] > 1:
                        dmg += self.atk_hs_max[k]
                    attempts = math.trunc(rem / e)
                    if attempts > 6 - x + 1:
                        attempts = 6 - x + 1
                    dpe = round((dmg * attempts) / rem, 4)
                    if dpe > best_dpe:
                        best_dmg, best_dpe, best_energy = dmg, dpe, e
            total += best_dmg
            rem -= best_energy
            x += 1
        for k in range(5):
            if self.atk_type[k] == 1 and self.atk_duration[k] > 1:
                total += self.atk_hs_max[k] * (2 if self.atk_duration[k] > 2 else 1)
            elif self.atk_type[k] == 2 and self.atk_duration[k] > 1:
                total += self.atk_max[k] * (2 if self.atk_duration[k] > 2 else 1)
        best = 0
        for x in range(5):
            if self.br_chance[x] > 0 and not self.br_duration[x] > 1:
                best = max(best, self.br_max[x])
        total += best
        for x in range(5):
            if self.br_chance[x] > 0 and self.br_duration[x] > 1:
                total += self.br_max[x] * (2 if self.br_duration[x] > 2 else 1)
        return int(total)

    def _anything_to_sim(self) -> bool:
        return any(self.atk_min[x] > 0 or self.atk_max[x] > 0 or self.atk_hs_min[x] > 0 or
                   self.atk_hs_max[x] > 0 or self.br_min[x] > 0 or self.br_max[x] > 0 for x in range(5))

    # -------------------------------------------------------------- RunSim
    def run(self, rounds: int, rng: random.Random) -> dict:
        rnd = rng.random

        def R(s, e):                                    # VB RandomNumber: Int(((e-s+1)*Rnd)+s)
            return math.floor((e - s + 1) * rnd() + s)

        def resisted(rtype):                            # IsSpellResisted
            if (rtype == 1 and self.user_antimagic == 1) or rtype == 2:
                roll = R(1, 100)
                return roll <= min(self.user_mr, 196) / 2
            return False

        st_att, st_hit, st_res, st_dodge, st_tot = [0] * 5, [0] * 5, [0] * 5, [0] * 5, [0] * 5
        st_hs_res, st_hs_tot = [0] * 5, [0] * 5
        st_br_res, st_br_tot = [0] * 5, [0] * 5
        st_br_cast, st_br_resisted, st_br_landed = [0] * 5, [0] * 5, [0] * 5
        a_ticks, a_left, a_val, a_orig = [0] * 5, [0] * 5, [0] * 5, [0] * 5
        b_ticks, b_left, b_val, b_orig = [0] * 5, [0] * 5, [0] * 5, [0] * 5
        tot_attacks = tot = tot_phys = tot_spell = 0
        max_round = max_energy = 0

        out = {"rounds": rounds, "avg": 0.0, "phys_avg": 0.0, "spell_avg": 0.0, "max_round_seen": 0,
               "max_possible": self.get_max_damage(), "max_energy_round": 0, "total_attacks": 0,
               "energy_per_round": self.energy_per_round, "attacks": []}
        if rounds < 1 or self.energy_per_round < 1 or not self._anything_to_sim():
            out["attacks"] = self._attack_stats(rounds, 0, st_att, st_hit, st_res, st_dodge, st_tot,
                                                st_br_cast, st_br_resisted, st_br_landed, st_br_res, st_br_tot)
            return out

        HIT_MIN = max(0, self.HIT_MIN)
        HIT_CAP = max(0, self.HIT_CAP)
        DODGE_SOFT = max(0, self.DODGE_SOFTCAP)
        DODGE_CAP = max(0, self.DODGE_CAP)
        ac_pe = self.user_ac + self.user_prot_evil
        dodge, dr, mr, am = self.user_dodge, self.user_dr, self.user_mr, self.user_antimagic
        typ, chance, energy = self.atk_type, self.atk_chance, self.atk_energy
        succ_base, dur = self.atk_success, self.atk_duration
        gmud, dodge_first = self.greatermud, self.dodge_before_ac

        # per-slot hit chance against this AC is constant -> precompute (same formula as in-loop VB)
        adj_success = [0.0] * 5
        adj_dodge = [0] * 5
        for k in range(5):
            s = succ_base[k]
            if typ[k] != 2:
                if ac_pe > 0:
                    if s != 0:
                        s = round(round(1 - ((ac_pe * ac_pe) / 100) / ((s * s) / 140), 2) * 100, 4)
                    else:
                        s = 0
                else:
                    s = HIT_CAP
                if s < HIT_MIN:
                    s = HIT_MIN
                if s > HIT_CAP:
                    s = HIT_CAP
            adj_success[k] = s
            if typ[k] != 2 and dodge > 0 and succ_base[k] >= 8:
                if gmud:
                    acc_t = ((succ_base[k] * succ_base[k]) / 14) / 10
                    d = round((dodge * dodge) / acc_t)
                    if d > DODGE_SOFT and DODGE_SOFT > 0:
                        d = round(DODGE_SOFT + gmud_diminishing_returns(d - DODGE_SOFT, 4.0))
                else:
                    d = math.trunc((dodge * 10) / (succ_base[k] / 8))
                if d > DODGE_CAP:
                    d = DODGE_CAP
                adj_dodge[k] = d

        rem = 0
        epr = self.energy_per_round
        for _round in range(rounds):
            rd = 0
            # ---- extra spell-round ticks (every 3 combat rounds)
            for x in range(5):
                if a_left[x] > 0 and a_ticks[x] == 3:
                    v = a_val[x]
                    rd += v; tot += v; tot_spell += v
                    st_tot[x] += v; st_res[x] += a_orig[x] - v
                    st_hs_res[x] += a_orig[x] - v; st_hs_tot[x] += v
                    a_left[x] -= 1
                    if a_left[x] < 1:
                        a_left[x] = a_ticks[x] = a_val[x] = 0
                if b_left[x] > 0 and b_ticks[x] == 3:
                    v = b_val[x]
                    rd += v; tot += v; tot_spell += v
                    st_br_res[x] += b_orig[x] - v; st_br_tot[x] += v
                    b_left[x] -= 1
                    if b_left[x] < 1:
                        b_left[x] = b_ticks[x] = b_val[x] = 0

            rem += epr
            if rem > max_energy:
                max_energy = rem

            # ---- regular attack attempts
            for _attempt in range(6):
                roll = R(1, 100)
                last_type = last_energy = 0
                for k in range(5):
                    if not (roll <= chance[k] and typ[k] > 0):
                        continue
                    last_energy, last_type = energy[k], typ[k]
                    if rem < energy[k]:
                        break                           # no energy for attack
                    st_att[k] += 1
                    tot_attacks += 1
                    hit = dodged = resist = False
                    dmg = hsd = orig = 0
                    show_hs = False
                    t = typ[k]

                    if dodge_first and dodge > 0 and t != 2:
                        if R(1, 100) <= dodge:
                            dodged = True
                            st_dodge[k] += 1
                    if not dodge_first or not dodged:
                        if R(1, 100) <= adj_success[k]:
                            hit = True
                            if t != 2 and dodge > 0 and not dodge_first and succ_base[k] >= 8:
                                if R(1, 100) <= adj_dodge[k]:
                                    hit = False
                                    dodged = True
                                    st_dodge[k] += 1

                    if hit:
                        dmg = R(self.atk_min[k], self.atk_max[k])
                        orig = dmg
                        if t == 2:                      # ---- spell attack
                            a_orig[k] = dmg
                            if self.atk_mr_dmg_resist[k] == 1 and dmg > 0:
                                dmg = round(self.calc_resisted_damage(dmg, mr, am))
                            if self.atk_spell_type[k] not in _NOT_RESISTABLE:
                                red = self._elemental_reduction(self.atk_spell_type[k], dmg)
                                if red != 0:
                                    dmg = round(dmg - red)
                            if dur[k] > 0:
                                if a_left[k] < 1 or a_val[k] != dmg:
                                    if resisted(self.atk_resist[k]):
                                        st_dodge[k] += 1
                                        resist = True
                                        hit = False
                                        dmg = 0
                                    else:
                                        a_ticks[k] = 0
                                        a_left[k] = dur[k]
                                        a_val[k] = dmg
                                        dmg = 0
                                else:
                                    # duration continues, not really an attempt -> try the next slot
                                    st_att[k] -= 1
                                    tot_attacks -= 1
                                    continue
                            else:
                                if resisted(self.atk_resist[k]):
                                    st_dodge[k] += 1
                                    resist = True
                                    hit = False
                                    dmg = 0
                        else:                           # ---- normal / rob
                            dr_res = dr if dr <= dmg else dmg
                            st_res[k] += dr_res
                            dmg -= dr_res
                            if self.atk_hs_min[k] > 0 or self.atk_hs_max[k] > 0 or dur[k] > 0:
                                hsd = R(self.atk_hs_min[k], self.atk_hs_max[k])
                                a_orig[k] = hsd
                                if self.atk_mr_dmg_resist[k] == 1 and hsd > 0:
                                    mr_red = round(self.calc_resisted_damage(hsd, mr, am))
                                    if dur[k] == 0:
                                        st_res[k] += hsd - mr_red
                                    hsd = mr_red
                                if self.atk_hs_type[k] not in _NOT_RESISTABLE:
                                    red = self._elemental_reduction(self.atk_hs_type[k], hsd)
                                    if red != 0:
                                        if dur[k] == 0:
                                            st_res[k] = round(st_res[k] + red)
                                        hsd = round(hsd - red)
                                if dur[k] > 0:
                                    if a_left[k] < 1 or a_val[k] != hsd:
                                        if resisted(self.atk_resist[k]):
                                            st_res[k] += hsd
                                            show_hs = True
                                            resist = True
                                            hsd = 0
                                        else:
                                            a_ticks[k] = 0
                                            a_left[k] = dur[k]
                                            a_val[k] = hsd
                                            show_hs = True
                                            hsd = 0
                                else:
                                    if resisted(self.atk_resist[k]):
                                        st_res[k] += hsd
                                        resist = True
                                        hsd = 0
                                    show_hs = True
                                if not show_hs:
                                    hsd = 0
                        if dmg <= 0:
                            dmg = 0
                        if hit:
                            if orig != dmg and t == 2 and dur[k] < 1:
                                st_res[k] += orig - dmg
                            rd += dmg + hsd
                            tot += dmg + hsd
                            tot_spell += hsd
                            if t == 2:
                                tot_spell += dmg
                            else:
                                tot_phys += dmg
                            rem -= energy[k]
                            st_hit[k] += 1
                            st_tot[k] += dmg + hsd
                    if not hit:
                        if t == 2:
                            if dur[k] == 0 or resist:
                                rem -= round(energy[k] / 2)
                        else:
                            rem -= energy[k]
                    break                               # GoTo next_attempt
                # next_attempt  (VB checks type 1 here although its comment says 'spell')
                if last_type == 1 and rem < last_energy:
                    break

            # ---- between-round spell cast (one roll for all five slots)
            roll = R(1, 100)
            for x in range(5):
                landed = res = applied = False
                dmg = 0
                if self.br_chance[x] > 0 and roll <= self.br_chance[x]:
                    dmg = R(self.br_min[x], self.br_max[x])
                    b_orig[x] = dmg
                    if self.br_resist_dmg_mr[x] == 1 and dmg > 0:
                        dmg = round(self.calc_resisted_damage(dmg, mr, am))
                    if self.br_spell_type[x] not in _NOT_RESISTABLE:
                        red = self._elemental_reduction(self.br_spell_type[x], dmg)
                        if red != 0:
                            dmg = round(dmg - red)
                    if self.br_duration[x] > 0:
                        if b_left[x] < 1 or b_val[x] != dmg:
                            if resisted(self.br_resist_type[x]):
                                res = True
                                dmg = 0
                            else:
                                b_ticks[x] = 0
                                b_left[x] = self.br_duration[x]
                                b_val[x] = dmg
                                applied = True
                                dmg = 0
                    else:
                        if resisted(self.br_resist_type[x]):
                            res = True
                            dmg = 0
                        else:
                            landed = True
                if applied or res or landed:            # (a still-running duration spell is not a cast)
                    st_br_cast[x] += 1
                if applied:
                    st_br_landed[x] += 1
                    break
                if res:
                    st_br_resisted[x] += 1
                    break
                if landed:
                    st_br_landed[x] += 1
                    rd += dmg; tot += dmg; tot_spell += dmg
                    st_br_tot[x] += dmg
                    break

            # ---- all spell duration ticks
            for x in range(5):
                if a_left[x] > 0:
                    v = a_val[x]
                    rd += v; tot += v; tot_spell += v
                    st_tot[x] += v; st_res[x] += a_orig[x] - v
                    st_hs_res[x] += a_orig[x] - v; st_hs_tot[x] += v
                    a_left[x] -= 1
                    a_ticks[x] = 1 if a_ticks[x] >= 3 else a_ticks[x] + 1
                    if a_left[x] < 1:
                        a_left[x] = a_ticks[x] = a_val[x] = 0
                if b_left[x] > 0:
                    v = b_val[x]
                    rd += v; tot += v; tot_spell += v
                    st_br_res[x] += b_orig[x] - v; st_br_tot[x] += v
                    b_left[x] -= 1
                    b_ticks[x] = 1 if b_ticks[x] >= 3 else b_ticks[x] + 1
                    if b_left[x] < 1:
                        b_left[x] = b_ticks[x] = b_val[x] = 0

            if rd > max_round:
                max_round = rd

        out.update({
            "avg": round(tot / rounds, 2), "phys_avg": round(tot_phys / rounds, 2),
            "spell_avg": round(tot_spell / rounds, 2), "max_round_seen": int(max_round),
            "max_energy_round": max_energy, "total_attacks": tot_attacks,
            "attacks": self._attack_stats(rounds, tot_attacks, st_att, st_hit, st_res, st_dodge, st_tot,
                                          st_br_cast, st_br_resisted, st_br_landed, st_br_res, st_br_tot)})
        return out

    def _attack_stats(self, rounds, tot_attacks, st_att, st_hit, st_res, st_dodge, st_tot,
                      br_cast, br_resisted, br_landed, br_res, br_tot):
        """Same per-attack figures the MME form shows (True cast %, Avg, Success %, Dmg resist %,
        Resist/Dodge %), plus between-round spells."""
        pct = lambda a, b: round(100.0 * a / b, 1) if b else 0.0
        rows = []
        for k in range(5):
            if self.atk_type[k] <= 0:
                continue
            res_pct = 0.0
            if st_res[k] != 0:
                res_pct = 100.0 if st_tot[k] == 0 else pct(st_res[k], st_res[k] + st_tot[k])
            rows.append({"slot": k + 1, "name": self.atk_name[k], "kind": KIND.get(self.atk_type[k], "other"),
                         "hit_spell": self.atk_hs_name[k],
                         "used_pct": pct(st_att[k], tot_attacks), "hit_pct": pct(st_hit[k], st_att[k]),
                         "avg_hit": round(st_tot[k] / st_hit[k], 1) if st_hit[k] and st_tot[k] > 0 else 0.0,
                         "resisted_pct": res_pct, "dodged_pct": pct(st_dodge[k], st_att[k]),
                         "per_round": round(st_tot[k] / rounds, 2) if rounds else 0.0,
                         "attempts": st_att[k], "hits": st_hit[k], "total_damage": st_tot[k]})
        for x in range(5):
            if self.br_chance[x] <= 0:
                continue
            res_pct = 0.0
            if br_res[x] != 0:
                res_pct = 100.0 if br_tot[x] == 0 else pct(br_res[x], br_res[x] + br_tot[x])
            rows.append({"slot": x + 1, "name": self.br_name[x], "kind": "between", "hit_spell": "",
                         "used_pct": pct(br_cast[x], rounds), "hit_pct": pct(br_landed[x], br_cast[x]),
                         "avg_hit": round(br_tot[x] / br_landed[x], 1) if br_landed[x] and br_tot[x] > 0 else 0.0,
                         "resisted_pct": res_pct, "dodged_pct": pct(br_resisted[x], br_cast[x]),
                         "per_round": round(br_tot[x] / rounds, 2) if rounds else 0.0,
                         "attempts": br_cast[x], "hits": br_landed[x], "total_damage": br_tot[x]})
        return rows


# ------------------------------------------------------------------ PopulateMonsterDataToAttackSim
def populate(sim: MonsterAttackSim, ad: dict, greatermud: bool = False) -> None:
    nmr = float(ad.get("nmr_ver") or 0)
    spells = ad.get("spells") or {}
    sim.energy_per_round = int(ad.get("energy") or 0) if nmr >= 1.71 else 1000
    ib = ad.get("item_bonus") or {}
    dmg_bonus = int(ib.get("dmg_gmud" if greatermud else "dmg", 0))
    acc_bonus = int(ib.get("acc_gmud" if greatermud else "acc", 0))
    sim.mob_is_evil = ad.get("align") in (1, 2, 5, 6)

    for x, a in enumerate((ad.get("att") or [])[:5]):
        t = int(a.get("type") or 0)
        if not 0 < t < 4:
            continue
        if nmr >= 1.8:
            name = a.get("name") or ""
        else:
            name = ""
            if t == 2 and a.get("acc", 0) > 0:
                name = (spells.get(str(a["acc"])) or {}).get("Name", "")
            if name in ("", "None"):
                name = f"Attack {x + 1}"
        sim.atk_name[x] = name.strip()
        sim.atk_type[x] = t
        sim.atk_energy[x] = int(a.get("energy") or 0)
        sim.atk_chance[x] = int(a.get("pct") or 0)
        if t == 2:                                       # spell attack: AttAcc = spell #, AttMax = cast level
            snum, lvl = int(a.get("acc") or 0), int(a.get("max") or 0)
            sp = spells.get(str(snum))
            if not sp:
                continue
            if not greatermud and sp.get("Targets") == 12:
                if spell_duration(sp, lvl, True) == 0 and spell_has_ability(sp, 1) > -1:
                    # area spell in a regular slot using ability 1: MMUD won't cast it
                    sim.atk_duration[x] = sim.atk_min[x] = sim.atk_max[x] = sim.atk_energy[x] = 0
                    continue
            if nmr >= 1.8:
                sim.atk_resist[x] = int(sp.get("TypeOfResists") or 0)
            sim.atk_spell_type[x] = int(sp.get("AttType") or 0)
            sim.atk_duration[x] = spell_duration(sp, lvl, True)
            sim.atk_min[x] = sim.atk_max[x] = 0
            for abil, mrflag in ((1, 0), (17, 1), (8, 0)):
                n = spell_has_ability(sp, abil)
                if n >= 0:
                    sim.atk_mr_dmg_resist[x] = mrflag
                    if n > 0:
                        sim.atk_min[x] = sim.atk_max[x] = n
                    else:
                        sim.atk_min[x] = spell_damage(spells, snum, "Min", lvl, -1, True)
                        sim.atk_max[x] = spell_damage(spells, snum, "Max", lvl, -1, True)
            sim.atk_success[x] = int(a.get("min") or 0)  # AttMin = cast %
        else:
            sim.atk_min[x] = int(a.get("min") or 0) + dmg_bonus
            sim.atk_max[x] = int(a.get("max") or 0) + dmg_bonus
            sim.atk_success[x] = int(a.get("acc") or 0) + acc_bonus
            hs = int(a.get("hit_spell") or 0)
            if hs > 0:
                sp = spells.get(str(hs))
                if not sp:
                    continue
                if nmr >= 1.8:
                    sim.atk_resist[x] = int(sp.get("TypeOfResists") or 0)
                sim.atk_hs_name[x] = sp.get("Name", "")
                sim.atk_hs_type[x] = int(sp.get("AttType") or 0)
                sim.atk_duration[x] = spell_duration(sp)
                if spell_has_ability(sp, 1) >= 0:
                    sim.atk_mr_dmg_resist[x] = 0
                    sim.atk_hs_min[x] = spell_damage(spells, hs, "Min")
                    sim.atk_hs_max[x] = spell_damage(spells, hs, "Max")
                elif spell_has_ability(sp, 17) >= 0:
                    sim.atk_mr_dmg_resist[x] = 1
                    sim.atk_hs_min[x] = spell_damage(spells, hs, "Min")
                    sim.atk_hs_max[x] = spell_damage(spells, hs, "Max")
                else:
                    sim.atk_hs_min[x] = sim.atk_hs_max[x] = 0

    for x, m in enumerate((ad.get("mid") or [])[:5]):
        snum, lvl = int(m.get("spell") or 0), int(m.get("lvl") or 0)
        if snum <= 0:
            continue
        sp = spells.get(str(snum))
        if not sp:
            continue
        sim.br_name[x] = sp.get("Name", "")
        sim.br_spell_type[x] = int(sp.get("AttType") or 0)
        if nmr >= 1.8:
            sim.br_resist_type[x] = int(sp.get("TypeOfResists") or 0)
        sim.br_chance[x] = int(m.get("pct") or 0)
        sim.br_duration[x] = spell_duration(sp, lvl, True)
        for abil, mrflag in ((1, 0), (17, 1), (8, 0)):
            n = spell_has_ability(sp, abil)
            if n >= 0:
                sim.br_resist_dmg_mr[x] = mrflag
                if n > 0:
                    sim.br_min[x] = sim.br_max[x] = n
                else:
                    sim.br_min[x] = spell_damage(spells, snum, "Min", lvl, -1, True)
                    sim.br_max[x] = spell_damage(spells, snum, "Max", lvl, -1, True)

    names = sim.atk_name                                 # disambiguate duplicate attack names
    for x in range(5):
        if names[x]:
            for y in range(5):
                if y != x and names[x] == names[y]:
                    names[x] = names[x].strip() + str(x + 1)
                    names[y] = names[y].strip() + str(y + 1)


# ------------------------------------------------------------------ public API
def build_sim(world, mon_num: int, user: dict | None = None, greatermud: bool = False) -> MonsterAttackSim | None:
    mon = world.monsters.get(mon_num) if world is not None else None
    ad = mon.get("attack_data") if mon else None
    if not ad:
        return None
    user = user or {}
    sim = MonsterAttackSim()
    sim.greatermud = bool(greatermud)
    sim.HIT_MIN = get_hit_min(greatermud)
    sim.HIT_CAP = get_hit_cap(greatermud)
    sim.SPELL_HIT_CAP = get_spell_hit_cap(greatermud)
    sim.DODGE_SOFTCAP = get_dodge_cap(greatermud, soft=True)
    sim.DODGE_CAP = get_dodge_cap(greatermud)
    pos = lambda k, d=0: max(0, int(user.get(k, d) or 0))   # form only passes values > 0
    sim.user_ac, sim.user_dr, sim.user_dodge = pos("ac"), pos("dr"), pos("dodge")
    sim.user_mr = pos("mr", 50) or 50
    sim.user_prot_evil = pos("prot_evil")
    sim.user_rcol, sim.user_rfir, sim.user_rsto = pos("rcol"), pos("rfir"), pos("rsto")
    sim.user_rlit, sim.user_rwat = pos("rlit"), pos("rwat")
    sim.user_antimagic = 1 if user.get("antimagic") else 0
    sim.dodge_before_ac = bool(user.get("dodge_before_ac", False))
    populate(sim, ad, greatermud)
    return sim


def simulate(world, mon_num: int, user: dict | None = None, rounds: int = 2000,
             greatermud: bool = False, seed=None) -> dict | None:
    """Estimate how hard monster ``mon_num`` hits a player with the given defences.

    user keys (all optional): ac, dr, dodge, mr (default 50), antimagic (bool), prot_evil,
    rcol, rfir, rsto, rlit, rwat, dodge_before_ac (bool, MME's "always dodge" option).

    Returns None when the monster has no attack data (old world.db), else a dict:
      avg, phys_avg, spell_avg (damage / round), max_round_seen, max_possible (MME GetMaxDamage),
      rounds, energy_per_round, max_energy_round, total_attacks, mob_is_evil, mme_avg (MME's
      precomputed AvgDmg column, stock settings: AC 0, MR 50) and
      attacks: [{slot, name, kind (melee|spell|rob|between), hit_spell, used_pct, hit_pct, avg_hit,
                 resisted_pct, dodged_pct, per_round, attempts, hits, total_damage}]
    """
    sim = build_sim(world, mon_num, user, greatermud)
    if sim is None:
        return None
    rng = random.Random(seed)
    res = sim.run(max(0, int(rounds)), rng)
    ad = world.monsters[mon_num]["attack_data"]
    res["mob_is_evil"] = sim.mob_is_evil
    res["mme_avg"] = ad.get("mme_avg")
    return res
