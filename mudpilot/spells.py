"""Spell damage vs. a specific monster — a port of MME's CalculateSpellCast /
CalculateResistDamage — plus automatic spell choice.

"Rated" damage = the spell's average round damage against a target with no magic
resistance and no elemental resists. "Effective" = against this monster, after its
MR, full-resist chance, anti-magic, undead-only and elemental resist (rcol/rfir/
rsto/rlit/rwat). A spell is skipped when effective/rated < the threshold (75%).

Actual hits seen in the game are recorded per (monster, spell); once there are a few
samples, the observed average overrides the calculation.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

# MME AttType -> monster ability holding the matching resist
ELEMENT_ABIL = {0: 3, 1: 5, 2: 65, 3: 66, 5: 147}
ELEMENT_NAME = {0: "cold", 1: "fire", 2: "stone", 3: "lightning", 5: "water"}
ABIL_DAMAGE, ABIL_DRAIN, ABIL_DMG_MR, ABIL_UNDEAD_ONLY, ABIL_ANTIMAGIC, ABIL_NONMAGIC = 1, 8, 17, 23, 51, 144
SPELL_HIT_CAP = 98


def _vb_round(x: float) -> int:
    """VB6 Round() is banker's rounding — Python's round() matches."""
    return int(round(x))


def _fix(x: float) -> int:
    return int(x)  # truncate toward zero, like VB Fix()


def resist_damage(dmg: float, vs_mr: int, resist_type: int = 2, dmg_resistable: bool = True,
                  include_total: bool = False, antimagic: bool = False) -> int:
    if vs_mr <= 0:
        vs_mr = 1
    dr = 0.0
    if dmg_resistable:
        if antimagic:
            dr = min(_fix(vs_mr / 2), 75)
        elif vs_mr > 51:
            dr = min(_fix((vs_mr - 50) / 2), 50)
        if dr > 0:
            dmg = dmg * (1 - dr / 100)
        elif not antimagic and vs_mr < 50:
            dmg = dmg + (dmg * (50 - vs_mr)) / 100
    if include_total and vs_mr > 1 and (resist_type == 2 or (antimagic and resist_type == 1)):
        dmg = dmg * (1 - min(_fix(vs_mr / 2), 98) / 100)
    return _vb_round(dmg)


@dataclass
class SpellCalc:
    spell: dict
    cast_level: int
    min: int
    max: int
    per_cast: int          # avg damage per successful cast (after resists)
    casts: int
    cast_chance: int
    full_resist: int
    round_dmg: int         # expected damage per round
    mana: int
    element: str | None
    resist_pct: int        # monster's elemental resist that applied


def spell_minmax(sp: dict, level: int):
    lvl = level
    cap, req = int(sp.get("Cap") or 0), int(sp.get("ReqLevel") or 0)
    if lvl <= 0:
        lvl = max(lvl, cap)
    lvl = max(lvl, req)
    if cap > 0:
        lvl = min(lvl, cap)
    mn, mx = int(sp.get("MinBase") or 0), int(sp.get("MaxBase") or 0)
    if sp.get("MinIncLVLs") and sp.get("MinInc"):
        mn += _fix(sp["MinInc"] / sp["MinIncLVLs"] * lvl)
    if sp.get("MaxIncLVLs") and sp.get("MaxInc"):
        mx += _fix(sp["MaxInc"] / sp["MaxIncLVLs"] * lvl)
    return lvl, mn, mx


def calc(sp: dict, level: int, mon: dict | None = None, spellcasting: int = 0, bonus_pct: int = 0) -> SpellCalc:
    abil_list = [tuple(a) for a in sp.get("abils", [])]
    att = int(sp.get("AttType") or 0)
    mabils = (mon or {}).get("abils", {})
    elem_res = int(mabils.get(ELEMENT_ABIL.get(att, -1), 0)) if mon else 0
    vs_mr = int(mon.get("mr", 0)) if mon else 0
    antimagic = bool(mon) and ABIL_ANTIMAGIC in mabils
    lvl, mn, mx = spell_minmax(sp, level)
    avg = _vb_round((mn + mx) / 2)
    mult = 1 + round(bonus_pct / 100, 2) if bonus_pct > 0 else 1
    avg_mod, min_mod = _fix(avg * mult), _fix(mn * mult)
    diff = int(sp.get("Diff") or 0)
    kai = int(sp.get("Magery") or 0) == 5
    if spellcasting > 0 and diff < 200:
        cc = max(0, spellcasting + diff)
        cc = min(cc, 100 if kai else SPELL_HIT_CAP)
    else:
        cc = 100
    nonmagic = any(a == ABIL_NONMAGIC for a, _ in abil_list)
    dmg = 0
    for a, v in abil_list:
        if a == ABIL_DAMAGE:
            dmg += avg_mod if v == 0 else v
            if elem_res:
                dmg = _vb_round(dmg - _vb_round(dmg * elem_res / 100))
        elif a == ABIL_DRAIN:
            dmg = dmg + avg_mod if v == 0 else v
        elif a == ABIL_DMG_MR:
            t = avg_mod if v == 0 else v
            if vs_mr > 0 and not nonmagic:
                dmg += resist_damage(t, vs_mr, int(sp.get("TypeOfResists") or 0), True, False, antimagic)
            else:
                dmg += t
            if elem_res:
                dmg = _vb_round(dmg - _vb_round(dmg * elem_res / 100))
    if any(a == ABIL_UNDEAD_ONLY for a, _ in abil_list) and mon and not mon.get("undead"):
        dmg = 0
    if mon and spell_blocked(sp, mon):
        dmg = 0
    full = 0
    rtype = int(sp.get("TypeOfResists") or 0)
    if vs_mr > 0 and (rtype == 2 or (rtype == 1 and antimagic)):
        full = min(_fix(vs_mr / 2), 98)
    energy = int(sp.get("EnergyCost") or 0)
    casts = _fix(1000 / energy) if 0 < energy <= 500 else 1
    rnd = _vb_round(dmg * casts * (cc / 100) * (1 - full / 100))
    return SpellCalc(sp, lvl, mn, mx, max(dmg, 0), casts, cc, full, max(rnd, 0),
                     int(sp.get("ManaCost") or 0) * casts, ELEMENT_NAME.get(att) if elem_res or att in ELEMENT_NAME else None,
                     elem_res)


ABIL_SPELL_IMMU, ABIL_AFFECTS_LIVING, ABIL_NONLIVING = 139, 108, 109


def spell_blocked(sp: dict, mon: dict) -> str:
    """Why this spell can't touch this monster at all ('' = it can): MME SpellImmu (139) — immune to
    spells below that level, all spells at 900+ — and 'affects living' spells on nonliving monsters."""
    mabils = (mon or {}).get("abils", {}) or {}
    imm = int(mabils.get(ABIL_SPELL_IMMU, 0) or 0)
    if imm >= 900:
        return "immune to spells"
    if imm > 0 and int(sp.get("ReqLevel") or 0) < imm:
        return f"immune to spells below level {imm}"
    if ABIL_NONLIVING in mabils and any(int(a) == ABIL_AFFECTS_LIVING for a, _ in (tuple(x) for x in sp.get("abils", []))):
        return "only affects the living"
    return ""


def is_attack_spell(sp: dict) -> bool:
    return any(a in (ABIL_DAMAGE, ABIL_DRAIN, ABIL_DMG_MR) for a, _ in (tuple(x) for x in sp.get("abils", [])))


class SpellBook:
    """Picks the best attack spell for the current target and learns from real hits."""

    REFUSED_RE = re.compile(r"don'?t know (?:that|the|any) spell|have not learned|not learned that|"
                            r"^huh\?|unknown spell|you can'?t cast that|no such spell", re.I)
    HIT_RE = re.compile(r"(?:for|doing|causing)\s+(\d+)\s+(?:points of\s+)?damage", re.I)
    RESIST_RE = re.compile(r"\bresists?\b|\bunaffected\b|no effect", re.I)
    FAIL_RE = re.compile(r"attempt to cast .*(?:but|and) fail|you fail to cast|your spell fails|spell fizzles|"
                         r"fail(?:ed)? to cast", re.I)

    def __init__(self, world):
        self.world = world
        self.observed: dict = {}         # (mon_num, spell_num) -> [damages]
        self.refused: set = set()        # spell numbers the game said we can't cast (this session)
        self.no_effect: set = set()      # (monster num, spell num): "Your spell has no effect on …" — never again
        self.on_refused = lambda sp: None
        self._last_cast = None           # (mon_num, spell_num, t)
        self.tries: dict = {}            # spell_num -> [casts, fails] seen this session
        self.memory_path = None          # spell_memory.json: spells seen hurting / not touching a monster, kept
        self._remembered: set = set()    # across restarts (Dan, 2026-11-14: Evolution relogged, forgot fury hits
                                         # copsewights and quaked a single one)

    def load_memory(self, path):
        """What earlier sessions saw: a spell that hurt a monster ([mon, spell, dmg]) and 'no effect' pairs."""
        import json
        self.memory_path = path
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        for mn, sn, dmg in d.get("hits") or []:
            self.observed.setdefault((int(mn), int(sn)), []).append(int(dmg))
            self._remembered.add((int(mn), int(sn)))
        for mn, sn in d.get("no_effect") or []:
            self.no_effect.add((int(mn), int(sn)))

    def _save_memory(self):
        import json
        import os
        if not self.memory_path:
            return
        hits = [[k[0], k[1], max(v)] for k, v in self.observed.items() if k in self._remembered and v and max(v) > 0]
        try:
            tmp = self.memory_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"hits": hits, "no_effect": [list(k) for k in self.no_effect]}, f)
            os.replace(tmp, self.memory_path)
        except OSError:
            pass

    def _remember_hit(self, key, dmg):
        """The first time a spell is seen hurting a monster: written down for the next session."""
        if dmg > 0 and key[0] and key not in self._remembered:
            self._remembered.add(key)
            self._save_memory()

    def success_factor(self, sp, mme_chance: int) -> float:
        """How the game's real cast rate compares with MME's guess (after 6+ casts)."""
        c, f = self.tries.get(sp["Number"], (0, 0))
        if c < 6 or not mme_chance:
            return 1.0
        return max(0.0, (c - f) / c) / (mme_chance / 100)

    def resolve(self, short: str, name: str = "", level: int = -1, mana: int = -1) -> dict | None:
        """The castable spell behind a line of the game's spell list. MME often has several
        spells sharing a short name (monster versions, item procs), so match the short,
        name, level and mana together."""
        key = (short, name, level, mana)
        cache = getattr(self, "_resolve_cache", None)
        if cache is None or cache.get("_world") is not self.world.spells:
            cache = self._resolve_cache = {"_world": self.world.spells}
        if key not in cache:
            cache[key] = self._resolve(short, name, level, mana)
        return cache[key]

    def _resolve(self, short, name="", level=-1, mana=-1):
        sh, nm = short.strip().lower(), name.strip().lower()
        best, best_score = None, -1
        for sp in self.world.spells.values():
            if (sp.get("Short") or "").lower() != sh:
                continue
            sc = 0
            if nm and (sp.get("Name") or "").lower() == nm:
                sc += 100
            if level >= 0 and int(sp.get("ReqLevel") or 0) == level:
                sc += 30
            if mana >= 0 and int(sp.get("_mme_mana", sp.get("ManaCost")) or 0) == mana:
                sc += 30
            if int(sp.get("Learnable") or 0):
                sc += 20
            if int(sp.get("ReqLevel") or 0) > 0:
                sc += 5
            if sc > best_score:
                best, best_score = sp, sc
        if best is None and nm:
            best = next((sp for sp in self.world.spells.values() if (sp.get("Name") or "").lower() == nm
                         and int(sp.get("Learnable") or 0)), None)
        return best

    def find(self, name) -> dict | None:
        if isinstance(name, dict):
            return name                  # already a resolved spell record
        n = name.strip().lower()
        if n.startswith("#"):
            # an item spell command ('#etc' = the emerald-tipped crozier's divine intervention — itemspells.py)
            from .itemspells import spell_for
            return spell_for(self.world, n, (getattr(self, "carrying", None) or (lambda: ""))())
        # the one in your own spell list first: 'fury' is elemental fury for a druid, divine fury for a priest
        # (Dan, 2026-11-14: Evolution's attack spell 'fury' went out as the Priest's divine fury)
        try:
            for sp in (getattr(self, "known", None) or (lambda: []))():
                if (sp.get("Short") or "").lower() == n:
                    return sp
        except Exception:
            pass
        hit = self.resolve(n)
        if hit:
            return hit
        for sp in self.world.spells.values():
            if (sp.get("Name") or "").lower() == n and int(sp.get("Learnable") or 0):
                return sp
        for sp in self.world.spells.values():
            if (sp.get("Name") or "").lower() == n:
                return sp
        return None

    def evaluate(self, names: list, mon: dict, level: int, spellcasting: int = 0, bonus: int = 0) -> list:
        """Return [(spell, rated, effective, ratio, calc, source)] best first."""
        rows, seen = [], set()
        for nm in names:
            sp = self.find(nm)
            if not sp or not is_attack_spell(sp) or sp["Number"] in seen:
                continue
            seen.add(sp["Number"])
            rated = calc(sp, level, None, spellcasting, bonus)
            eff = calc(sp, level, mon, spellcasting, bonus)
            r_val, e_val, source = rated.round_dmg, eff.round_dmg, "MME"
            obs = self.observed.get((mon["num"], sp["Number"])) if mon else None
            if obs and len(obs) >= 3:
                per = sum(obs) / len(obs)
                e_val = _vb_round(per * eff.casts * eff.cast_chance / 100)
                source = f"seen x{len(obs)}"
            ratio = (e_val / r_val) if r_val else 0.0
            rows.append((sp, r_val, e_val, ratio, eff, source))
        rows.sort(key=lambda r: r[2], reverse=True)
        return rows

    def choose(self, names: list, mon: dict, level: int, mana: int, threshold: float,
               spellcasting: int = 0, bonus: int = 0):
        """Best spell whose effectiveness >= threshold and that we can afford. None = melee."""
        for sp, rated, eff, ratio, c, src in self.evaluate(names, mon, level, spellcasting, bonus):
            if self.useless(mon, sp):
                continue                          # can't touch this monster (magical, or 'no effect' before)
            if ratio >= threshold and eff > 0 and mana >= c.spell.get("ManaCost", 0):
                return sp, rated, eff, ratio, src
        return None

    def auto_pick(self, spells, mobs, level, mana, threshold, spellcasting=0, bonus=0, mode="damage", area_min=0,
                  exclude=()):
        return auto_pick(self, spells, mobs, level, mana, threshold, spellcasting, bonus, mode, area_min, exclude)

    # --- learning from game output
    def can_hit(self, mon, sp) -> bool:
        """Can this spell touch this monster at all? Only the monster's spell immunity says no (MME SpellImmu: immune
        to spells below that level), or an 'affects the living' spell on a nonliving one. MME's 'Magical: N' is
        about weapons, not spells (Dan, 2026-11-14: "magic 5 and level 50 spells have no relation… most magic 5 are
        level 40 restricted, some are not"). It fits what the game showed: the prismatic dragon (immunity 15)
        shrugged off vine strike and stonestrike but not blaze (20); a copsewight (no immunity, Magical 4) takes
        vine strike for 13; a blood skeleton (immunity 20) ignored swarm (12)."""
        if not mon or not sp:
            return True
        return not spell_blocked(sp, mon)

    def useless(self, mon, sp) -> bool:
        """This spell can't hurt this monster: it had no effect before, or the monster is too magical for it."""
        if not (mon and sp):
            return False
        return ((mon or {}).get("num", 0), sp.get("Number")) in self.no_effect or not self.can_hit(mon, sp)

    def note_cast(self, mon: dict | None, sp: dict):
        if sp:
            self._last_cast = ((mon or {}).get("num", 0), sp["Number"], time.time())
            self._active = [(mon or {}).get("num", 0), sp["Number"], time.time()]   # repeats every round
            self._round_seen = time.time()           # this round's result is the first-cast window's
            t = self.tries.setdefault(sp["Number"], [0, 0])
            t[0] += 1
            if t[0] > 40:                  # keep it recent
                t[0], t[1] = 20, round(t[1] / 2)

    def feed_line(self, text: str):
        from .spelltune import ACTOR_ME_RE
        if ACTOR_ME_RE.match(text.strip()):
            self._gesture_at = time.time()          # "You make a complex circling gesture!"
        if "*combat off*" in text.lower():
            self._active = None
        lc = self._last_cast
        if not lc or time.time() - lc[2] > 3:
            self._round_after(text)
            return
        if "already cast a spell this round" in text.lower():
            t = self.tries.get(lc[1])
            if t and t[0] > 0:
                t[0] -= 1                            # didn't go out at all: not a try
            self._last_cast = None
            return
        short = ((self.world.spells.get(lc[1]) or {}).get("Short") or "").lower()
        if self.REFUSED_RE.search(text.strip()) or (short and text.strip().lower().startswith(f'you say "{short}')):
            # (a spell you don't have, with talk set fast, just comes out as 'You say "dtch serpent"')
            self.refused.add(lc[1])
            self._last_cast = None
            self.on_refused(self.world.spells.get(lc[1]))
            return
        if self.FAIL_RE.search(text):
            self.tries.setdefault(lc[1], [1, 0])[1] += 1
            self._last_cast = None
            return
        low = text.lower()
        if "you for" in low or " hits you" in low:
            return  # monster hitting us
        m = self.HIT_RE.search(text)
        st_ = text.strip()
        mine = low.lstrip().startswith(("your ", "you ")) or (
            time.time() - getattr(self, "_gesture_at", 0) < 2.5 and re.match(r"^(?:an?|the)\s", st_, re.I))
        if m and not mine:
            return                                   # someone else's damage ("Deacon summons holy ire …")
        if m:
            self.observed.setdefault(lc[:2], []).append(int(m.group(1)))
            self.observed[lc[:2]] = self.observed[lc[:2]][-20:]
            self._remember_hit(lc[:2], int(m.group(1)))
            self._last_cast = None
        elif re.search(r"no effect (?:on|against)|only (?:affects|works on) (?:the )?undead|has no effect on", text, re.I) \
                and "in this room" not in text.lower():
            # "Your exorcism has no effect on the troll" — don't wait for 3 tries: switch spells now, and never
            # cast it at that monster again (Dan, 2026-10-29: PVE dtch'd a surf elemental to death)
            self.observed[lc[:2]] = [0, 0, 0]
            key = lc[:2]
            mn = re.search(r"no effect (?:on|against) (?:the |an? )?(.+?)[.!]?\s*$", text.strip(), re.I)
            if mn and lc[0] and not re.match(r"(?:this|that) (?:monster|creature)|it\b|you\b", mn.group(1), re.I):
                # (0.8.201, bug hunt: an area spell's "no effect on blood skeleton" got stored against the kobold
                # thief it was aimed past, for good — the line names the monster: that's the one it can't hurt)
                said = mn.group(1).strip().lower()
                mine_ = ((getattr(self.world, "monsters", None) or {}).get(lc[0]) or {}).get("name", "").lower()
                if not (mine_ and mine_ in said):
                    hit = [m for m in (getattr(self.world, "monsters", None) or {}).values()
                           if (m.get("name") or "").lower() and said.endswith((m.get("name") or "").lower())]
                    hit.sort(key=lambda m: (-len(m["name"]), not m.get("in_game")))
                    key = (hit[0]["num"], lc[1]) if hit else None
            if key and key[0]:
                self.no_effect.add(key)
                self._remembered.discard(key)
                self._save_memory()
            self._last_cast = None
        elif self.RESIST_RE.search(text) and "in this room" not in text.lower():
            self.observed.setdefault(lc[:2], []).append(0)
            self._last_cast = None

    def _round_after(self, text):
        """The game repeats the spell each round by itself (MudPilot doesn't re-send it), so every round
        after the first is a cast too: learn its damage, resists and fizzles the same way. One sample a
        round (an area spell hits several monsters in one round)."""
        a = getattr(self, "_active", None)
        if not a:
            return
        now = time.time()
        if now - a[2] > 120:
            self._active = None
            return
        if now - getattr(self, "_round_seen", 0) < 2.5:
            return
        low = text.lower()
        st_ = text.strip()
        key = (a[0], a[1])
        if self.FAIL_RE.search(text) and low.lstrip().startswith("you"):
            t = self.tries.setdefault(a[1], [0, 0])
            t[0] += 1
            t[1] += 1
            self._round_seen = now
            return
        if "you for" in low or " hits you" in low:
            return
        m = self.HIT_RE.search(text)
        if m and low.lstrip().startswith("your "):
            self.observed.setdefault(key, []).append(int(m.group(1)))
            self.observed[key] = self.observed[key][-20:]
            self._remember_hit(key, int(m.group(1)))
            self.tries.setdefault(a[1], [0, 0])[0] += 1
            self._round_seen = now
        elif self.RESIST_RE.search(text) and low.lstrip().startswith("your ") and "in this room" not in low:
            self.observed.setdefault(key, []).append(0)
            self.tries.setdefault(a[1], [0, 0])[0] += 1
            self._round_seen = now


def buff_range(sp: dict, level: int) -> tuple[int, int]:
    """Possible roll for a buff spell (e.g. ManaRegen from flux/ntap/nity) at a level."""
    _lvl, mn, mx = spell_minmax(sp, level)
    return mn, mx


# Mana-regen rerolls (ability 145, Spell effects / "spells:" line)
MANA_REGEN_PRESETS = {
    "flux": {"name": "Mana flux", "target": 100},
    "ntap": {"name": "Nature tap", "target": 150},
    "nity": {"name": "Serenity", "target": 50},
}


# ---------------------------------------------------------------- automatic spell choice
SINGLE_TARGETS = {4, 8}          # Monster / Monster or User
AREA_TARGETS = {9: "divided", 12: "full"}   # attack-area spells (never hit your party)


# Instant but hard to land and dear: for bosses, not every room (Dan, 2026-11-02: "Acid tempest is not a combat spell
# its a curse.. Its instant and only used really for bosses")
BOSS_ONLY = {"acid tempest"}


def lasting(sp: dict) -> bool:
    """A spell that sits on the monster for rounds (acid rain, burning aura: 1 a tick plus AC down) — a curse, not
    a round's attack (Revolution, 2026-11-03: acid rain on the blood skeletons, "this is not a combat spell")."""
    return int(sp.get("Dur") or 0) > 0


def fight_spell(sp: dict, mobs=()) -> bool:
    """One the bot may pick for itself this fight: no curses, and the boss spells only with a boss in the room."""
    if lasting(sp):
        return False
    return (sp.get("Name") or "").lower() not in BOSS_ONLY or any((m or {}).get("boss") for m in mobs)


def spell_kind(sp: dict) -> str | None:
    t = int(sp.get("Targets") or 0)
    if t in SINGLE_TARGETS:
        return "single"
    return AREA_TARGETS.get(t)


def class_spells(world, cls: int, level: int) -> list:
    """Spells a class can learn up to a level (port of MME's SpellIsUsable). A fallback for
    when the game's `spells` list hasn't been read yet."""
    c = world.classes.get(cls)
    if not c:
        return []
    magery, mlvl = int(c.get("MageryType") or 0), int(c.get("MageryLVL") or 0)
    out = []
    for sp in world.spells.values():
        learnable = int(sp.get("Learnable") or 0) > 0 or len(str(sp.get("Learned From") or "")) >= 5
        if not learnable and int(sp.get("Magery") or 0) != 5:
            continue
        sm = int(sp.get("Magery") or 0)
        if sm:
            if not magery or magery != sm:
                continue
            if mlvl and mlvl < int(sp.get("MageryLVL") or 0):
                continue
        classes = str(sp.get("Classes") or "")
        if len(classes) > 2 and classes != "(*)" and f"({cls})" not in classes:
            continue
        if level and level < int(sp.get("ReqLevel") or 0):
            continue
        if not sp.get("Short"):
            continue
        out.append(sp)
    return out


def auto_pick(book, spells: list, mobs: list, level: int, mana: int, threshold: float,
              spellcasting: int = 0, bonus: int = 0, mode: str = "damage", area_min: int = 0,
              exclude=(), mana_floor: float = 0.5):
    """Best attack spell for the room right now.

    spells: candidate spell dicts. mobs: monster records in the room, target first.
    Single-target spells are judged on the target; attack-area spells on every mob
    present (full area hits each one; divided splits the damage between them).
    A spell is out if the target takes less than `threshold` of the rated damage
    (e.g. fire on a 50% rfir mob), or for an area spell if the room as a whole does.
    area_min: area spells only when at least this many mobs are here, and then they're
    preferred over single-target spells (0 = just pick whatever does the most).
    Returns (spell, effective round dmg, ratio, kind, note) or None."""
    if not mobs:
        return None
    spells = [sp for sp in spells if sp["Number"] not in book.refused and sp["Number"] not in exclude
              and fight_spell(sp, mobs)]
    target = mobs[0]
    best, rows = None, []
    for sp in spells:
        if not is_attack_spell(sp):
            continue
        kind = spell_kind(sp)
        if not kind:
            continue
        if area_min and kind != "single" and len(mobs) < area_min:
            continue
        cost = int(sp.get("ManaCost") or 0)
        rated_one = calc(sp, level, None, spellcasting, bonus).round_dmg
        if rated_one <= 0:
            continue
        obs = book.observed.get((target["num"], sp["Number"]))
        eff_t = calc(sp, level, target, spellcasting, bonus).round_dmg
        if obs and len(obs) >= 3:
            c = calc(sp, level, target, spellcasting, bonus)
            eff_t = round(sum(obs) / len(obs) * c.casts * c.cast_chance / 100)
        fac = book.success_factor(sp, calc(sp, level, None, spellcasting, bonus).cast_chance)
        eff_t = round(eff_t * fac)
        ratio_t = eff_t / rated_one
        if kind == "single":
            eff, rated = eff_t, rated_one
        else:
            per = [round(calc(sp, level, m, spellcasting, bonus).round_dmg * fac) for m in mobs]
            per[0] = eff_t
            if kind == "full":
                eff, rated = sum(per), rated_one * len(mobs)
            else:
                eff, rated = round(sum(per) / len(per)), rated_one
        ratio = eff / rated if rated else 0
        ok = ratio >= threshold and ratio_t >= threshold * (0.5 if kind != "single" else 1)
        afford = mana >= cost
        score = eff if mode == "damage" else (eff / max(cost, 1))
        rows.append((sp, eff, ratio, kind, ok, afford, score))
    usable = [r for r in rows if r[4] and r[5] and r[1] > 0]
    if mode != "damage" and usable:
        # saving mana: the cheapest spell per damage — but never a toy spell (magic missile at level 47);
        # it has to do at least half what the hardest one does
        top = max(r[1] for r in usable)
        usable = [r for r in usable if r[1] >= top * mana_floor] or usable
    for sp, eff, ratio, kind, _ok, _af, score in usable:
        prefer = 1 if (area_min and len(mobs) >= area_min and kind != "single") else 0
        key = (prefer, score, int(sp.get("ReqLevel") or 0))
        if best is None or key > best[0]:
            best = (key, sp, eff, ratio, kind)
    if not best:
        return None
    _k, sp, eff, ratio, kind = best
    note = f"{kind} target" if kind == "single" else f"{kind} area x{len(mobs)}"
    return sp, eff, ratio, kind, note


SPELL_ROUND_SECS = 3      # MME: spell durations count 3-second spell rounds


def spell_duration(sp: dict | None, level: int = 0) -> int | None:
    """How long a spell lasts, in seconds (MME's GetSpellMinMax duration x 3 s).
    None when this board's MME data predates spell durations (re-import it)."""
    if not sp or "Dur" not in sp:
        return None
    dur = int(sp.get("Dur") or 0)
    inc, lv = int(sp.get("DurInc") or 0), int(sp.get("DurIncLVLs") or 0)
    if inc and lv and level:
        dur += int(inc / lv * level)
    return dur * SPELL_ROUND_SECS


TARGET_NAMES = {0: "no target", 1: "yourself", 2: "you or a player", 3: "a player", 4: "a monster",
                5: "an item", 6: "the room", 7: "your party", 8: "a monster or player", 9: "every monster (damage divided)",
                10: "everyone in the room", 11: "a direction", 12: "every monster here (full damage)"}
RESIST_NAMES = {0: "can't be resisted", 1: "magic resistance", 2: "magic resistance (half)", 3: "anti-magic only"}


def describe(world, sp: dict, level: int = 0) -> str:
    """What a spell does, in words — Game Data → Spells, click one (Dan, 2026-11-01)."""
    from .gearcalc import ABIL_NAMES
    lvl, mn, mx = spell_minmax(sp, level)
    out = [f"{(sp.get('Name') or '').title()}  ({sp.get('Short') or '—'})"]
    mana = int(sp.get("ManaCost") or 0)
    mme = sp.get("_mme_mana")
    out.append(f"Level {sp.get('ReqLevel') or 0} · mana {mana}" + (f" (yours — MME says {mme})" if mme is not None
                                                                     and mme != mana else "")
               + (f" · energy {sp['EnergyCost']}" if sp.get("EnergyCost") not in (None, 0, 1000) else "")
               + f" · cast at {TARGET_NAMES.get(int(sp.get('Targets') or 0), 'target type ' + str(sp.get('Targets')))}")
    if is_attack_spell(sp):
        elem = {0: "cold", 1: "fire", 2: "stone", 3: "lightning", 4: "magic", 5: "water"}.get(int(sp.get("AttType") or -1))
        out.append(f"Damage {mn}–{mx} at level {lvl}" + (f" · {elem}" if elem else ""))
    elif mn or mx:
        out.append(f"Strength {mn}–{mx} at level {lvl}")
    dur = spell_duration(sp, level)
    if dur:
        out.append(f"Lasts about {dur // 60} min {dur % 60} s" if dur >= 60 else f"Lasts about {dur} s")
    out.append(f"Resisted by: {RESIST_NAMES.get(int(sp.get('TypeOfResists') or 0), 'type ' + str(sp.get('TypeOfResists')))}"
               + (f" · difficulty {sp['Diff']}" if sp.get("Diff") not in (None, 0) else ""))
    eff = []
    for a, v in (tuple(x) for x in sp.get("abils") or []):
        if a in (115, 101, 148, 122) or a is None:
            continue                                  # (message text / spell links: not an effect)
        nm = ABIL_NAMES.get(int(a))
        if not nm:
            continue                                  # (an unnamed link — another spell, a text block)
        if v in (0, None) and (mn or mx) and not any("–" in e for e in eff):
            eff.append(f"{nm} {mn}–{mx}")             # the spell's roll goes to its first effect; the rest are flags
        elif v in (0, None):
            eff.append(nm)
        else:
            eff.append(f"{nm} {v:+d}" if isinstance(v, int) else f"{nm} {v}")
    if eff:
        out.append("Effects: " + ", ".join(eff))
    lf = str(sp.get("Learned From") or "")
    m = re.match(r"Item #(\d+)", lf)
    if m and world is not None:
        it = (getattr(world, "items", {}) or {}).get(int(m.group(1))) or {}
        lf = f"{it.get('name') or lf}"
    if lf:
        out.append(f"Learned from: {lf}")
    cls = str(sp.get("Classes") or "")
    if cls and cls != "(*)":
        out.append(f"Classes: {cls}")
    return "\n".join(out)


def apply_mana_overrides(world, overrides: dict | None):
    """Your own mana cost per spell (Game Data → Spells). Power-levelling: a low character with too little mana
    still 'casts' — it engages the fight and earns its share even though the spell never goes off (Dan,
    2026-11-01). MME's cost is kept, so clearing it puts it back."""
    ov = {str(k): v for k, v in (overrides or {}).items()}
    for num, sp in (getattr(world, "spells", {}) or {}).items():
        if "_mme_mana" not in sp:
            sp["_mme_mana"] = int(sp.get("ManaCost") or 0)
        v = ov.get(str(num))
        sp["ManaCost"] = int(v) if v is not None else sp["_mme_mana"]


def default_recast(sp: dict | None, level: int = 0, margin: int = 15) -> int | None:
    """Recast a bless this long after casting it: its duration minus `margin` seconds."""
    d = spell_duration(sp, level)
    if not d:
        return None
    return max(d - margin, 10)
