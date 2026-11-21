"""Fresh start enters the realm at the MajorMUD menu; after a hang-up the next connect waits for you."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.username = "Miserable"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
    def connect(self, h, p): self.connected = True
s.telnet = T(); s._want_connected = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def menu():
    sent.clear(); s._line([("[MAJORMUD]: ", Style())])
s.connect("x", 23); menu()
check(f"fresh: enters ({sent})", sent == ["E"])
s.state.last_prompt = 0
s.safety.hangup("HP 100/674 below 25%")
s.connect("x", 23); menu()
check(f"after a low-HP hang-up: waits ({sent})", sent == [])
# you type E, get in → next drop comes back in by itself
import time
s.state.last_prompt = time.time() + 1; s.poll()
s.connect("x", 23); menu()
check(f"after you went back in: enters again ({sent})", sent == ["E"])
s.hangup_now()
s.connect("x", 23); menu()
check("after Alt+H: waits", sent == [])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
