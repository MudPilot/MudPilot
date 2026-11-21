"""Evolution, 2026-11-06: rafts never stashed on Rotting Glade Full. The stash only ran on a brand-new loop; every raft
bought for a Go to (the Ruined Shop, a boss hunt) came back to the same loop and was carried all day."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
st.auto_combat = False; st.auto_rest = False; st.auto_spells = False; st.auto_bless = False
s = Session(st); b = s.bot; w = s.world
s._no_log_file = True
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="Rotting Glade Full")
lp.filename = "/x/RGF.mp"
s.state.candidates = [(1, 3)]
calls = []
b.stash.on_loop = lambda mp, tell=False: calls.append(mp.title) or False
b.start_path(lp, loop=True, checked=True)
b._begin_loop(lp)
b.walk([], [])
check(f"a new loop stashes ({calls})", calls == ["Rotting Glade Full"])
calls.clear()
b.walk([], [])
check("…once", not calls)
# a Go to (an errand / a hunt) and back to the same loop
b._lap_path = lp
s.state.pending.clear(); s.state.candidates = [(1, 3)]
b.start_path(lp, loop=True, checked=True)
check("back on the same loop: no exp/hr reset", getattr(b, "_loop_reset_pending", None) is None)
b.walk([], [])
check(f"…but the raft's stashed again ({calls})", calls == ["Rotting Glade Full"])
calls.clear()
b.walk([], [])
check("…once", not calls)
# just back in after a restart: the pack not read yet → 'i', then stash once it's read
from mudpilot.stash import Stash
b.stash = Stash(b)
s.state.carrying, s.state.keys = "", ""
b._picked_items = set()
sent = []
b.send = lambda c, **k: sent.append(c)
b.carry_sets = lambda m: []
b._awaiting_move = lambda now: False          # (the test's own last step isn't answered)
check("pack not read: asks 'i' and tries later", b.stash.on_loop(lp) is None and "i" in sent)
b._stash_pending = lp; s.state.pending.clear(); b.walk([], [])
check("…still pending", b._stash_pending is lp)
s.state.carrying = "log raft, broadsword"; s.state.inv_seq += 1
s.state.pending.clear(); s.state.candidates = [b.path.steps[b.idx].room]; b.walk([], [])
check(f"…read: stashes the raft ({b.stash._job and b.stash._job['names']})",
      b._stash_pending is None and b.stash._job and b.stash._job["names"] == ["log raft"])
b.stash._job = None; b.stash._inv_asked = None
s.state.carrying = ""
b.stash.on_loop(lp); s.state.inv_seq += 1
check("an empty pack once read: done, no more 'i'", b.stash.on_loop(lp) is False)
# Evolution leads with no raft; Buddy and Revolution carry them (2026-11-06): the party's told anyway
b.stash._job = None; b.stash._inv_asked = None
s.state.carrying = "broadsword"; s.state.inv_seq += 1
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
s.comeback.leading = lambda: True
sent.clear()
b.stash.on_loop(lp)
check(f"leader with no raft, nothing said about the party: no @stash ({sent})", not any("@stash" in c for c in sent))
b.stash.on_loop(lp, tell=True)
check(f"…a new loop: the party's told @stash ({sent})", "/Buddy @stash raft" in sent and "/Revolution @stash raft" in sent)
sent.clear()
b.errands.party_boats = True
b.stash.on_loop(lp)
check(f"…their @have said they carry rafts: told ({sent})", "/Buddy @stash raft" in sent and not b.errands.party_boats)
# the follower: '@stash' with the pack not read yet (just back in) → 'i', then hide
f = Session(config.Settings()); f.settings.save = lambda: None; f._no_log_file = True
fb = f.bot; fsent = []
fb.send = lambda c, **k: fsent.append(c)
f.state.candidates = [(1, 3)]
check("follower: pack not read → reads it first", fb.stash.hide_asked() and "i" in fsent)
f.state.carrying = "log raft, longsword"; f.state.inv_seq += 1
fb.stash.tick()
check(f"…then hides the raft ({fsent})", "hide log raft" in fsent)
# the leader walks on before the 'i' check: still remembered (Buddy, 2026-11-06)
f.state.candidates = [(1, 4)]
fb.stash.tick()
check(f"follower moved on after 'hide': the stash is remembered ({f.settings.raft_stash})",
      f.settings.raft_stash.get("items") == ["log raft"] and tuple(f.settings.raft_stash["room"]) == (1, 3))
# Rego just back in, room not known yet: look, then carry on once it is (Miserable PVE, 2026-11-06)
g = Session(config.Settings()); g.settings.save = lambda: None; g._no_log_file = True
gb = g.bot; gsent = []; gone = []
gb.send = lambda c, **k: gsent.append(c)
g.telnet = T(); g._entered = True
gb.goto = lambda t, then=None, ask=None, _retry=False: gone.append(t) or True
gb.resume = {"target": (13, 785), "after": None}
g.state.candidates = []
check("Rego with the room unknown: looks first", gb.rego() and "" in gsent and not gone)
g.state.candidates = [(13, 391)]
gb.tick()
check(f"…then carries on once it knows ({gone})", gone == [(13, 785)])
sys.exit(0 if ok else 1)
