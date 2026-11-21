"""Evolution (Dan, 2026-11-03): asked 'pro' on a Go to to 2/873, and the echo of his own telepath to Buddy came back
first — "/Buddy {walking to Dragon's Teeth Hills (2/873)}" — taken as the board's answer: 'arrived', stopped 134
rooms short without a word. Chat lines are never the location."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
g = s.state
for line in ["/Buddy {walking to Dragon's Teeth Hills (2/873)}", "Buddy telepaths: @goto 2/873",
             "Revolution says \"meet at 2/873\"", "Buddy gossips: anyone at 2/873?"]:
    g.locate_until = time.time() + 10
    g.located = None
    g._scan_locate(line)
    check(f"not a location: {line}", g.located is None)
g.locate_until = time.time() + 10
g._scan_locate("Location: 1,1649")
check(f"the board's answer still counts ({g.located and g.located[0]})", g.located and g.located[0] == (1, 1649))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
