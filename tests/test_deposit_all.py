"""0.8.227.6 (Dan, 2026-11-25): '@deposit-all' — the other player deposits all its cash in the bank it's standing in."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
s.send = lambda c, from_bot=False: sent.append(c)
g, r = s.state, s.remote
check("@deposit-all is a known command", "@deposit-all" in __import__("mudpilot.remote", fromlist=["x"]).COMMANDS)
bank = s.trips.banks()[0]
g.candidates = [(5, 5)]; g.view = type("V", (), {"name": "Main Street"})()
out = r.c_deposit_all("Miserable", "")
check(f"not in a bank: says so, deposits nothing ({out}, {sent})", "not in a bank" in out and not sent)
g.candidates = [bank]; g.view = type("V", (), {"name": "Bank"})()
out = r.c_deposit_all("Miserable", "")
check(f"in a bank: reads the pack first ({sent})", out is None and sent == ["i"])
g.wealth = 20500
r._inv_ask = [(q[0], q[1], q[2], q[3]) for q in r._inv_ask]
replies = []
r.reply = lambda *a, **k: replies.append(a)
for q in r._inv_ask:
    msg = q[2]()
check(f"…then deposits it all ({sent}, {msg})", "deposit 20500" in sent and "20,500" in msg)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
