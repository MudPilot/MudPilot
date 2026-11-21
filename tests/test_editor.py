"""'train stats' / the character editor: the bot goes quiet until a room shows again."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.party_check_secs = 1
st.buffs = [{"name": "flux", "cast": "flux", "every": 2, "enabled": True, "op": ">=", "value": 0}]
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
    def connect(self, h, p): self.connected = True
s.telnet = T(); s.connect("x", 23)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
time.sleep(0.01)
feed("[HP=674/MA=467]:", "Ancient Keep, Throne Room", "Obvious exits: north")
s.state.max_hp = s.state.hp = 674
s.poll()
check("in the realm", s._entered)
s.send("train stats")
feed("/ P A R A D I G M      Char. Creation /    \\\\  ┌─    Point Cost Chart    ─┐")
sent.clear()
t0 = time.time()
while time.time() - t0 < 3:
    s.poll(); time.sleep(0.05)
check(f"nothing sent while in the editor ({sent})", sent == [])
feed("[HP=679/MA=467]:", "Ancient Keep, Throne Room", "Obvious exits: north")
t0 = time.time()
while time.time() - t0 < 2:
    s.poll(); time.sleep(0.05)
check(f"back in the realm → carries on ({sent[:4]})", s._entered and len(sent) > 0)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
