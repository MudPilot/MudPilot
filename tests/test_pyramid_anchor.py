"""A Go to through look-alike rooms (Great Pyramid) is never 're-anchored' onto a later step by hash."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w = s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
mp = path_from_route(w, (12, 1811), w.route((12, 1811), (12, 2002), level=47), name="Go to 12/2002 Great Pyramid")
rooms_before = [x.room for x in mp.steps]
s.bot.path, s.bot.idx = mp, 0
on = {x.room for x in mp.steps}
h = {x.hash for x in mp.steps[50:]}
off = next(k for k, r in w.rooms.items() if k[0] == 12 and k not in on and r.mega_hash in h and r.name == "Great Pyramid")
s.state.candidates = [off]
check("off the path in a look-alike room: no jump by hash", not s.bot._anchor() and s.bot.idx == 0)
check("…and the path's rooms aren't rewritten", [x.room for x in mp.steps] == rooms_before)
s.state.candidates = [off, mp.steps[3].room]
check("not sure which room: only a step's own room counts", s.bot._index_for_current(0) == 3)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
