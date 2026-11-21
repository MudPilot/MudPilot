"""Needed items on paths, Go to arrival turns combat/nuke/rest/heal on, stop before boss rooms."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None
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
# an item exit (e.g. rope and grapple)
found = None
for k, r in w.rooms.items():
    for d, ex in r.exits.items():
        need = w.exit_need(ex)
        if need and not need[1] and ex.to in w.rooms and w.items.get(need[0]):
            found = (k, d, ex, need[0]); break
    if found: break
k, d, ex, num = found
item = w.item_name(num)
print("using", k, d, ex.etype, item)
mp = path_from_route(w, k, [ex], name="Needs test")
s.state.candidates = [k]
s.state.carrying = "84 platinum pieces, skull mask (Face)"; s.state.keys = ""
st.auto_get_items = False
b.start_path(mp, loop=False)
check(f"won't walk without the {item}", not b.walking and "need" in b.status.lower())
st.auto_get_items = True
b.start_path(mp, loop=False)
check(f"…or goes to get it first ({b.status})", b.errands.active or "can't fetch" in b.status)
b.stop("x")
s.state.carrying = f"84 platinum pieces, skull mask (Face), {item}"
b.start_path(mp, loop=False)
check(f"walks with the {item}", b.walking)
b.stop("x")
# inventory unknown → asks with i, then decides
s.state.carrying = ""; s.state.keys = ""
sent.clear(); b.start_path(mp, loop=False)
check("unknown inventory → sends i first", sent == ["i"] and not b.walking)
s.state.carrying = f"{item}"; s.state.inv_seq += 1
b.tick()
check("…then walks once it's read", b.walking)
b.stop("x")
# routing only through the item door when you have it
have = b.held_items()
check("route uses the item exit when held", w.route(k, ex.to, have=have) is not None)
# arrival turns things on
st.auto_combat = st.auto_nuke = st.auto_rest = st.auto_heal = False
s.state.candidates = [k]
mp2 = path_from_route(w, k, [ex], name=f"Go to {ex.to[0]}/{ex.to[1]}")
b.start_path(mp2, loop=False, checked=True)
b.idx = len(mp2.steps); s.state.pending.clear()
s.state.candidates = [ex.to]
b.walk([], False)
check("Go to arrived → combat, rest, heal on; nuke stays off (Dan, 2026-11-02)",
      st.auto_combat and not st.auto_nuke and st.auto_rest and st.auto_heal)
# boss room
br = w.bosses_by_room()
dest, bosses = next(iter(br.items()))
src = next((rk for rk, r in w.rooms.items() for dd, e in r.exits.items() if e.to == dest and e.kind == "normal"), None)
e2 = next(e for e in w.rooms[src].exits.values() if e.to == dest)
lp = path_from_route(w, src, [e2], name="Loop by the boss")
s.state.candidates = [src]; s.state.view = RoomView(w.room(src).name, set(w.room(src).exits))
b.start_path(lp, loop=True, checked=True); b.idx = 0
sent.clear(); s.state.pending.clear(); b.walk([], False)
check(f"stops before {bosses[0]['name']}'s room ({b.status})", not sent and "Stopped before" in b.status)
b.resume_boss(); sent.clear(); b.walk([], False)
check(f"Alt+R walks in ({sent})", sent and sent[-1] == e2.dir.lower())
b.stop("x"); st.boss_no_stop = [x["name"] for x in bosses]
b._boss_ok = None
b.start_path(lp, loop=True, checked=True); b.idx = 0
sent.clear(); s.state.pending.clear(); s.state.candidates = [src]; b.walk([], False)
check("unticked boss → walks straight in", sent and sent[-1] == e2.dir.lower())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
