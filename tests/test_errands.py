"""Go to Thrag without his keys: fetch the green metal key (slave-master) and large iron key (werewolf) first."""
import os, sys, time
os.environ["MUDPILOT_DEFAULT_BOARD"] = "Paradigm"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"; st.check_needed_items = True
s = Session(st); b = s.bot; w = s.world
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._want_connected = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
thrag = (1, 1810)
start = (1, 1789)
s.state.candidates = [start]; s.state.view = RoomView(w.room(start).name, set(w.room(start).exits))
s.state.carrying = "84 platinum pieces, skull mask (Face)"; s.state.keys = ""; s.state.level = 40
b._door_power_unknown = lambda *a: False; b._out_unknown = lambda *a: False   # (stats unread on purpose: keys get fetched; not the 0.8.222 'st' step)
b.goto(thrag)
a = b.errands.active
check(f"plans the keys first ({[t['what'] for t in a['todo']] if a else b.status})",
      a and {w.item_name(t["num"]) for t in a["todo"]} == {"green metal key", "large iron key"})
sent.clear(); b._cool = {}
b.errands.tick()
check(f"heads off to the first source ({b.status}; {b.path and b.path.title})", b.walking and b.path.title.startswith("Go to"))
# pretend we got both keys and are back
b.stop("x")
b.errands.active = a
s.state.keys = "green metal key, large iron key"
b._cool = {}
b.errands.tick()
check(f"with both keys → Go to Thrag ({b.path and b.path.title})", b.walking and b.path and "1810" in b.path.title)
# toll
toll = next(((k, d, e) for k, r in w.rooms.items() for d, e in r.exits.items() if e.kind == "toll" and "10000" in e.etype), None)
from mudpilot.megamud_files import path_from_route
k, d, e = toll
mp = path_from_route(w, k, [e], name="Toll test")
s.state.candidates = [k]; s.state.wealth = 500
b.start_path(mp, loop=False)
check(f"short of toll cash → won't walk ({b.status})", not b.walking and "toll" in b.status)
s.state.wealth = 50000
b.start_path(mp, loop=False)
check("enough cash → walks", b.walking)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
