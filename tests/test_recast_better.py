"""Out of mana it settles for magic missile; the game then repeats that every round. Once the mana is back and the
picker wants magma blast again, switch — don't ride 35-damage rounds to the death (PVE, 2026-11-02). A similar
spell still isn't re-sent."""
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
sp = lambda short: next(v for v in w.spells.values() if (v.get("Short") or "").lower() == short)
mmis, magm, lbol = sp("mmis"), sp("magm"), sp("lbol") if any((v.get("Short") or "").lower() == "lbol" for v in w.spells.values()) else None
m1 = next(iter(w.monsters.values()))
s.state.view = RoomView("Rugged Shoreline", {"N"}, [(m1["name"], m1)], [], [], time.time())
s.state.max_ma, s.state.ma = 480, 2
b._cast_pick(mmis, 35, 0.9, "t", (m1["name"],), m1, "crab", 1)
check("out of mana: magic missile goes out", sent and sent[-1].startswith("mmis"))
s.state.in_combat = True
b._last_hit_at = time.time()
s.state.ma = 384
b._cool["cast"] = 0
n = len(sent)
b._cast_pick(mmis, 36, 0.9, "t", (m1["name"],), m1, "crab", 1)
check("the same spell isn't re-sent", len(sent) == n)
b._cast_pick(magm, 572, 1.02, "t", (m1["name"],), m1, "crab", 1)
check(f"mana back: magma blast replaces it ({sent[-1]})", len(sent) == n + 1 and sent[-1].startswith("magm"))
b._last_hit_at = time.time(); b._cool["cast"] = 0
n = len(sent)
b._cast_pick(magm, 572, 1.02, "t", (m1["name"],), m1, "crab", 1)
check("…and then left to repeat", len(sent) == n)
b._cast_pick(mmis, 400, 1.0, "t", (m1["name"],), m1, "crab", 1)   # (a near-equal choice)
check("a close second doesn't restart the fight", len(sent) == n)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
