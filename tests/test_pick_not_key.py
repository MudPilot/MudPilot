"""PVE, 2026-10-28: Go to the guardian golem fetched the green metal key ('Key: 475 [or any picklocks]') and the
large iron key with Picklocks 182, and picked up all 10 green keys. Good picklocks: no key run; errands take one."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
from mudpilot.megamud_files import Step, MPath
w = s.world
r = w.room((1, 1794)); ex = r.exits["E"]
mp = MPath("Go to 1/1797", "t", r.mega_hash, r.mega_hash, steps=[Step(r.mega_hash, 0, "E", [], (1, 1794), ex.to)])
st.bash_key_doors = False
check(f"Picklocks 0: the large iron key is a must ({b.path_needs(mp)})", b.path_needs(mp) == [(476, False)])
g.picklocks = 182
check(f"Picklocks 182: pick it instead ({b.path_needs(mp)})", b.path_needs(mp) == [(476, True)])
# 'st' sets it
g.picklocks = 0
for line in ("Mana: * 515/519   Spellcasting: 276    Traps:         157",
             "                                       Picklocks:     182"):
    g.feed_line([(line, None)])
check(f"'st' sets Picklocks ({g.picklocks})", g.picklocks == 182)
# errand loot: one key, not the pile
b.errands.wanted = lambda: {"green metal key"}
g.candidates = [(1, 1789)]
g.view = RoomView("Stone Chamber, Throne Room", {"N", "S", "W"}, [], [(10, "green metal key")], [], time.time()); g.view_seq += 1
b.carried_count = lambda n: 0
sent.clear(); b.loot()
check(f"errand loot takes one ({sent})", any("green metal key" in c for c in sent) and not any(c.startswith("get 10") for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
