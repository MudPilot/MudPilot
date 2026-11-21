"""Pyramid, 2026-10-28: 'use lion key w' through a closed door — the key once, 'open west', then walk.
(It used the key twice at once, walked into the shut door, and kept sending the crumbled key every retry.)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
room = (12, 2034)
g.candidates = [room]
g.view = RoomView("Great Pyramid", {"N", "S", "E", "W"}, [], [], ["Revolution"], time.time(), closed={"E", "W"}) \
    if "closed" in RoomView.__init__.__code__.co_varnames else RoomView("Great Pyramid", {"N", "S", "E", "W"}, [], [], ["Revolution"], time.time())
g.view.closed = {"E", "W"}
g.view_seq += 1
step = Step("X", 0, "W", ["use lion key w"], room, (12, 2048))
t = time.time()
check(f"closed door + key: uses the key, doesn't walk ({sent})", b._key_door(step, room, t) and sent == ["use lion key w"])
check("…and waits for the answer", b._key_door(step, room, t + 0.5) and sent == ["use lion key w"])
sent.clear()
b.note_line("You successfully unlocked the door.")
check(f"unlocked → 'open west' at once, before any step ({sent})", sent == ["open west"])
check(f"…and not again ({sent})", b._key_door(step, room, t + 1) is False and sent == ["open west"])
b.note_line("The door is now open.")
check(f"opened → walk on ({b._opened})", not b._key_door(step, room, t + 2) and b._opened[1] == "W")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
