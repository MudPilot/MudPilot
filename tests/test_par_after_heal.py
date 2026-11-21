"""0.8.208: walking between fights, a party heal (or a member knocked down) still gets its fresh 'par' ~2 s later —
the 60 s walking backstop held it back and Revolution healed Miserable once every 15 s (Dan, 2026-11-19)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.party_check_secs = 5
st.party_heal = True; st.party_heal_pct = 90; st.party_heal_cmd = "grme"
s = Session(st); s._no_log_file = True
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
b.walking = True
g.party = {"Revolution": {"hp": 95, "t": time.time()}, "Miserable": {"hp": 77, "t": time.time()}}
g.pending = None
g.in_combat = False
b._cool["par"] = time.time() - 3
sent.clear(); b.party_tick()
check("walking, no fight, nobody hurt lately: no par", "par" not in sent)
b.slot_free = lambda: True
sent.clear(); healed = b.heal_tick()
check("Miserable at 77%: healed", healed and any(c.startswith("grme Miserable") for c in sent))
sent.clear(); b.party_tick()
check("…no par the same instant", "par" not in sent)
b._cool["par"] -= 3
sent.clear(); b.party_tick()
check("…a par ~2 s after the heal, though walking out of combat", "par" in sent)
b._par_soon_until = 0
b._cool["par"] = time.time() - 3
sent.clear(); b.party_tick()
check("window over: back to the 60 s backstop", "par" not in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
