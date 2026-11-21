"""0.8.189 (realm walk sweep): from Kingsport the only way to Port Blackwater is the 2,000,000-copper 'secure passage to
port blackwater' boat. With 500,000 copper the 'no route' message said the passage "needs level 1+" — a level-55
character had no idea the fare was the problem. Now the fare and what you have are in it, and a level you have isn't."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot.worlddb import WorldDB
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
w.char = {"class": 5, "race": 1, "align": "Good", "abil": lambda a: None, "wealth": 500000, "tolls": True}
kit = {1281, 191}
check("Kingsport → the Blackwater bank: no way with 500,000 copper", w.route((14, 1), (14, 267), level=55, have=kit) is None)
why = w.why_no_route((14, 1), (14, 267), level=55, have=kit)
txt = "; ".join(x[2] for x in why)
fare = next((x for x in why if "secure passage" in x[1]), None)
check(f"the passage is what's in the way ({fare})", fare is not None)
check("…and it says the fare and what you have", fare and "2,000,000 copper" in fare[2] and "500,000" in fare[2])
check("…not a level you have", fare and "level 1+" not in fare[2])
w.char["wealth"] = 5000000
w.forget_routes()
r = w.route((14, 1), (14, 267), level=55, have=kit)
check(f"with 5,000,000 copper there's a way ({len(r) if r else None} rooms)", r is not None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
