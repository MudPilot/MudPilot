"""Stall watchdog (pMUD): being hit in a fight but no attack of ours for 8 s → attack again; not while ours land."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
st.auto_combat = st.auto_nuke = True
st.multi_spell = ""
st.monster_spells = {"drooling geist": {"spell": "dfir", "variants": False}}
b.x.may_cast_attack = lambda: True
mobs = [("drooling geist", {"name": "drooling geist", "num": 1})]
g.in_combat = False
b.fight(mobs)                                     # arms dfir
check(f"first cast goes out ({sent})", any(c.startswith("dfir") for c in sent))
g.in_combat = True
now = time.time()
b._cast_sent_at = b._own_attack_at = now - 2
b._attacked_at = now
sent.clear(); b._cool.pop("cast", None)
b.fight(mobs)
check(f"attacks landing: no re-send ({sent})", not any(c.startswith("dfir") for c in sent))
b._cast_sent_at = b._own_attack_at = now - 10    # our spell went quiet, the geist still hits
b._attacked_at = now
sent.clear()
b.fight(mobs)
check(f"silent for 10 s while being hit: attacks again ({sent})", any(c.startswith("dfir") for c in sent))
b.note_line("You make a complex circling gesture!")
check("our own attack line is noticed", time.time() - b._own_attack_at < 1)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
