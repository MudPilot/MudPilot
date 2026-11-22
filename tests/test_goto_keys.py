"""Go to when MudPilot hasn't seen your inventory yet: it reads it first (keys open the way), then
routes; with no way through it pops up why instead of sitting idle."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.char_level = 30
st.auto_get_items = False               # the case that sat idle: no fetching fallback
s = Session(st)
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
s.world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s.state.world = s.world
s._no_log_file = True
sent, popups = [], []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True; s.state.level = 30
s.state.picklocks, s.state.strength = 182, 60     # ('st' read: 0.8.222 reads it first before a picklocks door)
s.on_no_route = lambda m: popups.append(m)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w = s.world
key = next(n for n, it in w.items.items() if it.get("name", "").lower() == "green metal key")
check(f"green metal key is item #{key}", key)
s.state.candidates = [(1, 1810)]
check("goto accepted", s.bot.goto((17, 1637)))
check(f"reads the inventory first ({sent})", sent == ["i"])
s.state.carrying = "astral staff (Weapon Hand)"
s.state.keys = "green metal key, large iron key"
s.state.inv_seq += 1
s.bot.tick()
check(f"then walks ({s.bot.path and s.bot.path.title})", s.bot.walking and s.bot.path and s.bot.path.title.startswith("Go to"))
s.bot.stop("Stopped by you")
s.state.keys = ""
s.state.inv_seq += 1
sent.clear(); popups.clear()
# no key at all, nowhere to fetch it: walk anyway and pick/bash the door (it can be bashed from inside)
check("without the key: still goes (bash the door)", s.bot.goto((17, 1637)) and s.bot.walking)
check(f"…and says it'll pick/bash ({[l for l in s.logs if 'bash' in l][-1:]})", any("picking/bashing" in l for l in s.logs))
s.bot.stop("Stopped by you")
st.bash_key_doors = False
sent.clear(); popups.clear()
r = s.bot.goto((17, 1637))
check(f"bashing switched off → refuses and says why ({s.bot.status[:80]})", not s.bot.walking)
from mudpilot.diagnose import why_not_moving
why = why_not_moving(s)
check(f"diagnostics explain it ({why[-1][:80]})", any("green metal key" in x or "Not walking" in x for x in why))
# your settings: fetching on, but the key can't be fetched from here → walk and bash anyway
st.bash_key_doors = True; st.auto_get_items = True
s.bot.errands.plan = lambda mp, loop, need: (False, "no known source you can walk to")
s.bot.stop("Stopped by you")
check("fetching on, key unfetchable → still walks", s.bot.goto((17, 1637)) and s.bot.walking)
check("…logged why", any("walking anyway" in l or "picking/bashing" in l for l in s.logs[-3:]))
# sneak: monsters in the room (even peaceful) → don't try; after 'You may not sneak' → move on
from mudpilot.gamestate import RoomView
st.auto_sneak, st.sneak_mode, st.dont_move_unless_sneaking = True, "always", True
rec = next(m for m in w.monsters.values() if "kobold slave" in m["name"])
s.state.view = RoomView("Huge Cave", {"E", "NW"}, monsters=[("kobold slave", rec)]); s.state.view.t = time.time()
s.state.sneaking = False; st.auto_combat = False
sent.clear(); s.bot._cool = {"par": time.time(), "par_solo": time.time()}
for _ in range(3):
    s.state.pending.clear() if hasattr(s.state.pending, "clear") else None
    s.bot.tick()
check(f"no 'sn' spam with monsters here ({sent})", "sn" not in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
