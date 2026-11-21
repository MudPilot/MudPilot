"""Dan, 2026-11-05: "have the party stash the log rafts at the start of the loop then grabbing them and reusing rather
than rebuying. Rafts are heavy." — and if they've gone missing, buy new ones as before."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
sent = []
b.send = lambda c, **k: sent.append(c)
s.send = lambda c, **k: sent.append(c)
b.log = lambda m, *a, **k: None
RAFT = w.item_names["log raft"]["num"]
check(f"boats: the log raft and the rest ({[w.item_name(n) for n in sorted(b.stash.boats())]})",
      RAFT in b.stash.boats() and len(b.stash.boats()) >= 2)
LOOP = (3, 560)
g.candidates = [LOOP]
g.carrying = "log raft, broadsword"
g.party = {"Buddy": {}, "Revolution": {}}
s.comeback.leading = lambda: True
mp = MPath(name="Ruins loop", author="", start_hash="a", end_hash="b")
b.carry_sets = lambda m: []
def run(job_ticks=12):
    for _ in range(job_ticks):
        if b.stash._job:
            b.stash._job["t"] = 0
        b.stash.tick()
check("a loop that doesn't cross water: stashing", b.stash.on_loop(mp))
check(f"…the party told @stash ({sent})", "/Revolution @stash raft" in sent)
sent.clear()
b.stash.tick(); b.stash._job["t"] = 0; b.stash.tick(); b.stash._job["t"] = 0
check(f"hide it, then 'i' ({sent})", sent[:2] == ["hide log raft", "i"])
g.carrying = "broadsword"; g.inv_seq += 1
b.stash.tick()
check(f"out of the pack: remembered ({st.raft_stash})", st.raft_stash.get("items") == ["log raft"]
      and tuple(st.raft_stash["room"]) == LOOP)
b.carry_sets = lambda m: [frozenset(b.stash.boats())]
check("a loop that crosses water keeps them", not b.stash.on_loop(mp))
# leaving: the stash is where it comes from, not the shop
src = b.errands.source_for(RAFT)
check(f"the raft's source: the stash ({src and src['what']})", src and src["kind"] == "stash" and src["room"] == LOOP)
go = MPath(name="Go to 1/1813 Pier", author="", start_hash="a", end_hash="b")
b.errands.active = {"todo": [dict(src)], "then": (go, False), "started": time.time(), "at": None, "tries": 0}
b.walking = False
sent.clear()
b.errands.tick()
check(f"at the stash: the party told @unstash ({sent})", "/Revolution @unstash" in sent)
b.stash._job["t"] = 0; b.stash.tick(); b.stash._job["t"] = 0; b.stash.tick()
check(f"…search, get ({sent})", "search" in sent and "get log raft" in sent)
g.carrying = "log raft, broadsword"; b.stash._job["t"] = 0; b.stash.tick(); g.inv_seq += 1; b.stash._job["t"] = 0; b.stash.tick()
check(f"picked up: stash cleared ({st.raft_stash})", not st.raft_stash)
b.errands.tick()
check("…waits a moment for the party's own", b.errands.active and b.errands.active["todo"])
b.errands.active["todo"][0]["started"] -= 10
starts = []
b.start_path = lambda m, loop=None, checked=False: starts.append(m.title)
b.goto = lambda *a, **k: starts.append("goto") or True
b.errands.tick()
check(f"then on its way ({starts})", not b.errands.active and starts)
# gone: buys one
st.raft_stash = {"room": list(LOOP), "items": ["log raft"], "t": time.time()}
g.carrying = "broadsword"
b.errands.active = {"todo": [dict(src, started=None)], "then": (go, False), "started": time.time(), "at": None,
                    "tries": 0}
b.errands.active["todo"][0].pop("started")
starts.clear(); sent.clear()
b.errands.tick()
for _ in range(30):
    if b.stash._job:
        b.stash._job["t"] = 0
        if b.stash._job.get("seq") is not None:
            g.inv_seq += 1
    b.stash.tick()
check("gone from the stash: record cleared", not st.raft_stash)
b.errands.active["todo"][0]["started"] -= 10
b.errands.tick()
check(f"…and the walk starts over (which buys one) ({starts})", starts == ["Go to 1/1813 Pier"])
check(f"…the shop is the source now ({(b.errands.source_for(RAFT) or {}).get('kind')})",
      (b.errands.source_for(RAFT) or {}).get("kind") == "shop")
# a follower: @stash / @unstash
st.raft_stash = {}
g.carrying = "log raft"
check(f"follower @stash: hides it ({s.remote.c_stash('Miserable', 'raft')})", b.stash.busy())
b.stash._job = None
check(f"follower @unstash with nothing hidden: says so ({s.remote.c_unstash('Miserable', '')})",
      s.remote.c_unstash("Miserable", "") == "nothing stashed")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
