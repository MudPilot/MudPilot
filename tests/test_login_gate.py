"""Nothing game-side is sent at the BBS login; a failed login isn't retried."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.username = "miserable1"
st.buffs = [{"name": "flux", "cast": "flux", "every": 0, "enabled": True, "ability": "145", "op": ">=", "value": 5}]
st.abil_check_cmd = "abil"
s = Session(st); s.password = "secret"
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
    def connect(self, h, p): self.connected = True
s.telnet = T()
s.connect("x", 23)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s._line([("Welcome to the official Paradigm server!", Style())])
for _ in range(30):
    s.poll()
s._line([('Please enter your username or "new": ', Style())])
s.poll()
check(f"only the user name at the user prompt ({sent})", sent == ["miserable1"])
s._line([("Please enter your password: ", Style())]); s.poll()
check("then the password", sent[-1] == "secret")
for _ in range(30):
    s.poll()
check(f"no blesses/abil/par before entering the realm ({sent})", sent == ["miserable1", "secret"])
s._line([("Invalid username/password!", Style())])
s._line([('Please enter your username or "new": ', Style())]); s.poll()
s._line([("Please enter your password: ", Style())]); s.poll()
check(f"failed login isn't retried ({sent})", sent == ["miserable1", "secret"])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
