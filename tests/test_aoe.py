"""Area-spell safety and 'already cast a spell this round'."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel(); s._entered = True
b = s.bot
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
s.state.party = {"Miserable": {}, "Revolution": {}}
s.state.view = RoomView("Town Gates", {"N"}, [], [], ["Revolution"], time.time())
check("only the party here → area spells fine", b.aoe_blocked() is None)
s.state.view = RoomView("Town Gates", {"N"}, [], [], ["Revolution", "Bob"], time.time())
st.pvp_realm = True
check("PvP realm: Bob (not in the party) here → no area spells", b.aoe_blocked() and "Bob" in b.aoe_blocked())
st.pvp_realm = False
check("PVE realm: Bob here doesn't stop them (0.8.75)", b.aoe_blocked() is None)
st.pvp_realm = True
s.state.view = RoomView("Town Gates", {"N"}, [], [], [], time.time() - 300)
check("stale room → no area spells", b.aoe_blocked())
s.state.view = RoomView("Town Gates", {"N"}, [], [], [], time.time())
b.x._party_broke_at = time.time()
check("party just broke → no area spells", b.aoe_blocked())
b.x._party_broke_at = 0
st.aoe_safety = False
s.state.view = RoomView("Town Gates", {"N"}, [], [], ["Bob"], time.time())
check("switch off → allowed", b.aoe_blocked() is None)
b.note_line("You have already cast a spell this round!")
check("'already cast this round' → holds the next cast", b._cast_block_until > time.time())
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
