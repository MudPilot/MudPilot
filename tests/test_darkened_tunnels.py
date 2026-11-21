"""0.8.213 (Dan, 2026-11-20): Buddy's Go to the Darkened Tunnels Throne Room (15/416) sat at 15/401 NE and 15/546 NW,
'1000 picklocks' gates from that side. The real way in: disarm the spell traps, pull the levers at 15/604 and 15/730,
and rush back to 15/477 N before it shuts (his FMASDRKT path)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
for st in [(15, 401), (15, 546), (7, 1283)]:
    r = w.route(st, (15, 416), level=41)
    check(f"{st[0]}/{st[1]} → Throne Room: no '1000' gate on the way", r and not any(w.one_way_door(e) for e in r))
    mp = path_from_route(w, st, r or [], "x")
    levers = [s.room for s in mp.steps if "pull lever" in (s.pre or [])]
    check(f"…walks to both levers ({levers}) and rushes the gate ({mp.rush})",
          set(levers) == {(15, 604), (15, 730)} and mp.rush and mp.rush[0]["room"] == (15, 477))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
