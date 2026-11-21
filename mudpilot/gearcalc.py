"""Inventory calculator: best armour per worn slot for a goal (AC, mana regen, max mana…),
using the board's MME item data and MME's own usability rules (ItemIsUsableByChar):
level min/max, class-OK override, class/race lists, armour type, shields for one-handed
classes, magical items vs anti-magic classes, alignment, strength."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

_HERE = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(_HERE, "abil_names.json"), "r", encoding="utf-8") as f:
        ABIL_NAMES = {int(k): v for k, v in json.load(f).items()}
except (OSError, ValueError):
    ABIL_NAMES = {}

# MME worn codes -> slot (fingers and wrists have two slots each)
WORN_SLOT = {1: "Everywhere", 2: "Head", 3: "Hands", 4: "Finger", 5: "Feet", 6: "Arms", 7: "Back", 8: "Neck",
             9: "Legs", 10: "Waist", 11: "Torso", 12: "Off-Hand", 13: "Finger", 14: "Wrist", 15: "Ears",
             16: "Worn", 17: "Wrist", 18: "Eyes", 19: "Face"}
SLOTS = ["Head", "Ears", "Eyes", "Face", "Neck", "Back", "Torso", "Arms", "Wrist 1", "Wrist 2", "Hands",
         "Finger 1", "Finger 2", "Waist", "Legs", "Feet", "Off-Hand", "Worn", "Everywhere"]
ARMOUR_TYPES = {0: "Natural", 1: "Silk", 2: "Ninja", 3: "Leather", 4: "Leather", 5: "Leather", 6: "Leather",
                7: "Chainmail", 8: "Scalemail", 9: "Platemail"}

# goal name -> how to score an item ("ac"/"dr" special, otherwise an ability id)
GOALS = {
    "Armour class (AC)": "ac", "Damage resist (DR)": "dr", "AC + DR": "acdr",
    "Mana regen (145)": 145, "Max mana (69)": 69, "Max HP (88)": 88, "HP regen (123)": 123,
    "Spellcasting (70)": 70, "Accuracy (22)": 22, "Dodge (34)": 34, "Crits (58)": 58,
    "Magic resist (36)": 36, "Stealth (27)": 27, "Perception (77)": 77,
    "Resist fire (5)": 5, "Resist cold (3)": 3, "Resist lightning (66)": 66, "Resist stone (65)": 65,
    "Resist water (147)": 147,
}
ALIGNMENTS = ["Any", "Good", "Neutral", "Evil"]


def ac(g) -> float:
    return (int(g.get("ArmourClass") or 0) + g["abils"].get(2, 0)) / 10


def dr(g) -> float:
    return (int(g.get("DamageResist") or 0) + g["abils"].get(7, 0)) / 10


def score(g, goal) -> float:
    if goal == "ac":
        return ac(g)
    if goal == "dr":
        return dr(g)
    if goal == "acdr":
        return ac(g) + dr(g)
    return g["abils"].get(goal, 0)


def fmt(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


@dataclass
class Char:
    cls: int = 0          # 0 = any class
    race: int = 0         # 0 = any race
    level: int = 0        # 0 = ignore level limits
    align: str = "Any"
    strength: int = 0     # 0 = ignore strength requirement
    include_limited: bool = True
    include_not_in_game: bool = False


def usable(world, g, ch: Char) -> tuple[bool, str]:
    """Port of MME's ItemIsUsableByChar (+ race list and strength)."""
    ab = g["abils"]
    if not g.get("In Game") and not ch.include_not_in_game:
        return False, "not in game"
    if int(g.get("Limit") or 0) > 0 and not ch.include_limited:
        return False, "limited item"
    if ch.level:
        if ab.get(135, 0) > ch.level:
            return False, f"needs level {ab[135]}"
        if 136 in ab and ab[136] < ch.level:
            return False, f"max level {ab[136]}"
    if ch.strength and int(g.get("StrReq") or 0) > ch.strength:
        return False, f"needs {g['StrReq']} strength"
    al = {"Good": (97, 110), "Neutral": (112, 113), "Evil": (98, 111)}.get(ch.align)
    if al:
        need = [a for a in (97, 98, 112) if a in ab]
        if need and al[0] not in need:
            return False, "alignment"
        if al[1] in ab:
            return False, "alignment"
    if ch.race and g.get("races") and ch.race not in g["races"]:
        return False, "race"
    if not ch.cls:
        return True, ""
    cl = world.classes.get(ch.cls, {})
    class_ok = ab.get(59, 0) == ch.cls
    cl_abils = {int(cl.get(f"Abil-{x}") or 0) for x in range(10)}
    if 51 in cl_abils and 28 in ab:
        return False, "magical (anti-magic class)"
    if not class_ok:
        if g.get("classes") and ch.cls not in g["classes"]:
            return False, "class"
        if g.get("classes") and ch.cls in g["classes"]:
            return True, ""
        if int(g.get("ItemType") or 0) == 0:
            if int(cl.get("ArmourType") or 0) < int(g.get("ArmourType") or 0):
                return False, f"armour type ({ARMOUR_TYPES.get(int(g.get('ArmourType') or 0), '?')})"
            if int(g.get("Worn") or 0) == 12 and int(cl.get("WeaponType") or 0) in (0, 2, 4, 9):
                return False, "shield (one-handed class)"
    return True, ""


def sources(world, g, limit=3) -> list[str]:
    """Readable 'where to get it' from MME's Obtained From field."""
    out = []
    for m in re.finditer(r"(Shop|Monster|Item|Textblock|Room|Spell) #(\d+)(?:\(([\d.]+)%\))?", g.get("obtained", "")):
        kind, num, pct = m.group(1), int(m.group(2)), m.group(3)
        if kind == "Shop":
            sh = world.shops.get(num, {})
            rm = sh.get("rooms") or []
            out.append((0, f"sold: {sh.get('name') or f'shop #{num}'}" + (f" ({rm[0][0]}/{rm[0][1]})" if rm else ""),
                        rm[0] if rm else None))
        elif kind == "Monster":
            mon = world.monsters.get(num)
            out.append((1, f"drop: {mon['name'] if mon else f'monster #{num}'}" + (f" {pct}%" if pct else ""),
                        tuple(mon["spawn_rooms"][0]) if mon and mon.get("spawn_rooms") else None, float(pct or 0)))
        elif kind == "Item":
            it = world.items.get(num)
            out.append((2, f"inside: {it['name'] if it else f'item #{num}'}" + (f" {pct}%" if pct else ""), None))
        elif kind == "Textblock":
            out.append((3, "quest / scripted", None))
    out.sort(key=lambda x: (x[0], -(x[3] if len(x) > 3 else 0)))
    seen, res = set(), []
    for o in out:
        if o[1] in seen:
            continue
        seen.add(o[1])
        res.append((o[1], o[2]))
    if not res:
        res = [("source unknown", None)]
    return res[:limit] if limit else res


def worn_items(world, carrying: str) -> dict:
    """Map 'You are carrying …' text to {slot: gear} for items marked (Worn)."""
    worn = {}
    names = {g["name"].lower(): g for g in world.gear.values()}
    from .gamestate import worn_list
    for item, _slot in worn_list(carrying):
        g = names.get(item.lower())
        if not g:
            continue
        slot = "Weapon" if int(g.get("ItemType") or 0) == 1 else WORN_SLOT.get(int(g.get("Worn") or 0))
        if slot in ("Finger", "Wrist"):
            slot = f"{slot} 1" if f"{slot} 1" not in worn else f"{slot} 2"
        if slot:
            worn[slot] = g
    return worn


@dataclass
class SlotResult:
    slot: str
    best: dict | None
    value: float
    current: dict | None
    current_value: float
    alts: list = field(default_factory=list)   # (gear, value)


def optimize(world, goal_key, ch: Char, current: dict | None = None, alts: int = 4):
    goal = GOALS[goal_key]
    cands = {}
    for g in world.gear.values():
        worn = int(g.get("Worn") or 0)
        if worn <= 0 or int(g.get("ItemType") or 0) == 1:
            continue
        slot = WORN_SLOT.get(worn)
        if not slot:
            continue
        ok, _why = usable(world, g, ch)
        if not ok:
            continue
        v = score(g, goal)
        if v <= 0:
            continue
        cands.setdefault(slot, []).append((g, v))
    results = []
    current = current or {}
    for slot in SLOTS:
        base = slot.split(" ")[0]
        lst = sorted(cands.get(base, []), key=lambda x: (-x[1], -ac(x[0]), x[0]["name"]))
        if slot.endswith("2"):
            # second ring/wrist: next best, or the same item again if it isn't limited
            first = lst[0][0] if lst else None
            if first is not None and int(first.get("Limit") or 0) == 0:
                pick = lst[:1]
            else:
                pick = lst[1:2]
            alt_list = lst[1:1 + alts]
        else:
            pick = lst[:1]
            alt_list = lst[1:1 + alts]
        best, val = (pick[0] if pick else (None, 0))
        cur = current.get(slot)
        results.append(SlotResult(slot, best, val, cur, score(cur, goal) if cur else 0, alt_list))
    return results


def slot_name(g) -> str:
    """Where an item goes: Head, Torso, Finger… or Weapon."""
    if int(g.get("ItemType") or 0) == 1:
        return "Weapon"
    return WORN_SLOT.get(int(g.get("Worn") or 0), "—") if int(g.get("Worn") or 0) > 0 else "Carried"


PRETTY = {"MaxMana": "Max mana", "ManaRgn": "Mana regen", "MaxHP": "Max HP", "HPRegen": "HP regen",
          "M.R.": "Magic resist", "Resist-Fire": "Resist fire", "Resist-Cold": "Resist cold",
          "Resist-Lightning": "Resist lightning", "Resist-Stone": "Resist stone", "Resist-Water": "Resist water"}
FLAG_ABILS = {28, 135, 136, 59, 97, 98, 112, 110, 111, 113, 43}


def item_stats(world, g) -> list:
    """Every stat on an item, for the full-stats window: [(section, label, value)]."""
    rows = [("Item", "Worn at", slot_name(g))]
    if int(g.get("ItemType") or 0) == 1:
        hands = "two-handed" if int(g.get("WeaponType") or 0) in (1, 3) else "one-handed"
        rows += [("Item", "Weapon", f"{WEAPON_TYPES.get(int(g.get('WeaponType') or 0), '?')} ({hands})"),
                 ("Item", "Damage", f"{g.get('Min')}-{g.get('Max')}"), ("Item", "Speed", g.get("Speed")),
                 ("Item", "Accuracy", f"{int(g.get('Accy') or 0):+d}")]
    else:
        at = int(g.get("ArmourType") or 0)
        rows.append(("Item", "Armour type", ARMOUR_TYPES.get(at, at)))
    rows += [("Defence", "AC", fmt(ac(g))), ("Defence", "DR", fmt(dr(g)))]
    for a, v in sorted(g["abils"].items()):
        if a in (2, 7) or a in FLAG_ABILS:
            continue
        nm = PRETTY.get(ABIL_NAMES.get(a, ""), ABIL_NAMES.get(a, f"abil {a}"))
        sec = "Resists" if nm.lower().startswith("resist") or a == 36 else "Bonuses"
        rows.append((sec, nm, f"{v:+d}"))
    ab = g["abils"]
    if 43 in ab:
        sp = (getattr(world, "spells", {}) or {}).get(ab[43]) or {}
        rows.append(("Bonuses", "Casts a spell", sp.get("Name") or sp.get("name") or f"spell #{ab[43]}"))
    if 28 in ab:
        rows.append(("Requires", "Magical", "yes (anti-magic classes can't use it)"))
    if 135 in ab:
        rows.append(("Requires", "Min level", ab[135]))
    if 136 in ab:
        rows.append(("Requires", "Max level", ab[136]))
    if int(g.get("StrReq") or 0):
        rows.append(("Requires", "Strength", g["StrReq"]))
    if 59 in ab:
        rows.append(("Requires", "Class OK", world.classes.get(ab[59], {}).get("Name", ab[59])))
    if g.get("classes"):
        rows.append(("Requires", "Classes", ", ".join(world.classes.get(c, {}).get("Name", str(c)) for c in g["classes"])))
    if g.get("races"):
        rows.append(("Requires", "Races", ", ".join(world.races.get(r, {}).get("Name", str(r)) for r in g["races"])))
    for a in (97, 98, 110, 111, 112, 113):
        if a in ab:
            rows.append(("Requires", ABIL_NAMES.get(a, f"abil {a}"), "yes"))
    if int(g.get("Encum") or 0):
        rows.append(("Other", "Weight (encum)", g["Encum"]))
    if int(g.get("Limit") or 0):
        rows.append(("Other", "Limited", f"{g['Limit']} in game"))
    if int(g.get("Price") or 0):
        cur = {0: "copper", 1: "silver", 2: "gold", 3: "platinum", 4: "runic"}.get(int(g.get("Currency") or 0), "")
        rows.append(("Other", "Price", f"{g['Price']} {cur}".strip()))
    return rows


def describe(world, g) -> str:
    bits = []
    if ac(g) or dr(g):
        bits.append(f"AC {fmt(ac(g))} / DR {fmt(dr(g))}")
    for a, v in sorted(g["abils"].items()):
        if a in (2, 7):
            continue
        nm = ABIL_NAMES.get(a, f"abil {a}")
        if a in (28, 135, 136, 59, 97, 98, 112, 110, 111, 113):
            if a == 135:
                bits.append(f"min level {v}")
            elif a == 28:
                bits.append("magical")
            elif a == 59:
                cl = world.classes.get(v, {}).get("Name", v)
                bits.append(f"class-ok {cl}")
            else:
                bits.append(nm)
            continue
        bits.append(f"{nm} {v:+d}")
    at = int(g.get("ArmourType") or 0)
    bits.append(f"{ARMOUR_TYPES.get(at, at)} armour")
    if int(g.get("Encum") or 0):
        bits.append(f"encum {g['Encum']}")
    if int(g.get("StrReq") or 0):
        bits.append(f"str {g['StrReq']}")
    if g.get("classes"):
        bits.append("classes: " + ", ".join(world.classes.get(c, {}).get("Name", str(c)) for c in g["classes"]))
    if g.get("races"):
        bits.append("races: " + ", ".join(world.races.get(r, {}).get("Name", str(r)) for r in g["races"]))
    if int(g.get("Limit") or 0):
        bits.append(f"limited ({g['Limit']} in game)")
    return " · ".join(bits)


# ---------------------------------------------------------------- weapons
WEAPON_TYPES = {0: "1H blunt", 1: "2H blunt", 2: "1H sharp", 3: "2H sharp"}
MAX_SWINGS = 5
HIT_MIN, HIT_CAP, DODGE_CAP = 8, 99, 95


def class_can_wield(world, g, cls: int) -> tuple[bool, str]:
    """MME's class weapon-type rule (ItemIsUsableByChar, ItemType 1)."""
    if not cls:
        return True, ""
    if g["abils"].get(59, 0) == cls or (g.get("classes") and cls in g["classes"]):
        return True, ""
    if g.get("classes"):
        return False, "class"
    cw = int(world.classes.get(cls, {}).get("WeaponType") or 0)
    wt = int(g.get("WeaponType") or 0)
    ok = {0: wt == 0, 1: wt == 1, 2: wt == 2, 3: wt == 3, 4: wt in (0, 2), 5: wt in (1, 3),
          6: wt >= 2, 7: wt <= 1, 8: True, 9: g["num"] in (68, 100)}.get(cw, True)
    return ok, "" if ok else f"class can't use {WEAPON_TYPES.get(wt, wt)}"


@dataclass
class Fighter:
    level: int = 38
    combat: int = 3            # class CombatLVL - 2
    agility: int = 60
    strength: int = 60
    encum_pct: int = 33
    accuracy: int = 0          # your accuracy without a weapon; 0 = ignore the target's AC / dodge
    crit: int = 0              # crit % from your other gear/class


@dataclass
class Swing:
    weapon: dict
    energy: int
    swings: float
    avg_hit: int
    avg_crit: int
    crit_pct: int
    hit_pct: int
    round_dmg: int
    note: str = ""


def energy_used(f: Fighter, speed: int, str_req: int) -> int:
    """MME CalcEnergyUsed."""
    base = int((((f.level * (f.combat + 2)) + 45) * (f.agility + 150)) / 6) or 1
    e = int((speed * 1000) / base)
    if f.strength and f.strength < str_req:
        e = int(((((str_req - f.strength) * 3) + 200) * e) / 200)
    if f.encum_pct >= 0:
        e = int((e * (int(f.encum_pct / 2) + 75)) / 100)
    return max(e, 1)


ATTACKS = ("normal", "bash", "smash")
# MME CalculateAttack, stock rules: damage x pre-roll (rounded down), then (dmg - DR) x multiplier; no crits; accuracy hit
ATTACK_MODS = {"bash": (1.1, 3, 15), "smash": (1.2, 5, 25)}


def attack_kind(cmd: str) -> str:
    """'bash {target}' / 'sm {target}' -> bash / smash; anything else is a normal attack."""
    w = (cmd or "").strip().split(" ", 1)[0].lower()
    return {"bash": "bash", "smash": "smash", "sm": "smash"}.get(w, "normal")


def weapon_round(g, f: Fighter, mon: dict | None = None, attack: str = "normal") -> Swing:
    """Average damage per round with a weapon (port of MME CalculateAttack, stock MajorMUD rules) for a normal
    attack, a bash (double energy a swing, x1.1 then x3, no crits, -15 accuracy) or a smash (one swing a round,
    x1.2 then x5, no crits, -25 accuracy). Weapon procs (casts-spell abilities) aren't counted."""
    ab = g["abils"]
    str_req = int(g.get("StrReq") or 0)
    if attack == "smash":
        e = 1000
    else:
        e = energy_used(f, int(g.get("Speed") or 0), str_req)
    crit = 0
    if attack == "normal":
        crit = f.crit + ab.get(58, 0)
        if f.strength >= str_req and e < 200 and f.encum_pct <= 66:   # quick & deadly
            qnd = min((200 - e) + int((f.agility - 50) / 10), 20)
            if f.encum_pct >= 33:
                qnd = int(qnd / 2)
            crit += max(qnd, 0)
        if crit > 40:
            crit = min(40 + int((crit - 40) / 3), 99)
    if attack == "bash":
        e *= 2
    e = max(e, 1)
    swings = min(round(1000 / e, 4), MAX_SWINGS)
    dmin, dmax = int(g.get("Min") or 0), int(g.get("Max") or 0) + ab.get(4, 0)
    dmin = min(dmin, dmax)
    dr = int(mon.get("dr", 0)) if mon else 0
    pre, mult, accy_pen = ATTACK_MODS.get(attack, (1, 1, 0))
    dmin, dmax = int(dmin * pre), int(dmax * pre)
    avg_crit = 0
    if crit > 0:
        avg_crit = max(round((dmax * 2 + dmax * 4) / 2) - dr, 0)
    dmin, dmax = max(int((dmin - dr) * mult), 0), max(int((dmax - dr) * mult), 0)
    avg_hit = round((dmin + dmax) / 2)
    hit = 100.0
    note = ""
    if mon and f.accuracy:
        accy = max(f.accuracy + int(g.get("Accy") or 0) - accy_pen, 8)
        ac_ = int(mon.get("ac", 0))
        acc_t = max((accy * accy) // 140, 1)
        hit = 100 - ((ac_ * ac_) // acc_t) if ac_ > 0 else 100
        hit = min(max(hit, HIT_MIN), HIT_CAP)
        dodge = int(mon.get("abils", {}).get(34, 0))
        if dodge > 0 and accy > 8:
            dg = min((dodge * 10) // max(accy >> 3, 1), DODGE_CAP)
            hit = hit * (1 - dg / 100)
    elif mon:
        note = "enter accuracy for hit chance"
    if 43 in ab:
        note = (note + "; " if note else "") + "casts a spell on hit (not counted)"
    c = crit / 100
    rnd = round(((1 - c) * avg_hit + c * avg_crit) * swings * hit / 100)
    return Swing(g, e, swings, avg_hit, avg_crit, crit, round(hit), rnd, note)


def best_weapons(world, ch: Char, f: Fighter, mon: dict | None = None, limit: int = 40) -> list:
    out = []
    for g in world.gear.values():
        if int(g.get("ItemType") or 0) != 1:
            continue
        if not g.get("In Game") and not ch.include_not_in_game:
            continue
        ok, _ = usable(world, dict(g, ItemType=1), Char(cls=0, race=ch.race, level=ch.level, align=ch.align,
                                                         strength=0, include_limited=ch.include_limited))
        if not ok:
            continue
        ok, _ = class_can_wield(world, g, ch.cls)
        if not ok:
            continue
        cl = world.classes.get(ch.cls, {})
        if ch.cls and 51 in {int(cl.get(f"Abil-{x}") or 0) for x in range(10)} and 28 in g["abils"]:
            continue    # anti-magic class
        sw = weapon_round(g, f, mon)
        if sw.round_dmg > 0:
            out.append(sw)
    out.sort(key=lambda s: (-s.round_dmg, s.weapon["name"]))
    return out[:limit]
