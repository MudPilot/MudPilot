"""Buddy, 2026-10-29: Goto 'Guardian Golem-1 1797' → 'has no way in on MME's map — going to 1/662, the Small Room next to
it', and off through the sewers. 1/1797 is behind the green metal / large iron key doors: a keyed way in exists, so go
there (the key run / bash sorts the doors), never to a same-named room elsewhere."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b = s.bot
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


check("no twin for the guardian golem's room", b._reachable_twin((1, 662), (1, 1797)) is None)
check("…a keyed way in exists", b.keyed_route((1, 662), (1, 1797)) is not None)
# the King Crab case still works: 16/297 'Sandbar' has no way in at all
r = s.world.room((16, 297))
if r and not any(e.to == (16, 297) for rm in s.world.rooms.values() for e in rm.exits.values()):
    tw = b._reachable_twin((16, 287), (16, 297))
    check(f"a room nothing leads into still gets its twin ({tw and tw[0]})", tw is not None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
