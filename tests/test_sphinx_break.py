"""Pyramid top, 2026-10-28: the stone sphinx (0 exp, 9999 HP) held combat, so the game repeated esto at it every
round. Nothing left to kill → break combat. Never a target, even with zero-exp skipping off."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
rec = s.world.monster_names["stone sphinx"]
g.candidates = [(12, 2085)]
g.view = RoomView("Great Pyramid", {"W", "U"}, [("stone sphinx", rec)], [], ["Revolution"], time.time()); g.view_seq += 1
b._aggro = {"stone sphinx": time.time()}            # it swung at us
check("sphinx never a target (it hit us)", b.attackable() == [])
st.skip_zero_exp = False
check("…even with zero-exp skipping off", b.attackable() == [])
g.in_combat = True
g.hp, g.max_hp, g.ma, g.max_ma = 650, 674, 300, 448
g.last_prompt = time.time()
b.tick()
check(f"in combat with only the sphinx: breaks off ({sent})", "bre" in sent and not any(c.startswith("esto") for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
