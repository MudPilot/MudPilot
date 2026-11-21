"""The game repeats your attack spell each round: don't send it again mid-fight (area spell, or the
same monster still here) — it only toggles *Combat Off* / *Combat Engaged*."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w = s.bot, s.world
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
esto = next(v for v in w.spells.values() if (v.get("Short") or "").lower() == "esto")
m1 = next(iter(w.monsters.values())); m2 = list(w.monsters.values())[1]
s.state.view = RoomView("Rotting Glade, Trail", {"SE"}, [(m1["name"], m1), (m2["name"], m2)], [], [], time.time())
s.state.max_ma, s.state.ma = 473, 473
b._cast_pick(esto, 100, 1.0, "t", (m1["name"],), m1, "", 2)
check("first esto goes out", sent and sent[-1].startswith("esto"))
n = len(sent)
b._cast_pick(esto, 100, 1.0, "t", (m2["name"],), m2, "", 2)
check("…not again before *Combat Engaged*", len(sent) == n)
s.state.in_combat = True
b._cool["cast"] = 0
b._cast_pick(esto, 100, 1.0, "t", (m2["name"],), m2, "", 2)
check("…nor once engaged, though the picker's monster changed", len(sent) == n)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
