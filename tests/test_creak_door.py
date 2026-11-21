"""Pyramid level 3, 2026-10-28: 'Doors on this level creak and thump!' made every door there a timer door —
12/2046's east door got 'e' over and over; Dan bashed it by hand. Wait ~5 s for it, then bash."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b = s.bot
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
r = s.world.room((12, 2046))
d = "E"                                  # plain (Door); N and W are [1000 picklocks] timer doors
print("door dirs", {k: (e.kind, e.etype) for k, e in r.exits.items()})
b.note_line("Doors on this level creak and thump!")
b._lock_room, b._lock_tries = (12, 2046), {}
res = [b._timed_door((12, 2046), d) for _ in range(8)]
check(f"creak level, a plain door you can pick or bash: tried at once, no waiting ({res})", not any(res))
check("…the [1000 picklocks] north door still just waits", all(b._timed_door((12, 2046), "N") for _ in range(8)))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
