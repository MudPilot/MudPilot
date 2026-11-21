"""Dan, 2026-10-28: "prompted avoid" areas are default for everybody — Negative Power Plane and Black Wasteland
prompt before routing through, for any character, on top of whatever they add themselves."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# a character with an EMPTY avoid list still gets the built-in prompt areas
st = config.Settings(); st.save = lambda: None; st.avoid_names = []
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, w = s.bot, s.world
av = b.avoid_set()
has = lambda name: any(name in (w.room(k).name or "").lower() for k in av)
check("empty avoid list still prompts Negative Power Plane", has("negative power plane"))
check("empty avoid list still prompts Black Wasteland", has("black wasteland"))

# a character's own additions are merged in, not replaced
st2 = config.Settings(); st2.save = lambda: None; st2.avoid_names = ["Frozen Cavern"]
s2 = Session(st2, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s2._no_log_file = True
b2, w2 = s2.bot, s2.world
av2 = b2.avoid_set()
has2 = lambda name: any(name in (w2.room(k).name or "").lower() for k in av2)
check("own addition (Frozen Cavern) is included", has2("frozen cavern"))
check("…alongside the defaults", has2("black wasteland") and has2("negative power plane"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
