"""0.8.224: heal only above a mana % — one line in a fight, another out of one (Dan, 2026-11-22). Someone under
30% HP is healed whatever the mana; 0 = off."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.heal_cmd = "mihe"; st.heal_pct = 70; st.party_heal = True; st.party_heal_pct = 70; st.party_heal_cmd = "mihe {name}"
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
b.slot_free = lambda: True
b.early_in_round = lambda: True
g.max_hp, g.max_ma = 1000, 500
def go(hp, ma, fight, party=None):
    g.hp, g.ma, g.in_combat = hp, ma, fight
    g.party = party or {}
    b._cool.pop("heal", None); b._pheal_at.clear()
    sent.clear(); b.heal_tick()
    return list(sent)
check("0 = off: heals at 10% mana", go(600, 50, False) == ["mihe"])
st.heal_min_ma_rest, st.heal_min_ma_fight = 60, 15
check("out of a fight at 40% mana (line 60): no heal", go(600, 200, False) == [])
check("out of a fight at 70% mana: heals", go(600, 350, False) == ["mihe"])
check("in a fight at 40% mana (line 15): heals", go(600, 200, True) == ["mihe"])
check("in a fight at 10% mana: no heal", go(600, 50, True) == [])
check("under 30% HP: heals whatever the mana", go(250, 50, True) == ["mihe"])
t = time.time()
check("party member at 50%, mana under the line: not healed",
      go(1000, 200, False, {"Miserable": {"hp": 50, "t": t}}) == [])
check("party member at 20%: healed anyway",
      go(1000, 200, False, {"Miserable": {"hp": 20, "t": t}}) == ["mihe Miserable"])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
