"""Best regen gear from your own pack while you rest or meditate, and your fighting gear back after.

Dan, 2026-10-28: instead of Pre-rest / Post-rest command lines ("eq runed ca^Meq sparkl^Mremove platinum ring…")
MudPilot looks at what you're wearing and carrying (the 'i' list marks worn items "(Back)", "(Finger)"…), reads each
item's HPRegen / ManaRgn from MME, and for every slot puts on the best one for this rest:
  rest (HP short)        → most HP regen (sparkling pendant +20, white gold ring +25 — the faded shawl's −100 off)
  meditate (mana short)  → most mana regen (faded shawl +100, rainbow stone +20)
Your fighting set is whatever you had on when you sat down; it goes back on when you get up."""
from __future__ import annotations

import re

MULTI = {"finger": 2, "wrist": 2}          # slots you wear two of


def parse_carrying(text: str):
    """(worn {slot: [names]}, pack [names]) from "You are carrying … faded shawl (Back), platinum ring, …"."""
    worn, pack = {}, []
    for part in re.split(r",\s*", (text or "").replace("\r", " ").replace("\n", " ")):
        p = re.sub(r"\s+", " ", part).strip().rstrip(".")
        if not p:
            continue
        m = re.match(r"^(.+?)\s*\(([^)]+)\)$", p)
        if m:
            worn.setdefault(m.group(2).strip().lower(), []).append(m.group(1).strip().lower())
        elif not re.match(r"^\d+\s", p):            # '2 grey potion', '415 gold crowns': not gear
            pack.append(re.sub(r"^(?:an?|the|some)\s+", "", p, flags=re.I).lower())
        else:
            # '2 white gold ring': both are candidates (0.8.201, bug hunt). Potions and coins aren't gear — plan()
            # only keeps names MME has wearable gear for
            q, nm = p.split(" ", 1)
            pack += [nm.strip().lower()] * min(int(q), 2)
    return worn, pack


def _abils(world, name):
    num = next((n for n, it in world.items.items() if (it.get("name") or "").lower() == name), None)
    g = world.gear.get(num) if num is not None and getattr(world, "gear", None) else None
    return g


HP_REGEN, MANA_REGEN, MIN_LEVEL = 123, 145, 135     # MME ability numbers


def _val(g, *keys):
    ab = (g or {}).get("abils") or {}
    for k in keys:
        if k in ab:
            try:
                return float(ab[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def regen_score(g, w_hp, w_mana) -> float:
    """HP regen and mana regen, weighted by what this rest is for."""
    return w_hp * _val(g, HP_REGEN) + w_mana * _val(g, MANA_REGEN)


def plan(world, carrying: str, w_hp: float, w_mana: float, level: int | None = None, keep=()):
    """([commands to put the regen set on], [commands to put your fighting set back], [notes]).
    keep: worn items that must stay on (0.8.227.8: the phoenix feather in a room that sears you) — their slot is
    left alone."""
    keep = {str(n).strip().lower() for n in (keep or ()) if n}
    worn, pack = parse_carrying(carrying)
    gear = {}
    def g_of(n):
        if n not in gear:
            gear[n] = _abils(world, n)
        return gear[n]
    # which MME 'Worn' code goes in which slot: learnt from what you have on
    code_slot = {}
    for slot, names in worn.items():
        for n in names:
            g = g_of(n)
            if g and g.get("Worn") is not None:
                code_slot.setdefault(g.get("Worn"), slot)
    cands = {}
    for n in pack:
        g = g_of(n)
        if not g or g.get("Worn") not in code_slot:
            continue
        if level and int(_val(g, MIN_LEVEL)) > level:
            continue
        cands.setdefault(code_slot[g["Worn"]], []).append(n)
    pre, post, notes = [], [], []
    score = lambda n: regen_score(g_of(n), w_hp, w_mana)
    for slot, extra in cands.items():
        if slot in ("weapon hand", "worn", "everywhere", "nowhere"):
            continue                                     # never swap the weapon or quest trinkets
        have = list(worn.get(slot) or [])
        if keep and any(n.lower() in keep for n in have):
            continue                                     # it stops this room's damage: it stays on
        n_slots = MULTI.get(slot, 1)
        # 0.8.201, bug hunt: a list, not a set — two worn "platinum ring"s are two rings. The set collapsed them,
        # so the white gold ring looked like it went in a free finger: 'eq' into a full slot, then 'remove' it
        pool = sorted([(n, True) for n in have] + [(n, False) for n in extra], key=lambda e: (-score(e[0]), not e[1]))
        best = pool[:n_slots]
        on = [n for n, worn_ in best if not worn_]
        off = list(have)
        for n, worn_ in best:
            if worn_:
                off.remove(n)                            # this worn one stays on
        if not on or sum(score(n) for n, _w in best) <= sum(score(n) for n in have):
            continue
        free = max(0, n_slots - len(have))
        for a, b in zip(off, on):
            if n_slots > 1:
                pre += [f"remove {a}", f"eq {b}"]
                post += [f"remove {b}", f"eq {a}"]
            else:
                pre.append(f"eq {b}")
                post.append(f"eq {a}")
            notes.append(f"{b} for {a} ({slot}: {score(a):+g} → {score(b):+g})")
        for b in on[len(off):len(off) + free]:           # a free ring slot
            pre.append(f"eq {b}")
            post.append(f"remove {b}")
            notes.append(f"{b} ({slot}: {score(b):+g})")
    return pre, post, notes
