"""Ways MME's map doesn't have: learned from a MegaMUD path that walks them, and from walking them yourself."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
config.DATA_DIR = tempfile.mkdtemp()
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import MPath, Step, resolve_path
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
H = lambda k: w.room(k).mega_hash
check("MME alone: no way into the Crumbling Temple from the desert pyramid", w.route((12, 334), (12, 2459), level=47) is None)
steps = [Step(H((12, 333)), 0, "SW"), Step(H((12, 334)), 0, "SW"), Step(H((12, 335)), 0, "enter pyramid"),
         Step(H((12, 2224)), 0, "N"), Step(H((12, 2225)), 0, "N")]
mp = MPath("Desert to temple", "test", steps[0].hash, H((12, 2226)), steps=steps)
okr = resolve_path(w, mp, hint=(12, 333))
check(f"the MegaMUD path resolves anyway ({mp.resolve_note})", okr and steps[2].room == (12, 335) and steps[2].dest == (12, 2224))
r = w.route((12, 334), (12, 2226), level=47)
check(f"…and Go to can now use 'enter pyramid' ({[e.text_command or e.dir for e in r] if r else None})",
      r and any(e.text_command == "enter pyramid" for e in r))
# walking it yourself teaches it too
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
s = Session(st); s._no_log_file = True
learned = []
s.state.on_learn = [lambda a, c, b: learned.append((a, c, b))]
s.state.candidates = [(12, 335)]
s.state.note_command("crawl into the sand")
from mudpilot.ansi import Style
r2 = s.world.room((12, 2459))
s._line([(r2.name, Style())])
s._line([("Obvious exits: " + ", ".join({"NE": "northeast", "NW": "northwest", "SE": "southeast", "SW": "southwest"}[d]
                                         for d in r2.exits), Style())])
check(f"typed a command and landed somewhere MME has no way to → learned ({learned})",
      learned and learned[0] == ((12, 335), "crawl into the sand", (12, 2459)))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
