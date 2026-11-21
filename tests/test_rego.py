"""Stop → Rego carries on (Go to + the loop after it, or the loop); a new loop resets exp/hr."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None
s = Session(st); b = s.bot; w = s.world
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="Loop A")
s.state.candidates = [(1, 3)]
s.state.exp_gained = 5000 if hasattr(s.state, "exp_gained") else None
b.start_path(lp, loop=True, checked=True)
check("loop started", b.walking)
b.stop("Stopped by you")
check("stopped, resume remembered", not b.walking and b.resume)
b.rego()
check("rego → same loop again", b.walking and b.path is lp)
b.stop("Stopped by you")
s.state.candidates = [(1, 1)]
b.goto((1, 16), then=lp)
b.stop("Stopped by you")
b.rego()
check(f"rego a Go to → Go to again, loop after ({b.path and b.path.title})",
      b.walking and b.path.title.startswith("Go to") and b.after_goto is lp)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
