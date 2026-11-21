"""Item spells as commands, like MegaMUD's: '#etc' casts the emerald-tipped crozier's spell.

Any item that casts a spell with unlimited uses (MME UseCount -1, or 9999) gets a command: '#' and the first letter
of each word of its name — emerald-tipped crozier → #etc, large silvery cross → #lsc. Use it wherever a spell goes
(heal, attack, bless, a typed command: '#etc', '#lsc orc'). Wands and other limited-use items don't get one.

MudPilot does the swapping MegaMUD needed a pile of message responses for. Dan's priest, scepter in hand and cross
off-hand, casting with the two-handed crozier:
    remove large silvery cross · eq emerald-tipped crozier · use emerald-tipped crozier
    eq amber scepter · eq large silvery cross
Only the off-hand item has to come off: equipping the crozier swaps the weapon by itself. Already holding it? Just
'use'. Another slot (an amulet, a ring): equip it, use it, then put back whatever was there."""
from __future__ import annotations

import re

from .gamestate import parse_item_list, worn_list, wielded

UNLIMITED = 9999          # MME's "as good as unlimited" use count
WEAPON, OFF_HAND = 1, 12  # MME 'Worn' slots
TWO_HANDED = (1, 3)       # MME WeaponType: two-handed blunt / sharp


def alias(name: str) -> str:
    return "#" + "".join(w[0] for w in re.split(r"[\s-]+", (name or "").lower()) if w)


def table(world) -> dict:
    """{'#etc': [gear, …]} — every unlimited-use item spell (initials can be shared: '#ss' is four items)."""
    gear = getattr(world, "gear", None) or {}
    c = getattr(world, "_item_spells", None)
    if c is not None and c[0] is gear:
        return c[1]
    out = {}
    for g in gear.values():
        uses = int(g.get("UseCount") or 0)
        if 43 in (g.get("abils") or {}) and (uses < 0 or uses >= UNLIMITED) and g.get("name"):
            out.setdefault(alias(g["name"]), []).append(g)
    world._item_spells = (gear, out)
    return out


def _carried(carrying) -> list:
    return [re.sub(r"\s*\([^)]*\)\s*$", "", n).strip() for _q, n in parse_item_list(carrying or "")]


def pick(world, al: str, carrying: str = ""):
    """The item behind '#etc': the one you carry if several share the initials."""
    items = table(world).get((al or "").lower())
    if not items:
        return None
    have = {n.lower() for n in _carried(carrying)}
    return next((g for g in items if g["name"].lower() in have), items[0])


def carried(world, carrying: str) -> list:
    """[(alias, spell name, item)] for the item spells in your pack."""
    have = {n.lower() for n in _carried(carrying)}
    out = []
    for al, items in sorted(table(world).items()):
        for g in items:
            if g["name"].lower() in have:
                sp = (getattr(world, "spells", {}) or {}).get(int(g["abils"][43])) or {}
                out.append((al, sp.get("Name") or "?", g["name"]))
                break
    return out


def spell_for(world, al: str, carrying: str = ""):
    """The spell record '#etc' casts, with Short set to the alias (so spell lists, heals and the damage
    calculator treat it like any spell)."""
    g = pick(world, al, carrying)
    if not g:
        return None
    sp = (getattr(world, "spells", {}) or {}).get(int(g["abils"][43]))
    return {**sp, "Short": al.lower(), "item": g["name"]} if sp else None


def expand(world, cmd: str, carrying: str = "") -> list | None:
    """'#etc [target]' → the commands to send, or None if it isn't an item spell."""
    m = re.match(r"^\s*(#[a-z]+)(?:\s+(.*?))?\s*$", cmd or "", re.I)
    if not m:
        return None
    g = pick(world, m.group(1), carrying)
    if not g:
        return None
    item, tgt = g["name"], (m.group(2) or "").strip()
    use = f"use {item}" + (f" {tgt}" if tgt else "")
    worn = worn_list(carrying or "")
    if any(n.lower() == item.lower() for n, _s in worn):
        return [use]                                  # already wearing / holding it
    gear = getattr(world, "gear", {}) or {}
    by_name = {x.get("name", "").lower(): x for x in gear.values()}
    slot = int(g.get("Worn") or 0)
    off = next((n for n, s in worn if "off" in s.lower()), "")
    pre, post = [], []
    if slot == WEAPON:
        wpn = wielded(carrying or "")
        if int(g.get("WeaponType") or 0) in TWO_HANDED and off:
            pre.append(f"remove {off}")              # a two-hander won't go on over an off-hand item
        pre.append(f"eq {item}")
        if wpn:
            post.append(f"eq {wpn}")                 # the weapon first: the off-hand needs a free hand
        if pre[0].startswith("remove "):
            post.append(f"eq {off}")
    elif slot:
        was = off if slot == OFF_HAND else next(
            (n for n, _s in worn if int((by_name.get(n.lower()) or {}).get("Worn") or 0) == slot), "")
        wpn = wielded(carrying or "")
        wx = by_name.get(wpn.lower()) if wpn else None
        two = slot == OFF_HAND and wx and int(wx.get("WeaponType") or 0) in TWO_HANDED
        if two:
            pre.append(f"remove {wpn}")              # holding a two-hander: free a hand for the off-hand item
        pre.append(f"eq {item}")
        post.append(f"eq {was}" if was else f"remove {item}")
        if two:
            post.append(f"eq {wpn}")
    else:
        return [use]
    return pre + [use] + post
