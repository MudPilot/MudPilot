"""0.8.190 (Dan, "fix both"): a wall or door opened from another room (a lever down the hall) cost every route a flat
12 rooms. It now costs the walk round to the action rooms and back at its real length (remembered): the Grand Stair's
south-east door (7/150, lever in 7/152) is 7 — what the Go to really walks — the mummy's gate (1/1056 N, two levers)
41, and one whose action rooms are themselves behind other remote walls (the Treetops 16/551, the 6/861 four-lever
puzzle) 100."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_lever_cost"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w = s.bot, s.world
gs = w.room((7, 150)).exits["SE"]
check(f"the Grand Stair door costs its walk round ({w.exit_cost(gs, (7, 150))})", w.exit_cost(gs, (7, 150)) == 7)
p = b.pilot
p.target, p.done, p.prog, p.pending = (7, 151), {}, {}, None
tour = p._build((7, 150)) or []
check(f"…which is what the Go to walks ({len(tour)} steps from 7/150)", abs(len(tour) - 7) <= 1)
mg = w.room((1, 1056)).exits["N"]
check(f"the mummy's gate, two levers: {w.exit_cost(mg, (1, 1056))}", 20 < w.exit_cost(mg, (1, 1056)) < 100)
for k, d in (((16, 551), "N"), ((6, 861), "D")):
    ex = w.room(k).exits[d]
    check(f"{k[0]}/{k[1]} {d}: behind other remote walls → {w.exit_cost(ex, k)}", w.exit_cost(ex, k) == 100)
check("remembered (one search per exit)", ((7, 150), "SE") in w._remote_costs)
check("no room to measure from: the old 12", w.exit_cost(gs) == 12)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
