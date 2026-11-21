"""PVE, 2026-10-28: on the way to the bank it walked to the Blue Tower and typed 'ask Jorah portal/teleport' 8
times. That exit is gated (Ability 127 — a quest Miserable doesn't have); gates on typed commands count too."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
ex = w.room((1, 2327)).exits["@ask jorah teleport"]
w.char = {"abil": lambda a: 19 if a == 126 else None}
check("no ability 127: Jorah's teleport is closed", not w.can_use(ex))
w.char = {"abil": lambda a: 2 if a == 127 else None}
check("…with it, open", w.can_use(ex))
w.char = {"abil": lambda a: 19 if a == 126 else None}
r = w.route((1, 2326), (1, 155), level=55)
check(f"route doesn't use it ({[e.dir for e in r][:6] if r else r})", r is None or not any("jorah" in (e.dir or "").lower() for e in r))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
