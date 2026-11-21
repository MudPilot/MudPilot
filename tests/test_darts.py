"""0.8.58: 'Darts …' (a pyramid level-2 room spell) isn't a player attacking you — no PvP hang-up."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.hangup_on_pvp = True; st.pvp_realm = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
for line in ["Darts shoot out of the walls and strike you for 22 damage!", "Darts fly out of the wall at you!",
             "Poison darts strike you for 12 damage!"]:
    feed(line)
    check(f"'{line}' → no hang-up", s.telnet.connected)
# the trap below the docks (Evolution hung up on 'Spikes' with Revolution and Buddy in the party, 2026-10-30)
s.state.party = {"Miserable": {}, "Revolution": {}, "Buddy": {}}
for line in ["Spikes shoot out and stab Revolution viciously!", "Spikes shoot out and stab Buddy viciously!"]:
    feed(line)
    check(f"'{line}' → no hang-up", s.telnet.connected and not s.safety._pvp_hang)
check("…not taken for a player attack", s.safety._party_victim("Spikes shoot out and stab Revolution viciously!") is None
      or s.safety.spell_line("Spikes shoot out and stab Revolution viciously!"))
s.state.party = {}
feed("Vexx hits you for 40 damage!")
check("a real player hitting you still hangs up", not s.telnet.connected)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
