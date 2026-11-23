"""0.8.225 (Dan): the Negative Power Plane is avoided under level 50 unless it's the only way; from level 50 it isn't
avoided by default (your own avoid list still counts)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda *a, **k: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, w = s.bot, s.world
npp = {k for k, r in w.rooms.items() if "negative power plane" in r.name.lower()}
st.char_level = 30; s.state.level = 30
check("level 30: NPP rooms are avoided", npp and npp <= set(b.avoid_set()))
st.char_level = 55; s.state.level = 55
check("level 55: NPP isn't avoided by default", not (npp & set(b.avoid_set())))
st.avoid_names = ["Negative Power Plane", "Webbed Hollow"]
check("level 55, NPP on the (shipped) avoid list: still not avoided", not (npp & set(b.avoid_set())))
check("under 50, the only way through NPP: goes", b._npp_only_ok("Negative Power Plane, Ruins"))
check("another avoided area isn't covered", not b._npp_only_ok("Black Wasteland"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
