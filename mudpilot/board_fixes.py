"""Ways through places MME's map gets wrong, from players who've walked them.

A *segment* is a fixed run of moves that must be walked as written (MME has shortcuts through doors that never
open). Any route that passes through a segment's rooms toward its end is made to follow it. A segment is only
used on a map where every one of its moves exists, so another board's MME data is never bent by it.

A *task* is something to do in a room before the route can go on (kill the floating key, pick up its key)."""
from __future__ import annotations

SEGMENTS = [
    {
        # Dan, 2026-10-27: the only way across level 3 of the Great Pyramid. MME's shortcuts (east from 12/2045,
        # south from 12/2048, east from 12/2044…) go through doors that never open from that side.
        "name": "Great Pyramid level 3 (golden lion key)",
        "start": (12, 2002),
        "moves": ["S", "E", "S", "S", "E", "E", "E", "E", "E", "N", "W", "N", "N", "W", "W",   # → 12/2005
                  "E", "S", "W", "W", "S", "E", "U"],                                          # → 12/2052
        "pre": {17: ["use lion key w"]},          # the key door west of 12/2034
        "key": 1175,                              # golden lion key
        "key_from": 15,                           # moves from here on need the key (it's got in 12/2005)
    },
    {
        # pMUD's Level 4 maze (Spell FOURTEEN). It comes back through 12/2052, so the right way on can't be told
        # from the room alone: progress through it is remembered (note_move) and a replan carries on from there.
        "name": "Great Pyramid level 4 maze",
        "start": (12, 2052),
        "moves": ["W", "W", "N", "N", "N", "N", "E", "E", "S", "W", "S", "S", "E", "S",     # back to 12/2052
                  "E", "E", "N", "N", "N", "W", "S", "U"],                                # → 12/2077
    },
]

# pMUD: of the pyramid's '[1000 picklocks/strength]' doors only these open by themselves (on a timer). The
# rest of them on levels 3-5 never open for us — except the ones on a walked-for-real segment above.
TIMED_DOORS = {((12, 2004), "N"), ((12, 2017), "E"), ((12, 2022), "S"), ((12, 2032), "S")}
SHUT_ZONE = (12, 2002, 2085)          # map, first and last room where the other 1000-doors count as shut

# exit commands MME's text gets wrong (pMUD's answers)
# Paradigm changed the top sphinx's answer: stock MajorMUD (and pMUD) say 'time', Paradigm's is 'E' (Dan: capital
# matters). MME's text has it lower-case.
EXIT_ACTIONS = {((12, 2085), "U"): ["ask sphinx E"]}

# items a party never routes on: Dan, 2026-10-28 — the amber talisman way into Dark-Elf City has you jumping
# roofs, likely to fall and break up the party; the Fungus Tunnel way needs no talisman
PARTY_SPLIT_ITEMS = ("amber talisman",)

# ways players prefer: a route that goes into `into` from outside goes through `via` first, if that's at most `slack`
# times as long (+20 rooms). Only on a board where both rooms carry these names.
# Dan, 2026-10-28: Dark-Elf City through the Fungus Tunnel (7/1405) — the planner's Dragon's Teeth Hills way
# was ~10 rooms shorter, but he wants this one.
VIA = [{"name": "Dark-Elf City via the Fungus Tunnel", "via": (7, 1405), "via_name": "fungus tunnel",
        "into": (8, 44), "into_name": "black cave", "slack": 1.25}]


def prefer_via(world, start, route, route_fn):
    """Re-route through a preferred room (VIA). route_fn(a, b) plans a leg. The route (possibly unchanged)."""
    for v in VIA:
        vr, ir = world.rooms.get(v["via"]), world.rooms.get(v["into"])
        if not vr or not ir or v["via_name"] not in vr.name.lower() or v["into_name"] not in ir.name.lower():
            continue
        if start == v["via"] or not any(ex.to == v["into"] for ex in route) or any(ex.to == v["via"] for ex in route):
            continue
        goal = route[-1].to
        a = route_fn(start, v["via"])
        b = route_fn(v["via"], goal) if a is not None else None
        if a is None or b is None or not any(ex.to == v["into"] for ex in b):
            continue
        if len(a) + len(b) <= len(route) * v["slack"] + 20:
            return a + b
    return route


# exits MME doesn't have: (room, dir) → (to, raw MME-style suffix, item every walker uses up on the way)
# Dan, 2026-10-28: into the Necromancer's catacombs — drink a potion of levitation in Mossy Cave, Waterfall
ADD_EXITS = {((3, 1), "U"): ((9, 1009), "(Text: use potion of levitation)", 992)}

PROGRESS_SECS = 900                   # forget how far through a segment we were after this long

TASKS = {
    (12, 2005): {
        "what": "get the golden lion key",
        "item": 1175, "item_name": "golden lion key", "get": "get golden lion key",
        "monster": "floating key", "melee": True,
        # it drops the key and is gone — miss it (it's whisked off to the desert) and stepping out and back
        # brings the floating key back
        "respawn": ["E", "W"],
    },
}


def is_paradigm(world, realm=None) -> bool:
    """These fixes were walked on Paradigm (pMUD): the board plays by Paradigm's rules (lair_camp.realm_of says so)
    or its MME data is Paradigm's ('data-Paradigm-1.9.1.mdb'). Stock shares the room numbers, so 'the rooms fit'
    alone applied them everywhere (0.8.201, bug hunt)."""
    return realm == "paradigm" or "paradigm" in str(getattr(world, "source", "") or "").lower()


def apply(world, realm=None) -> int:
    """Check each segment against this map; keep the ones that fit. Returns how many apply.
    realm: lair_camp.realm_of(session) — not Paradigm (and not Paradigm's MME data): nothing applies."""
    world.paradigm = is_paradigm(world, realm)
    if not world.paradigm:
        world.segments, world.room_tasks, world.seg_progress = [], {}, {}
        world.segment_exits, world.shut_doors, world.carry_exits = set(), set(), {}
        world.timed_doors = set()
        return 0
    ok = []
    for seg in SEGMENTS:
        cur = tuple(seg["start"])
        nodes, exits = [cur], []
        good = cur in world.rooms
        for mv in seg["moves"]:
            r = world.rooms.get(cur)
            ex = r.exits.get(mv) if r else None
            if ex is None:
                good = False
                break
            exits.append(ex)
            cur = ex.to
            nodes.append(cur)
        if good:
            ok.append({**seg, "nodes": nodes, "exits": exits})
    world.segments = ok
    world.room_tasks = {k: v for k, v in TASKS.items() if k in world.rooms} if ok else {}
    world.seg_progress = {}
    # 1000-strength doors that never open: shut for routing (timed ones and walked segments excepted)
    opens = {id(e) for seg in ok for e in seg["exits"]}
    world.segment_exits = set(opens)
    for room, d in TIMED_DOORS:
        e = (world.rooms.get(room).exits.get(d) if world.rooms.get(room) else None)
        if e is not None:
            opens.add(id(e))
    world.timed_doors = opens - world.segment_exits     # they open by themselves: not "nobody can open it" (0.8.201)
    mp, lo, hi = SHUT_ZONE
    world.shut_doors = {id(e) for (m, n), r in world.rooms.items() if m == mp and lo <= n <= hi
                        for e in r.exits.values()
                        if e.kind == "door" and "1000 picklocks" in (e.etype or "").lower() and id(e) not in opens}
    from .worlddb import parse_exit
    world.carry_exits = {}
    for (room, d), (to, raw, item) in ADD_EXITS.items():
        r = world.rooms.get(room)
        if r is None or to not in world.rooms:
            continue
        e = r.exits.get(d)
        if e is None:
            e = r.exits[d] = parse_exit(d, f"{to[0]}/{to[1]} {raw}")
        if e is not None and e.to == to and item:
            world.carry_exits[id(e)] = item
    for (room, d), cmds in EXIT_ACTIONS.items():
        e = world.rooms.get(room).exits.get(d) if world.rooms.get(room) else None
        for a in (getattr(e, "actions", None) or []):
            a["cmds"] = list(cmds)
    return len(ok)


def note_move(world, frm, to):
    """We walked frm → to: if that's a step of a segment, remember how far along it we are (a room the segment
    passes twice, like 12/2052 in the level 4 maze, then means 'the second time')."""
    import time
    for seg in getattr(world, "segments", None) or []:
        sn = seg["nodes"]
        steps = [p for p in range(len(sn) - 1) if sn[p] == frm and sn[p + 1] == to]
        if not steps:
            if to == sn[0] and frm not in sn:
                world.seg_progress.pop(seg["name"], None)   # (re)entering from outside: start over
            continue
        prog = _progress(world, seg)
        later = [p for p in steps if p >= prog - 1]
        world.seg_progress[seg["name"]] = ((later or steps)[0] + 1, time.time())


def _progress(world, seg) -> int:
    import time
    p, t = (getattr(world, "seg_progress", None) or {}).get(seg["name"], (0, 0))
    return p if time.time() - t < PROGRESS_SECS else 0


def splice(world, start, steps, have=None):
    """A route (list of exits from start) that crosses a segment toward its end follows the segment instead."""
    segs = getattr(world, "segments", None)
    if not segs or steps is None:
        return steps
    nodes = [tuple(start)] + [e.to for e in steps]
    for seg in segs:
        sn = seg["nodes"]
        tgt = nodes[-1]
        if tgt in sn[1:-1]:
            # going to a room inside the segment (the floating key's 12/2005): along the segment too
            pt = max(p for p, k in enumerate(sn) if k == tgt) if have and seg.get("key") in have else \
                min(p for p, k in enumerate(sn) if k == tgt)
            for i, k in enumerate(nodes[:-1]):
                pos = [p for p, kk in enumerate(sn) if kk == k and p < pt]
                if pos:
                    return list(steps[:i]) + list(seg["exits"][pos[0]:pt])
    for seg in segs:
        end = seg["nodes"][-1]
        if end not in nodes:
            continue
        j = nodes.index(end)
        have_key = bool(have and seg.get("key") in have)
        for i in range(j):
            if nodes[i] not in seg["nodes"]:
                continue
            pos = [p for p, k in enumerate(seg["nodes"][:-1]) if k == nodes[i]]
            prog = _progress(world, seg)
            pos = [p for p in pos if p >= prog] or pos      # a room it passes twice: carry on, don't start over
            if have_key:
                later = [p for p in pos if p >= seg.get("key_from", 0)]
                pos = later or pos
            p = pos[0]
            return list(steps[:i]) + list(seg["exits"][p:]) + list(steps[j:])
    return steps


def pre_for(world, room, ex):
    """Extra commands a segment wants before this exit ('use lion key w')."""
    for seg in getattr(world, "segments", None) or []:
        for p, e in enumerate(seg["exits"]):
            if e is ex and seg["nodes"][p] == room:
                return list(seg.get("pre", {}).get(p, []))
    return []
