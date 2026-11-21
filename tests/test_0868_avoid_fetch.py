"""0.8.168 (Miserable, 2026-11-09): standing in the Negative Power Plane (on his avoid list), a Go to the Pharaoh
said 'nobody in the party has a golden lion key, and there's no known place to get one' — the fetch kept out of
the avoided area it was standing in, so nothing was in reach. Like a Go to, a fetch from inside one walks out."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, er, w = s.bot, s.bot.errands, s.world
raft = w.item_names["log raft"]["num"]
pier = (1, 1813)                                    # the raft shop
start = next(k for k, d in sorted(w.dist_map(pier).items(), key=lambda kv: kv[1]) if d == 3 and k[0] == 1)
s.state.candidates = [start]
found = er.source_for(raft)
check(f"from the pier a raft is in reach ({found and found['what']})", found)
# the rooms round the pier are an avoided area, and we're standing in it
dm = w.dist_map(start)
area = frozenset(k for k, d in dm.items() if d <= 3)
b.avoid_set = lambda: area
got = er.source_for(raft)
check(f"standing in an avoided area: still finds it, walking out ({got and (got['what'], got['dist'])})",
      got and got["dist"] > 0)
s.state.candidates = [next(k for k, d in dm.items() if d == 6)]
far = er.source_for(raft)
check("…from outside it, a source inside the avoided area isn't used", not far or far["room"] not in area)

# Dan, 2026-11-09: he killed the floating key leading on PvP, and Revolution (following, idle in 12/2005) @'d him to
# hand the golden lion key over. A follower leaves the key to the leader (who asks a member that picks it up).
import time
from mudpilot.gamestate import RoomView
del b.avoid_set
s2sent = []
s.send = lambda c, from_bot=False: s2sent.append(c)
s.state.candidates = [(12, 2005)]
s.state.view = RoomView("Great Pyramid", {"N", "S", "E", "W"}, [], [], [], time.time()); s.state.view_seq += 1
b.walking, b.path = False, None
b._task_holder = ("Miserable", time.time())
b.x._following = "Miserable"
check(f"following: no room task, no @'ing the leader for the key ({s2sent})",
      not b._room_task(time.time()) and not s2sent)
b.x._following = None
b._task_holder = ("Revolution", time.time())
b.ready = lambda *a, **k: True
check(f"leading: asks the member who has it ({s2sent})",
      b._room_task(time.time()) and any("@do give golden lion key" in c for c in s2sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
