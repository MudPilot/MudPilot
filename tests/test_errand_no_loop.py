"""Buddy, 2026-11-04, in the desert without a waterskin: "'Go to 6/1335 General Store' needs waterskin (sold: Dwarven
General Store (6/1335)) — getting it first … Detouring to General Store (6/1335)" every 5 s, not moving. The errand's
own walk to the shop needed the very item it was going for, and planned a new errand. Now the errand's walk doesn't
count the items it's fetching."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.check_needed_items = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
b, e = s.bot, s.bot.errands
SKIN = s.world.item_names["waterskin"]["num"]
b.log = lambda m, *a, **k: None
b.missing_items = lambda mp: ([SKIN], [])
b.path_toll = lambda mp: 0
b.carry_sets = lambda mp: []
planned = []
e.plan = lambda mp, loop, hard: planned.append((mp.title, list(hard))) or (True, "")
def walk(title):
    mp = MPath(name=title, author="", start_hash="a", end_hash="b")
    mp.resolved = True
    try:
        b.start_path(mp, False)
    except Exception:
        pass                                         # (the walk itself needs a live game — only the check matters)
walk("Go to 6/1334 Bank of Khazarad")
check(f"no waterskin: an errand to get one ({planned})", planned and planned[0][1] == [SKIN])
planned.clear()
e.active = {"todo": [{"num": SKIN, "kind": "shop", "room": (6, 1335), "what": "sold"}], "then": (None, False),
            "started": time.time(), "at": None, "tries": 0}
walk("Go to 6/1335 General Store")
check(f"the errand's walk to the shop doesn't start another errand ({planned})", not planned)
# Dan: "by the time it gets there it no longer needs a waterskin so it really shouldn't even get one" — and when
# one IS needed while standing in the desert, the nearest (Nekojin's Village Store), not one on the way
s2 = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s2._no_log_file = True
s2.state.inv_at = float("inf")
b2, w2, g2 = s2.bot, s2.world, s2.state
b2.log = lambda m, *a, **k: None
g2.alignment = "Good"
desert = (12, 142)
g2.candidates = [desert]
route = b2.plan_route(desert, (6, 1334))
from mudpilot.automation import path_from_route
mp = path_from_route(w2, desert, route, name="Go to 6/1334 Bank of Khazarad")
check(f"walking out of the desert you're in: no waterskin needed ({b2.carry_sets(mp)})", b2.carry_sets(mp) == [])
g2.candidates = [(6, 1300)]
back = path_from_route(w2, (6, 1300), b2.plan_route((6, 1300), desert), name="Go to 12/142 Scorching Desert")
check("walking into it from outside: still needed", any(SKIN in c for c in b2.carry_sets(back)))
g2.candidates = [desert]
b2._goto_target = (6, 1334)
b2.errands.plan(mp, False, [SKIN])
got = b2.errands.active["todo"][0]["room"] if b2.errands.active else None
check(f"needed while in the desert: the nearest shop ({got})", got == (12, 49))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
