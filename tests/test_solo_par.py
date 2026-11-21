"""Solo: once the game says 'You are not in a party', no more 'par' checks until there's party news."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_check_secs = 5
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
g.party, g.pending = {}, None

def par_sent():
    sent.clear()
    b._cool.pop("par", None); b._cool.pop("par_solo", None)
    b.party_tick()
    return "par" in sent

check("first check goes out", par_sent())
b.note_line("You are not in a party at the present time.")
check("solo: no more par, even long after", not par_sent())
b.note_line("You have invited Revolution to follow you.")
check("an invite brings the checks back", par_sent())
b.note_line("You are not in a party at the present time.")
b.note_line("Revolution has joined your travel party.")
check("someone joining does too", par_sent())
g.party = {"Miserable": {}, "Revolution": {}}
b._solo = True
check("a party in progress always checks", par_sent())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
