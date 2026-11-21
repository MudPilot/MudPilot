"""Dan, 2026-10-28 (phoenix feather quest): the Caves of Chaos scatter the party without breaking it. The leader
notices a member who hasn't been with it for 30 s (and 3+ rooms), @wheres them, walks to them (no invite — they're
still in the party), then carries on with the trip."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, cb, w = s.state, s.bot, s.comeback, s.world
g.party = {"Miserable": {"t": time.time()}, "Revolution": {"t": time.time()}}
b.x._own_party = True
rooms = [(9, 1292), (9, 1293), (9, 1294), (9, 1295), (9, 1296)]
g.candidates = [rooms[0]]
class _Loop:                                        # '@loop x': the Go to's to the loop's start, then the loop
    title, filename, steps = "Caves loop", "", []
loop_after = _Loop()
b.goto((9, 1425), then=loop_after)                  # Morukai's lair
check(f"walking a Go to ({b.walking})", b.walking)
cb.last_seen = {"revolution": (rooms[0], time.time() - 40)}
for r in rooms:
    g.history.append(r)
g.candidates = [rooms[-1]]
sent.clear()
cb.tick()
check(f"30 s and 4 rooms without Revolution: @where ({sent})", "/Revolution @where" in sent)
check("…no invite while still in the party", cb.fetch and cb.fetch.get("no_invite") and not any(c.startswith("invite") for c in sent))
cb.answer("Revolution", "{Caves of Chaos - map 9 room 1293; exits: n, s}")
check(f"…going to get them ({cb.fetch and cb.fetch.get('room')})", cb.fetch and cb.fetch["room"] == (9, 1293))
g.candidates = [(9, 1293)]
b.walking = False
from mudpilot.gamestate import RoomView
g.view = RoomView("Caves of Chaos", {"N", "S"}, [], [], ["Revolution"], time.time())
cb.tick()
check(f"found them → carries on to Morukai ({b._goto_target})", cb.fetch is None and getattr(b, "_goto_target", None) == (9, 1425))
check(f"…and still loops when it gets there ({b.after_goto})", b.after_goto is loop_after)
# a member just a step behind isn't 'scattered'
cb.last_seen = {"revolution": (rooms[-2], time.time() - 40)}
g.candidates = [rooms[-1]]; b.walking = True; cb._scatter_asked = {}
sent.clear(); cb.tick()
check("a member a room behind isn't chased", "/Revolution @where" not in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
