"""0.8.140: walking with a party, 'par' only once combat is engaged (plus a 60 s backstop) — never between a
room and the next move, where it held the room back (Evolution's trace, 2026-11-01)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.party_check_secs = 5
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
sent = []
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
g.party, g.pending = {"Evolution": {}, "Buddy": {}}, None

def tick(ago=None):
    sent.clear()
    if ago is not None:
        b._cool["par"] = time.time() - ago
    b.party_tick()
    return "par" in sent

check("not walking: every 5 s as before", tick(6))
b.walking = True
check("walking, no fight: no par after 6 s", not tick(6))
check("…nor after 30 s", not tick(30))
check("…but the 60 s backstop goes out", tick(61))
g.in_combat = True
check("combat engaged: checks straight away (even 1 s after the last)", tick(1))
check("…not again at once", not tick(1))
check("long fight: every 5 s", tick(6))
g.in_combat = False
check("fight over, walking on: no par", not tick(6))
g.in_combat = True
check("next fight: checks again", tick(2))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
