"""Dan, 2026-11-08: Buddy couldn't pick his stashed raft back up — too much looted gold — and, half-ogre with low int,
can need 3 or 4 searches to find it. Drop coins (copper, silver, gold — never platinum/runic) right there till it fits,
and keep searching."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
sent = []
b.send = lambda c, **k: sent.append(c)
s.send = lambda c, **k: sent.append(c)
logs = []
b.log = lambda m, *a, **k: logs.append(m)
s.log = lambda m, *a, **k: logs.append(m)
LOOP = (17, 183)
g.candidates = [LOOP]
need = int(w.item_names["log raft"]["encum"])
st.raft_stash = {"room": list(LOOP), "items": ["log raft"], "t": time.time()}
g.carrying = "broadsword"
g.enc = (1000 - need // 2, 1000, "Heavy", 90)
g.coins = {"gold crown": 400, "platinum piece": 5}
check("follower @unstash: picking it up", s.remote.c_unstash("Evolution", "") is None and b.stash.busy())
def tick():
    if b.stash._job:
        b.stash._job["t"] = 0
    b.stash.tick()
tick()
check(f"search first ({sent})", sent == ["search"])
sent.clear(); tick()
check(f"too heavy: no get yet, coins first ({sent})", "get log raft" not in sent and "i" in sent)
check("…waiting on the drop", s.remote.making_room())
sent.clear(); s.remote.inv_answer()
check(f"…drops the gold, not the platinum ({sent})", any(x.startswith("drop 400 gold") for x in sent)
      and not any("platinum" in x for x in sent))
g.enc = (1000 - need - 50, 1000, "Medium", 50)
s.remote.inv_answer()
check("…room made", not s.remote.making_room())
sent.clear(); tick()
check(f"then the get ({sent})", sent == ["get log raft"])
# not found on the first three searches
for i in range(3):
    tick(); g.inv_seq += 1; tick(); tick(); tick()
check(f"still searching after 3 misses ({b.stash.busy()}, tries {b.stash._job and b.stash._job['tries']})",
      b.stash.busy() and st.raft_stash)
g.carrying = "broadsword, log raft"
for _ in range(6):
    if b.stash._job and b.stash._job.get("seq") is not None:
        g.inv_seq += 1
    tick()
check(f"4th search finds it: picked up ({logs[-1]})", not b.stash.busy() and not st.raft_stash
      and "Picked up the stashed log raft" in logs[-1])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
