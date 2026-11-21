"""0.8.181 (Dan, 2026-11-12: "standing at abandoned temple trying to goto lost city, it's trying to take me hundreds
of rooms out of the way… there's a way through earthen catacombs, requires golden idol which we have").
16/2273 E is '(Cast: post-857)': 'checkitem 1281:teleport 2431', else 2228. MME draws it to 2274, so it was thrown
out as a teleport. With the idol it's planned to where it really lands."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot.worlddb import WorldDB
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ic = (getattr(w, "item_casts", {}) or {}).get((16, 2273)) or []
check(f"the idol teleport is known ({[(e.to, sorted(i)) for e, i in ic]})",
      any(e.to == (16, 2431) and 1281 in i for e, i in ic))
r = w.route((16, 2273), (16, 2431), have={1281}, level=55)
check(f"with the idol: one step east ({len(r) if r is not None else None})", r is not None and len(r) == 1 and r[0].dir == "E")
r = w.route((16, 2273), (16, 2431), level=55)
check(f"without it: not that way ({len(r) if r is not None else None})", r is None or len(r) > 1)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
