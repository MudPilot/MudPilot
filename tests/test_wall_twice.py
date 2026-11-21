"""PVE, 2026-10-28 (minotaur champion): 's' from 1/2104 — "There is no exit in that direction!" 16 times over two
Go tos (a hidden exit opened from another room). The second 'no exit' from a room we're sure of is a wall: go
round it, and the next Go to doesn't try it again."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent, logs = [], []
s.send = lambda c, from_bot=False: sent.append(c)
b.log = lambda m, *a, **k: logs.append(m)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.candidates = [(1, 2104)]
g.view = RoomView("Labyrinth Passage", {"E", "W"}, [], [], [], time.time()); g.view_seq += 1
b.walking = True
b.path = type("P", (), {"title": "Go to 1/2124 Minotaur", "steps": [], "is_loop": False})()
calls = []
b.route_around = lambda room, d, why: calls.append((room, d, why)) or True
b._resends = (((1, 2104), "s"), 0)
b.note_line("There is no exit in that direction!")
check("first 'no exit': not a wall yet (it may have been a miss)", not calls)
b._resends = (((1, 2104), "s"), 1)
b.note_line("There is no exit in that direction!")
check(f"second: a wall — going round it ({calls})", calls and calls[0][:2] == ((1, 2104), "S"))
w = s.world
check("…and it stays out of routes", ((1, 2104), "S") in (getattr(w, "walls", {}) or {}))
r = w.route((1, 2104), (1, 2124), level=55)
check(f"a Go to won't plan through it ({len(r) if r else r})", r is None or r[0].dir != "S")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
