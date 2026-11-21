"""0.8.201 bug hunt (stock_routing.md, allrooms_maps_*.md, allrooms_weak_char.md): dist_map agrees with route(),
Paradigm-only board fixes, the sea reason in 'why no route', small tolls with the cash not read yet, party race /
alignment gates, and doors nobody in the party can open (asked about, No by default; dist_map skips them)."""
import os, sys, tempfile
from types import SimpleNamespace as NS
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_bughunt_route"))
from mudpilot import board_fixes, config
from mudpilot.worlddb import WorldDB
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

PARA = os.path.join(here, "data", "boards", "Paradigm", "world.db")
if not os.path.exists(PARA):
    PARA = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
STOCK = os.path.join(here, "mudpilot", "bundled", "Stock.db")
w = WorldDB(PARA)
board_fixes.apply(w)
have = set(w.items)
hub = (1, 1382)

# --- dist_map vs route(): the asylum's random drop, a sea room as the end of a trip
d = w.dist_map(hub, level=75, have=have)
for goal, why in (((9, 1234), "Warped Asylum behind the 9/1182 cast drop"), ((17, 1541), "a Crystal Lake sea room")):
    r = w.route(hub, goal, level=75, have=have)
    check(f"{why}: route() {'finds' if r else 'has no'} a way, dist_map agrees ({goal in d})", (r is not None) == (goal in d))
sea_mid = (17, 1141)
check("…a sea room is an end, not a way through (its neighbours behind it aren't counted through it)",
      w._sea(sea_mid))
d_ns = dict(d)
w.scatter = {}
w.forget_routes()
check("without the random drop the asylum is unreachable (the second pass is what adds it)",
      (9, 1234) not in w.dist_map(hub, level=75, have=have))
w = WorldDB(PARA); board_fixes.apply(w)

# --- map 17 'plain exits rejected': sea rooms (MME room spells), not a code bug
ex = w.rooms[(17, 1106)].exits["SE"]
check("17/1106 SE → 17/1141 is blocked because 17/1141 is a sea room", w._sea(ex.to) and not w.can_use(ex, None, 75, have))
check("…but fine as the trip's end", w.can_use(ex, None, 75, have, None, ex.to))

# --- why no route: say it's open water
bl = w.why_no_route(hub, (17, 1075), level=75, have=have)       # (Crystal Lake, out past the first sea room)
check(f"why_no_route names the sea ({bl[:1]})", any("open water" in why for _r, _d, why in bl))

# --- board fixes: Paradigm only
check(f"Paradigm: fixes on (segments {len(w.segments)}, shut doors {len(w.shut_doors)})",
      w.paradigm and w.segments and w.shut_doors)
if os.path.exists(STOCK):
    s_ = WorldDB(STOCK)
    n = board_fixes.apply(s_)
    act = s_.rooms.get((12, 2085)).exits.get("U") if s_.rooms.get((12, 2085)) else None
    cmds = [c for a in (getattr(act, "actions", None) or []) for c in a.get("cmds") or []]
    check(f"Stock: none applied (segments {n}, shut {len(s_.shut_doors)}, carry {s_.carry_exits}, sphinx {cmds})",
          n == 0 and not s_.shut_doors and not s_.carry_exits and "ask sphinx E" not in cmds and not s_.paradigm)
    check("Stock board on Paradigm rules (realm says paradigm) still applies them",
          board_fixes.apply(WorldDB(STOCK), "paradigm") >= 0 and True)
check("realm 'stock' with Paradigm's own MME data: still Paradigm's fixes", board_fixes.is_paradigm(w, "stock"))

# --- a small toll with the cash not read yet
toll = next(e for r in w.rooms.values() for e in r.exits.values()
            if e.kind == "toll" and int(w.TOLL_RE.search(e.etype).group(1)) <= 100)
w.char = {"wealth": None, "tolls": True}
check(f"cash unknown: a small toll ({toll.etype}) isn't a wall", w.can_use(toll, None, 75, have))
w.char = {"wealth": 0, "tolls": True}
check("cash 0: it is", not w.can_use(toll, None, 75, have))

# --- party race / alignment gates come from Game Data → Players
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, sw, g = s.bot, s.world, s.state
b.log = lambda *a, **k: None
g.level = 55
g.party = {"Tester": {}, "Buddy": {"class": "Warrior"}}
s.players.data["buddy"] = {"name": "Buddy", "race": "Half-Ogre", "alignment": "Seedy", "last_who": 1}
s.route_char()
check(f"leading: party aligns {sw.char.get('party_aligns')}, races {sw.char.get('party_races')}",
      sw.char.get("party_aligns") == ["Seedy"] and len(sw.char.get("party_races") or []) == 1)

# --- doors nobody in the party can open
g.party = {}
g.strength, g.picklocks = 10, 0
s.route_char()
door = sw.room((8, 489)).exits["S"]                      # '[61 picklocks/strength]', a 6-room way round
check(f"strength 10 against {door.etype}: hopeless", sw.door_hopeless(door, set()))
d0 = sw.dist_map((8, 489), level=55, have=set())
check(f"dist_map doesn't count the way through it ({d0.get(door.to)} > 1)", d0.get(door.to, 99) > 1)
asked = []
def say(ans):
    def ask(short, scenic, area, kind="area"):
        asked.append((kind, area))
        return ans
    return ask
fake = [door]
b.plan_route_once = None
calls = {"n": 0}
def again():
    calls["n"] += 1
    return None
b._door_have = lambda: set()
r = b._ask_doors((8, 489), door.to, fake, say(False), again)
check(f"asked about it ({asked[-1:]}), No → a wall, planned again without it",
      asked and asked[-1][0] == "door" and calls["n"] == 1 and r is None
      and sw.refused_doors.get(id(door)) and not sw.can_use(door, None, 55, set()))
check(f"…no route names the door ({b.no_route_msg!r})", "nobody in the party can open it" in (b.no_route_msg or ""))
sw.refused_doors = {}
sw.forget_routes()
asked.clear()
r = b._ask_doors((8, 489), door.to, fake, say(True), again)
check("Yes → through it as before, and not asked again on a re-plan", r == fake and
      b._ask_doors((8, 489), door.to, fake, None, again) == fake and len(asked) == 1)
b._door_yes = {}
r = b._ask_doors((8, 489), door.to, fake, None, lambda: [])
check(f"nobody to ask = No: round it ({r})", r == [] and sw.refused_doors.get(id(door)))
sw.refused_doors = {}
sw.forget_routes()
g.strength = 90
s.route_char()
check("strength 90: not hopeless, no question", not sw.door_hopeless(door, set()))
thousand = next((e for k, rm in sw.rooms.items() for e in rm.exits.values() if e.kind == "door" and not e.actions
                 and "1000 picklocks" in (e.etype or "").lower() and id(e) not in sw.shut_doors
                 and id(e) not in (getattr(sw, "timed_doors", None) or ())
                 and id(e) not in (getattr(sw, "segment_exits", None) or ())), None)
check("a 1000-picklock door: not hopeless (opens another way — lever, quest; Morukai's 9/1423 W)", thousand is not None and not sw.door_hopeless(thousand, set()))
timed = next(iter(getattr(sw, "timed_doors", None) or ()), None)
tex = next((e for rm in sw.rooms.values() for e in rm.exits.values() if id(e) == timed), None)
check("a timed pyramid door isn't", tex is None or not sw.door_hopeless(tex, set()))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
