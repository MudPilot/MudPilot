"""Dan, 2026-11-11, Dao Lord: Revolution's MudPilot sent @comeback 12/2251 for the room they were both in, then
re-joined a second later. The search was called off, but the Go to was still being worked out on the planner's
thread, so it went ahead anyway. Flung out to 12/335, it searched the whole map twice and popped up 'No walkable
route' for a walk Dan never asked for. Called off = it never starts; the popup is only for your own Go to."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_comeback = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, cb = s.bot, s.state, s.comeback
sent, pops = [], []
s.send = lambda c, from_bot=False: sent.append(c)
s.on_no_route = lambda m: pops.append(m)
class Tel:
    connected = False
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# 1. called off while it was still being planned: when the plan comes back, it doesn't set off
g.candidates = [(12, 335)]
g.view = RoomView("Pyramid", {"N"}, [], [], [], time.time()); g.view_seq += 1
b.call_off_goto((12, 2251), "Revolution is back — no need to go to 12/2251")
r = b.goto((12, 2251))
check(f"called off: the Go to doesn't go ({r}, walking {b.walking})", r is False and not b.walking)
check(f"…and no 'No route' popup ({pops})", not pops)

# 2. comeback re-joined: calls it off (not only a walk already under way)
b._called_off = None
cb.fetch = {"name": "Revolution", "phase": "going", "room": (12, 2251), "back": None, "t": time.time(), "searched": 1}
cb.missing = {"Revolution": {"t": time.time(), "why": "left behind"}}
b.walking = False
g.party = {"Miserable": {"t": time.time()}, "Revolution": {"t": time.time() + 1}}
cb.tick()
check(f"back in the party while still planning: called off ({b._called_off and b._called_off[0]})",
      b._called_off and b._called_off[0] == (12, 2251) and b.called_off((12, 2251)))

# 3. a Go to nobody you asked for, no way there: logged, no popup
b._called_off = None; pops.clear(); b._goto_by_user = None
b.goto((12, 2251))
check(f"not your Go to, no route: no popup ({len(pops)})", not pops)
# …your own: the popup
b._goto_by_user = ((12, 2251), time.time())
b.goto((12, 2251))
check(f"your own Go to, no route: the popup ({len(pops)})", len(pops) == 1)

# 4. @comeback for the room we're in: no walk
g.candidates = [(12, 2251)]
g.view = RoomView("Dao Lord", {"N"}, [], [], ["Revolution"], time.time()); g.view_seq += 1
g.party = {"Miserable": {}, "Revolution": {}}
started = []
b.goto = lambda *a, **k: started.append(a) or True
reply = s.remote.c_comeback("Revolution", "12/2251")
check(f"@comeback for the room we're both in: no Go to ({reply}, {started})", not started and "same room" in reply)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
