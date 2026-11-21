"""PVE, 2026-10-28: hauling, 'You picked up 0 gold crown' over and over → leave the pile, read the inventory.
And 'pro' sent right behind 'st': "Lives/CP: 9/5" isn't a location (it walked east into a wall from '9/5')."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.loot_cash = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.candidates = [(13, 785)]
def look():
    g.view = RoomView("Jungle Trail", {"NE", "SW"}, [], [(1, "gold crown")], [], time.time())
    g.view_seq += 1
look()
b.loot()
check(f"gets the crown ({sent})", any(c.startswith("get") and "gold crown" in c for c in sent))
sent.clear()
b.note_line("You picked up 0 gold crown")
check(f"picked up 0 → reads the inventory ({sent})", "i" in sent)
b._loot_wait = None
sent.clear(); look(); b.loot()
check(f"…and leaves that pile alone ({sent})", not any("gold crown" in c for c in sent))
# Dark Pit, 2026-10-28: the room says "40 gold crowns" (plural), the answer "0 gold crown"
g.candidates = [(13, 790)]
b._loot_wait = None
def look2():
    g.view = RoomView("Dark Pit", set(), [], [(40, "gold crowns"), (9, "silver nobles")], [], time.time())
    g.view_seq += 1
look2(); sent.clear(); b.loot()
check(f"plural pile: gets it ({sent})", any("gold crowns" in c for c in sent))
b.note_line("You picked up 0 gold crown")
b._loot_wait = None
look2(); sent.clear(); b.loot()
check(f"…then leaves the crowns alone ({sent})", not any("gold crown" in c for c in sent))
# 'st' and 'pro' answers together
g.locate_until = time.time() + 5
g.candidates = [(13, 785), (13, 786)]
g._scan_locate("Name: Miserable Cunt                   Lives/CP:      9/5")
check("'Lives/CP: 9/5' isn't read as a room", g.locate_until > 0 and g.candidates != [(9, 5)])
g._scan_locate("10/21/2026 11:58 AM - buccaneer - 13/323")
check("…nor a death in the deaths list", g.candidates != [(13, 323)])
g._scan_locate("Location:            13,785")
check(f"'Location: 13,785' is ({g.candidates})", g.candidates == [(13, 785)])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
