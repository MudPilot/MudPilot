"""Cheap hazard counters (0.8.201, Dan): "Hazard counters i like lets implement that without spending tons of cash…
I dont want to go buy a 20 runic item to minimize minimal damage."

A path that crosses rooms that hurt (freezing cold, magma heat, swamp / bog poison, ocean drowning…) can often be
walked unhurt with an item MME says negates that room spell (Items → NegateSpell): a sapphire ring or fur cape for
the cold, a magma amulet for the Volcano, swamp boots in the bog, a gnomish fish-helm under water. Rafts for the
rivers are a different thing — the room spell itself checks for one, so they're already a must-have (carry_needs).

Settings → Other → Routing → 'Rooms that hurt on the way…' (off by default) and a gold cap (default 300):
  * one you carry already → nothing to do;
  * worth it only when the damage it saves on this path is real: at least WORTH_PCT of your max HP (WORTH_MIN when
    max HP isn't known), counted over LOOP_LAPS laps on a loop, and no more than GOLD_PER_HP gold per HP saved;
  * only from a shop (never hunting a monster for it), never above the cap, and not a detour of more than
    DETOUR_MAX rooms; one item can cover several (swamp boots: swamp and bog);
  * with 'Missing one? Go get it first' on, the errand buys it on the way; otherwise (or over the cap) it just says
    which is the cheapest and where it's sold.
MudPilot doesn't put it on for you (that would swap out gear you chose): it says so when it's something to wear.
"""
from __future__ import annotations

import time

WORTH_PCT = 25           # % of max HP the path's damage must reach before a counter is worth buying
WORTH_MIN = 60           # …HP, when max HP isn't known
LOOP_LAPS = 5            # a loop crosses the same rooms every lap: counted over this many
GOLD_PER_HP = 10         # never more than this many gold per HP it saves
DETOUR_MAX = 60          # rooms out of the way to a shop that sells one
SAID_SECS = 1800         # one note per path and item this long
COPPER = (1, 10, 100, 10000, 1000000)


def counters(w, sp) -> list:
    """Items MME says stop room spell `sp` (NegateSpell) — gettable ones."""
    out = []
    for n in (getattr(w, "negates", {}) or {}).get(int(sp), []):
        it = (getattr(w, "items", {}) or {}).get(int(n)) or {}
        if it and it.get("gettable", 1) and int(n) not in out:
            out.append(int(n))
    return out


def path_damage(w, steps, skip_here=None) -> dict:
    """{room spell: (most damage over these steps, rooms)} for the room spells a counter could stop (not the ones a
    raft / waterskin is a must for — carry_needs has those). skip_here: the spell you're standing in — the way out of
    it can't be helped by a shop trip."""
    out = {}
    spells = getattr(w, "room_spells", {}) or {}
    skipping = skip_here is not None
    for s in steps:
        dest = getattr(s, "dest", None)
        sp = spells.get(tuple(dest)) if dest else None
        if skipping and sp == skip_here:
            continue
        skipping = False
        if not sp or w.spell_items(int(sp)):
            continue
        d = w.spell_damage(int(sp))
        if d <= 0:
            continue
        tot, n = out.get(sp, (0, 0))
        out[sp] = (tot + d, n + 1)
    return out


def shop_price(bot, num) -> int | None:
    """The cheapest a shop asks for item #num, in copper (None = no shop sells it)."""
    trips = getattr(bot.s, "trips", None)
    rows = []
    try:
        rows = trips.stocked_at(num) if trips is not None else []
    except Exception:
        rows = []
    if rows:
        return min(int(p) for _r, _sn, p in rows)
    return None


def advise(bot, mp) -> dict:
    """What to do about the rooms that hurt on `mp`: {"buy": [num], "notes": [str]}."""
    out = {"buy": [], "notes": []}
    cfg, st = bot.cfg, bot.st
    if not getattr(cfg, "hazard_counters", False) or not mp or not mp.steps:
        return out
    w = bot.s.world
    have = bot.held_items()
    if have is None:
        return out
    here = (mp.steps[0].room if mp.steps[0].room else None) or st.room
    dmg = path_damage(w, mp.steps, (getattr(w, "room_spells", {}) or {}).get(here) if here else None)
    if not dmg:
        return out
    laps = LOOP_LAPS if getattr(mp, "is_loop", False) and not mp.title.startswith("Go to ") else 1
    worth = (st.max_hp * WORTH_PCT / 100.0) if st.max_hp else WORTH_MIN
    cap = max(0, int(getattr(cfg, "hazard_counter_cap", 300) or 0)) * 100      # gold → copper
    open_ = {}                                       # spell → damage still to stop
    for sp, (tot, n) in dmg.items():
        cs = counters(w, sp)
        if not cs:
            continue
        mine = [c for c in cs if c in have]
        if mine:
            continue                                 # one you carry keeps it off already
        open_[sp] = tot * laps
    if not open_:
        return out
    # each counter: what it saves on this path (all the spells it stops) and its price
    cand = {}
    for sp in open_:
        for c in counters(w, sp):
            if c in cand:
                continue
            p = shop_price(bot, c)
            if p is None:
                continue                             # never hunted for: shops only
            cand[c] = p
    _nm = getattr(w, "item_name", None) or (lambda n: (w.items.get(n) or {}).get("name", f"item {n}"))
    nm = lambda n: (lambda x: x if x.endswith("s") else ("an " if x[:1].lower() in "aeiou" else "a ") + x)(_nm(n))
    spn = lambda sp: ((w.spells.get(int(sp)) or {}).get("Name") or f"room spell {sp}")
    left = dict(open_)
    toward = bot.errands._toward(mp) if hasattr(bot, "errands") else None
    auto = bool(getattr(cfg, "auto_get_items", True))
    while left and cand:
        saves = {c: sum(d for sp, d in left.items() if c in counters(w, sp)) for c in cand}
        ok = [(p, c) for c, p in cand.items() if saves[c] >= worth and p <= cap and p <= saves[c] * GOLD_PER_HP * 100]
        if not ok:
            # nothing cheap enough: say which would do and what it costs, once
            worthy = [(p, c) for c, p in cand.items() if saves[c] >= worth]
            if worthy:
                p, c = min(worthy)
                what = ", ".join(sorted({spn(sp) for sp in left if c in counters(w, sp)}))
                out["notes"].append(f"Rooms that hurt ahead ({what}, up to {saves[c]} damage"
                                    + (f" over {laps} laps" if laps > 1 else "") + f"): the cheapest thing that stops "
                                    f"it is {nm(c)} at {p // 100:,} gold — over the {cap // 100:,}-gold cap, not "
                                    "buying it")
            break
        p, c = min(ok)
        covered = [sp for sp in left if c in counters(w, sp)]
        what = ", ".join(sorted({spn(sp) for sp in covered}))
        src = None
        try:
            src = bot.errands.source_for(c, toward=toward) if hasattr(bot, "errands") else None
        except Exception:
            src = None
        detour = None
        if src and src.get("kind") in ("shop", "stash"):
            base = 0
            if here and toward and tuple(toward) != tuple(here):
                rt = w.route(tuple(here), tuple(toward), level=bot.route_level(), have=set(have))
                base = len(rt) if rt is not None else 0
            detour = max(0, int(src.get("dist") or 0) - base)
        where = (f"{w.room(src['room']).name if w.room(src['room']) else 'a shop'} ({src['room'][0]}/{src['room'][1]})"
                 if src and src.get("room") else "a shop")
        wear = int(((getattr(w, "gear", None) or {}).get(c) or {}).get("Worn") or 0)
        wear_note = " — wear it for the stretch (MudPilot won't swap your gear for it)" if wear else ""
        if detour is None or detour > DETOUR_MAX:
            out["notes"].append(f"Rooms that hurt ahead ({what}, up to {saves[c]} damage): {nm(c)} would stop it "
                                f"({p // 100:,} gold at {where}) — " + ("too far out of the way to fetch now"
                                                                         if detour is not None else
                                                                         "no shop in reach to buy one"))
        elif not auto:
            out["notes"].append(f"Rooms that hurt ahead ({what}, up to {saves[c]} damage): {nm(c)} would stop it — "
                                f"{p // 100:,} gold at {where}{wear_note}")
        else:
            out["buy"].append(c)
            out["notes"].append(f"Rooms that hurt ahead ({what}, up to {saves[c]} damage): buying {nm(c)} for "
                                f"{p // 100:,} gold at {where} on the way{wear_note}")
        for sp in covered:
            left.pop(sp, None)
        cand.pop(c, None)
    return out


def extra_buys(bot, mp) -> list:
    """The counters to fetch before walking `mp` (start_path adds them to the errand), saying why once."""
    try:
        adv = advise(bot, mp)
    except Exception as ex:
        bot.log(f"Hazard counters: couldn't work it out ({ex})")
        return []
    said = bot.__dict__.setdefault("_hazard_said", {})
    tried = bot.__dict__.setdefault("_hazard_tried", {})
    now = time.time()
    for n in adv["notes"]:
        key = (mp.title, n)
        if now - said.get(key, 0) > SAID_SECS:
            said[key] = now
            bot.log(n)
    out = []
    for c in adv["buy"]:
        n, t0 = tried.get(c, (0, 0))
        if now - t0 > SAID_SECS:
            n, t0 = 0, now
        if n >= 2:
            continue                                 # asked for twice lately (the 'i' re-read, then the errand) and
                                                     # still not carried — out of stock / no cash: not again yet
        tried[c] = (n + 1, t0)
        out.append(c)
    return out
