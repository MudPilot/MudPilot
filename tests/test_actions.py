"""Hidden exits that need an action (MME's 'Action#1 [on the S exit of this room]: pull lever'):
imported, routed through, and the path types the action first. No route → it says what's in the way."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB, parse_action_note
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
d, room, act = parse_action_note("Action [on the S exit of this room]: rub bloodstone orb, rub orb (Item: 807)")
check("note parsed (dir, item)", d == "S" and act["item"] == 807 and act["cmds"][0] == "rub bloodstone orb")
d, room, act = parse_action_note("Action#2 [on the E exit of room 10/5]: push stone")
check("note for another room", room == (10, 5) and act["n"] == 2)
ex = w.rooms[(10, 4)].exits["S"]
check(f"lever exit knows its action ({ex.action_cmds()})", ex.action_cmds() == ["pull lever"])
rt = w.route((17, 1637), (1, 297), level=30, have=set())
check(f"Rotting Glade → Bank of Godfrey routes ({rt and len(rt)} steps)", rt)
mp = path_from_route(w, (17, 1637), rt, name="t")
st = next((s for s in mp.steps if s.room == (10, 4) and s.dest == (10, 3)), None)
check(f"…and pulls the lever first ({st and st.pre})", st and st.pre == ["pull lever"])
check("back the other way too", w.route((1, 297), (17, 1637), level=30, have=set()))
check("Brigand Chief reachable", w.route((17, 1637), (2, 9452), level=30, have=set()))
w.rooms[(10, 4)].exits["S"].actions = []
bl = w.why_no_route((17, 1637), (2, 9452), level=30, have=set())
check(f"no route → names the blocking exit ({bl})", bl and bl[0][0] == (10, 4) and bl[0][1] == "S")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
