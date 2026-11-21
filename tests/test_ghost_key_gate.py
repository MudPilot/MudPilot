"""Revolution, 2026-10-30: '@goto bank of godfrey' from the Dark Corridor (8/494) — 'No walkable route … blocked by
the north exit of Town Gates, Archway (8/462): needs item #1'. MME has that gate as 'Key: 1 [or 31
picklocks/strength]' and there is no item #1: it's a bash/pick-only door, so plan through it and bash it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b = s.world, s.bot
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
check("item #1 isn't an item", 1 not in w.items)
check("…so it's a ghost key", 1 in w.ghost_keys())
check("planning with every key goes through the gate", 1 in b.every_item())
route = b.keyed_route((8, 494), (1, 297))
check("Dark Corridor → Bank of Godfrey has a route", route)
mp = path_from_route(w, (8, 494), route, name="t")
needs = dict(b.path_needs(mp))
check(f"the gate is a soft need (bash it) {needs.get(1)}", needs.get(1) is True)
# Dan: '@status' said just 'idle' — say what's jamming it up
b.no_route_msg = ("No walkable route from 8/494 to 1/297 — blocked by the north exit of Town Gates, Archway "
                  "(8/462): needs item #1")
st_txt = s.remote._activity()
check(f"@status says why ({st_txt})", st_txt.startswith("idle - No walkable route") and "8/462" in st_txt)
b.no_route_msg = ""
check("plain idle otherwise", s.remote._activity() == "idle")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
