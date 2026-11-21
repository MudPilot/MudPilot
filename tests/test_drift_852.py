"""Overnight: a few forward resyncs after missed room displays aren't 'knocked off the path', and a second
drift with a certain room pauses and carries on instead of stopping for the night."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
w, b, g = s.world, s.bot, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
mp = path_from_route(w, (12, 1811), w.route((12, 1811), (12, 2002), level=47), name="Go to 12/2002 x")
b.start_path(mp, loop=False, checked=True)
b._drift = []
for k in range(10):
    b.idx = k * 3
    j = k * 3 + 3
    g.candidates = [mp.steps[j].room]
    old = b.idx
    n_ = len(mp.steps)
    ahead = (j - old) % n_
    if not (0 < ahead <= 5):
        b._drifted("resync")
check("ten small forward resyncs: no drift counted", len(getattr(b, "_drift", [])) == 0)
g.candidates = [(12, 1811)]
b._drift = [(time.time(), "resync", None)] * 7
b._drift_warned = time.time()
stopped = []
b.stop = lambda why="": stopped.append(why)
check("second drift, room certain: pause and carry on (no stop)", b._drifted("resync") and not stopped and "drift" in b.holds)
b._drift = [(time.time(), "resync", None)] * 7
b._drifted("resync")
check("…a third within 5 min does stop", stopped)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
