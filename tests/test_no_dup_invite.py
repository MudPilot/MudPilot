"""0.8.60: two parts deciding to invite the same member at once → one invite, one @join."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.send("invite Revolution", from_bot=True)
s.send("invite Revolution", from_bot=True)
check(f"one invite ({sent})", [x.lstrip('.') for x in sent].count("invite Revolution") == 1)
sent.clear(); s.send("/Revolution @join", from_bot=True); s.send("/Revolution @join", from_bot=True)
check("one @join", len(sent) <= 1)
sent.clear(); s.send("s", from_bot=True); s.send("s", from_bot=True)
check("moves aren't touched", sent.count("s") == 2)
sent.clear(); s.send("invite Revolution")
check("one you type always goes", any("invite Revolution" in x for x in sent))
s._party_sent = {k: t - 9 for k, t in s._party_sent.items()}
sent.clear(); s.send("invite Revolution", from_bot=True)
check("…and again after 8 s", any("invite Revolution" in x for x in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
