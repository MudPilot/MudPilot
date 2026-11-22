"""0.8.66: pyramid level 3 — Dan's way (MME's shortcuts go through doors that never open), the floating key
killed with melee in 12/2005, its golden lion key grabbed, and the key door west of 12/2034."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_spells = st.auto_bless = st.auto_rest = st.auto_heal = False; st.stop_before_boss = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
r = w.route((12, 2002), (12, 2052), level=47)
check("level 3 goes Dan's way", [e.dir for e in r] == "S E S S E E E E E N W N N W W E S W W S E U".split())
mp = path_from_route(w, (12, 2002), r, name="Go to 12/2052")
check("…with 'use lion key w' at the key door", any(x.move == "W" and "use lion key w" in x.pre for x in mp.steps))
r2 = w.route((12, 2041), (12, 2052), level=47)
check("re-planned from the middle of it: still Dan's way", [e.to for e in r2][:3] == [(12, 2040), (12, 2039), (12, 2038)])
# in 12/2005 on the way: kill the floating key (melee), grab the key, then on
b.start_path(mp, loop=False, checked=True); b._goto_target = (12, 2052)
b.idx = 15
g.candidates = [(12, 2005)]
feed("[HP=684/MA=473]:Great Pyramid", "Also here: floating key.", "Obvious exits: east, west")
g.candidates = [(12, 2005)]
fk = w.monsters[598]
check("floating key: melee only", b.monster_spell(fk) == "")
sent.clear(); b._cool.clear()
check("…the task holds the walk", b._room_task(time.time()))
check(f"…and attacks it by its whole name ({sent})", "a floating key" in sent)
feed("[HP=684/MA=473]:Great Pyramid", "You notice golden lion key here.", "Obvious exits: east, west")
g.candidates = [(12, 2005)]
sent.clear(); b._cool.clear()
b._room_task(time.time())
check(f"key on the floor: grabbed at once ({sent})", "get golden lion key" in sent)
# PVE live, 2026-10-28: the key on the floor and an undead priest in the room — it cast at the priest, the key vanished
feed("[HP=684/MA=473]:Great Pyramid", "You notice golden lion key here.", "Also here: fat undead priest.",
     "Obvious exits: east, west")
g.candidates = [(12, 2005)]
sent.clear(); b._cool.clear()
for _ in range(3):
    b.tick()
acts = [c for c in sent if c and c not in ("par", "")]
check(f"…before fighting the priest ({sent})", acts and acts[0] == "get golden lion key")
feed("You picked up golden lion key.")
check("picked up: the task's done", not b._room_task(time.time()))
b._picked_items = set()
feed("[HP=684/MA=473]:Great Pyramid", "Obvious exits: east, west")
g.candidates = [(12, 2005)]
b._task_state = {"t": time.time() - 10, "respawned": 0, "out": None}
sent.clear(); b._cool.clear()
b._room_task(time.time())
check(f"missed it: first makes sure it's the key room — every room looks alike ({sent})", sent == ["pro"])
b._locate_at = 0; sent.clear(); b._cool.clear()
b._room_task(time.time())
check(f"…then steps out east to bring it back ({sent})", "e" in sent)
# PVE live, 2026-10-28 23:11: a Go to 12/2005 ended right there — stood next to the floating key for minutes
b.walking, b.path = False, None
b._picked_items = set(); b._task_state = None
feed("[HP=684/MA=473]:Great Pyramid", "Also here: floating key.", "Obvious exits: east, west")
g.candidates = [(12, 2005)]
sent.clear(); b._cool.clear()
b._room_task(time.time())
check(f"Go to ended in the key room: attacks the floating key anyway ({sent})", "a floating key" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
