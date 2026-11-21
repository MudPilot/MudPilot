"""Phoenix feather quest, route check (Dan, 2026-10-30: 'simulate a walk on the whole thing — direct routes, avoid the
vortex, most players are level 15'). Plans every leg the way Go to does for a party whose lowest member is level 15
and prints, per leg: steps, the areas it crosses, and anything a level-15 party can't take (vortex, level gates).

  python tests\\sim_phoenix.py            (not part of runall — a report, not a pass/fail test)"""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session

# the quest, from MME's textblocks (quest flag = ability 133)
LEGS = [   # (what, room, quest stage while walking there)
    ("start: Bank of Godfrey", (1, 297), 0),
    ("old man — ask phoenix (lvl 15+) → stage 1", (9, 1259), 0),
    ("dread mystic — kill → stage 2, yellowed note", (9, 930), 1),
    ("smuggler boss — kill → stage 3, smudged paper", (9, 223), 2),
    ("gnome alchemist — potion of levitation (10,000)", (6, 645), 3),
    ("Orfeo Talespinner — ask morukai → stage 4", (6, 126), 3),
    ("shadow guard — ask phoenix (opens Morukai's door)", (9, 1423), 4),
    ("Morukai — ask phoenix → stage 5", (9, 1425), 4),
    ("white jelly — kill → acid gland", (9, 146), 5),
    ("queen ant — kill → unfertilized eggs", (9, 717), 5),
    ("Earthy Cave — get roots → cave roots", (9, 500), 5),
    ("Morukai — ask components → stage 6; ask return → quartz rod, stage 7", (9, 1425), 5),
    ("necromancer (Amethyst Cave) — kill → golden egg", (9, 1431), 7),
    ("Morukai — ask information → stage 8, basalt key", (9, 1425), 7),
    ("Lake of Fire — throw egg → phoenix feather", (9, 1427), 8),
]
LOW = 15

st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b = s.world, s.bot
s.state.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
s.partysync.levels = lambda: {"Buddy": LOW, "Evolution": 20}
w.char = {**(w.char or {}), "party": True}
print(f"Routing level: {b.route_level()} (party's lowest)")


def areas(start, route):
    out = []
    for k in [start] + [e.to for e in route]:
        r = w.room(k)
        a = (r.name.split(",")[0].strip() if r else "?")
        if not out or out[-1][0] != a:
            out.append([a, 1])
        else:
            out[-1][1] += 1
    return " → ".join(f"{a}({n})" for a, n in out)


def flags(start, route):
    bad, cur = [], start
    for e in route:
        t = (e.etype or "").lower()
        if "vortex" in t or "vortex" in (getattr(e, "text_command", "") or "").lower():
            bad.append(f"VORTEX at {cur[0]}/{cur[1]}")
        m = w.LEVEL_RE.search(e.etype or "") if hasattr(w, "LEVEL_RE") else None
        if m and int(m.group(1)) > LOW:
            bad.append(f"level {m.group(1)}+ exit at {cur[0]}/{cur[1]} {e.dir}")
        if "teleport" in t:
            bad.append(f"teleport '{e.text_command or e.dir}' at {cur[0]}/{cur[1]}")
        cur = e.to
    return bad


total = 0
cur = LEGS[0][1]
stage = {"v": 0}
_abil = s.state.abil_value
s.state.abil_value = lambda a, kind="total": (stage["v"],) if a == 133 else _abil(a, kind)   # the session rebuilds world.char
for what, target, stg in LEGS[1:]:
    stage["v"] = stg
    for ex_ in (x for rm in w.rooms.values() for x in rm.exits.values() if hasattr(x, "_moves")):
        del ex_._moves                                      # (cached per character: the stage changed)
    r = w.room(target)
    route = b.plan_route(cur, target, None)
    how = "plain"
    if route is None:
        route = b.keyed_route(cur, target)
        how = "keys/doors"
    print(f"\n== {what}\n   {cur[0]}/{cur[1]} → {target[0]}/{target[1]} {r.name if r else '?'}")
    if route is None:
        bl = w.why_no_route(cur, target, level=b.route_level(), have=b.every_item(), avoid=b.avoid_set())
        print("   NO ROUTE — blocked by: " + "; ".join(f"{x[0][0]}/{x[0][1]} {x[1]}: {x[2]}" for x in bl))
        continue
    short = w.route(cur, target, have=b.every_item())          # no level / avoid / danger rules: the floor
    extra = (f" (shortest possible {len(short)})" if short is not None and len(short) < len(route) - 5 else "")
    print(f"   {len(route)} steps [{how}]{extra}")
    print("   " + areas(cur, route))
    for f in flags(cur, route):
        print("   !! " + f)
    total += len(route)
    cur = target
print(f"\nTotal: {total} steps")
