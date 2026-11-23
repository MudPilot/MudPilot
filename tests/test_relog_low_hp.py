"""Back in after a low-HP hang-up, still under the line, in a quiet room: no second hang-up (Evolution, 2026-11-01:
the check judged the full HP from before the hang-up, armed itself, and the first real prompt — 38/208 — hung it up
again). Falling another 10% (something hitting you) still hangs up."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
st.hangup_low_hp, st.hangup_hp_pct = True, 25
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
hung = []
s.safety.hangup = lambda why: hung.append(why)
g = s.state
g.max_hp, g.hp = 208, 208                      # what we knew before the hang-up
g.max_hp_read = True                           # (the real max was read before the drop — 0.8.225 waits for 'st' otherwise)
s._connected_at = time.time(); s._entered = True
s.safety._was_in = False
s.safety.tick()
check("just reconnected, no HP prompt yet: nothing decided", not hung and not s.safety._was_in)
time.sleep(0.01)
s._line([("[HP=38/MA=40]:", Style())])         # the first real prompt
s.safety.tick()
check(f"back in at 18% in a quiet room: no hang-up ({hung})", not hung)
s._line([("[HP=12/MA=40]:", Style())])         # something's hitting us: another 10%+ down
s.safety.tick()
check(f"…but falling further still hangs up ({hung})", hung)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
