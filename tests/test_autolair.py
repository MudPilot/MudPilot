"""0.8.201 (Dan): Camp lairs (lair_camp.py) — MudPlay's Auto-Lair as its own engine, off unless started.
- respawn T from Rooms.Delay: Stock Delay*60+30 s from the last kill, Paradigm (Delay-1)*60+30 s from entry; a time
  lairclock.py has learned wins
- the next lair: the closest that's back by arrival, else the soonest back; or least late (throughput)
- the wait room's entry instant is latched once; the walker is asked once, not every tick
- in the lair: empty after 3 s → move on; a fight is capped at 30 s (never walking out mid-fight)
- a failed entry backs off 2 s, 4 s …; a door we can't open drops the lair; 'no route' is believed 30 s
- bank / stash / train trips pause it and their way back resumes it; a reconnect keeps the clocks
- @camp start / stop / list, never on a follower; Stop ends it; it's off by default (LAIR_PACING stays off)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MUDPILOT_NO_RECORD", "1")
from mudpilot import config, lair_camp as LC
from mudpilot.automation import Automation
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


class Clock:
    t = 1_000_000.0
    @classmethod
    def time(cls):
        return cls.t
LC.time = Clock                                    # the module's clock only (the session keeps the real one)


# a little map: A(1/1) - B(1/2) - L1(1/3) - L2(1/4), and A - C(1/5) - D(1/6) - L3(1/7)
class Ex:
    def __init__(self, to): self.to = to
class Room:
    def __init__(self, key, name, delay=0, lair=""):
        self.key, self.name, self.delay, self.lair, self.exits = key, name, delay, lair, {}
class World:
    def __init__(self):
        self.rooms = {}
    def room(self, k): return self.rooms.get(tuple(k)) if k else None
    def can_use(self, ex, **kw): return True
W = World()
def add(k, name, delay=0):
    W.rooms[k] = Room(k, name, delay, "(Max 3): 5" if delay else "")
def link(a, b, da, db):
    W.rooms[a].exits[da] = Ex(b); W.rooms[b].exits[db] = Ex(a)
A, B, L1, L2, C, D, L3 = (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7)
add(A, "Square"); add(B, "Hall"); add(L1, "Den", 3); add(L2, "Back Den", 2)
add(C, "Path"); add(D, "Glade"); add(L3, "Far Den", 5)
link(A, B, "E", "W"); link(B, L1, "E", "W"); link(L1, L2, "E", "W"); link(A, C, "N", "S"); link(C, D, "N", "S")
link(D, L3, "N", "S")


class Tel:
    connected = True
    def send_line(self, x): pass

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
s.telnet = Tel()
s._entered = True
s.world = W
b, g, lc = s.bot, s.state, s.lair_camp
b.send = lambda *a, **k: None
b.route_level = lambda: None
b.held_items = lambda: set()
b.avoid_set = lambda: frozenset()
b.walk_holds = lambda: {}
mobs = []
b.attackable = lambda: list(mobs)
lc._secs_per_step = lambda: 2.0
s.lairclock.estimate = lambda room: None
gotos = []
goto_ret = {"v": True}
class P:
    def __init__(self, dest): self.title = f"Go to {dest[0]}/{dest[1]}"; self.steps = []
def fake_goto(dest, then=None, ask=None, **kw):
    gotos.append(tuple(dest))
    if not goto_ret["v"]:
        b.no_route_msg = goto_ret.get("msg", "No walkable route")
        return False
    b.walking, b.loop, b.path, b._goto_target = True, False, P(dest), tuple(dest)
    return True
b.goto = fake_goto
def arrive(room):
    g.candidates = [room]
    b.walking, b.path = False, None

# ------------------------------------------------------------ off by default, old pacing untouched
check("off by default (nothing marked, not camping)", config.Settings().lair_camp_rooms == [] and not lc.on and
      config.Settings().lair_camp_throughput is False and config.Settings().hangup_items_drop is False)
check("the old loop lair pacing is still switched off", Automation.LAIR_PACING is False)

# ------------------------------------------------------------ respawn maths
check("Stock: Delay*60+30", LC.respawn_secs(3, "stock") == 210 and LC.respawn_secs(1, "stock") == 90)
check("Paradigm: (Delay-1)*60+30", LC.respawn_secs(3, "paradigm") == 150 and LC.respawn_secs(1, "paradigm") == 30)
check("no Delay: no MME time", LC.respawn_secs(0, "stock") is None)
st.board, st.host = "Stock", "bbs.example.org"
check("realm: Stock board", LC.realm_of(s) == "stock")
st.host = "paramud.mudinfo.net"
check("realm: Paradigm host", LC.realm_of(s) == "paradigm")
st.board, st.host = "Paradigm", ""
check("realm: Paradigm board", LC.realm_of(s) == "paradigm")

st.lair_camp_rooms = ["1/3", "1/4", "1/7"]
now = Clock.t
lc.anchors = {L1: {"kill": now - 100, "entry": now - 160}}
st.board = "Stock"
check(f"Stock times from the last kill ({lc.ready_at(L1) - now:.0f})", lc.ready_at(L1) == now - 100 + 210)
st.board = "Paradigm"
check(f"Paradigm times from the entry ({lc.ready_at(L1) - now:.0f})", lc.ready_at(L1) == now - 160 + 150)
s.lairclock.estimate = lambda room: 60.0 if room == L1 else None
check(f"a learned time wins, from the kill ({lc.ready_at(L1) - now:.0f}, {lc.respawn(L1)})",
      lc.ready_at(L1) == now - 100 + 60 and lc.respawn(L1) == (60.0, "learned"))
s.lairclock.estimate = lambda room: None
check("nothing seen = ready now", lc.ready_at(L2) == 0.0)
check(f"no Delay at all: the default refill ({lc.respawn(A)})", lc.respawn(A)[1] == "default")
st.board = "Stock"

# ------------------------------------------------------------ wait rooms and the pick
g.candidates = [A]
dist = lc.distances(A)
check(f"wait room for L1 is the hall ({lc.wait_room_for(L1, dist)})", lc.wait_room_for(L1, dist) == B)
check(f"wait room for L2 isn't the marked L1 ({lc.wait_room_for(L2, dist)})", lc.wait_room_for(L2, dist) is None)
check(f"wait room for L3 is the glade ({lc.wait_room_for(L3, dist)})", lc.wait_room_for(L3, dist) == D)
lc.anchors = {}
c = lc.pick()
check(f"all back: the closest ({c and c['room']})", c and c["room"] == L1)
lc.anchors = {L1: {"kill": now}, L2: {"kill": now}}              # L1 back in 210 s, L2 in 150 s, L3 now
c = lc.pick()
check(f"L1/L2 not back yet: L3, which is ({c and c['room']})", c and c["room"] == L3)
lc.anchors = {L1: {"kill": now}, L2: {"kill": now}, L3: {"kill": now}}   # L3 in 330 s
c = lc.pick()
check(f"none back by arrival: the soonest back, L2 ({c and c['room']})", c and c["room"] == L2)
lc.anchors = {L1: {"kill": now - 207}, L2: {"kill": now - 200}}        # L1 back in 3 s (we're 4 s off), L2, L3 now
st.lair_camp_throughput = False
c = lc.pick()
check(f"closest rule: L1 (back by the time we walk in) ({c and c['room']})", c and c["room"] == L1)
lc.anchors = {L1: {"kill": now - 150}, L3: {"kill": now - 330}}        # L1 back in 60 s; L2, L3 ready
c = lc.pick()
check(f"closest rule: a lair that's back (L2 / L3), not wait for L1 ({c and c['room']})", c and c["room"] in (L2, L3))
st.lair_camp_throughput = True
c = lc.pick()
check(f"throughput rule: least late (max(0, slack)) — L1, not late at all ({c and c['room']}, "
      f"slack {c and round(c['slack'])})", c and c["room"] == L1)
lc.anchors = {L1: {"kill": now - 300}, L2: {"kill": now - 152}, L3: {"kill": now - 600}}   # all back already
c = lc.pick()
check(f"throughput rule, all back: the one we reach soonest after it's back ({c and c['room']})", c and c["room"] == L1)
st.lair_camp_throughput = False

# ------------------------------------------------------------ start: anchors cleared, follower refused
st.party_leader = "Revolution"
s.state.party = {"Revolution": {}, "Miserable": {}}
r = s.remote.c_camp("Revolution", "start")
check(f"never starts on a follower ({r!r})", not lc.on and "follow" in r)
st.party_leader = ""
s.state.party = {}
lc.anchors = {L1: {"kill": now}}
r = s.remote.c_camp("Revolution", "start")
check(f"@camp start ({r!r}) clears the marked lairs' clocks", lc.on and lc.anchors == {} and "3 lairs" in r)
lst = s.remote.c_camp("Revolution", "list")
check(f"@camp list ({lst})", isinstance(lst, list) and any("1/3 Den" in x for x in lst))
check("@camp is a 'move' command", __import__("mudpilot.remote", fromlist=["COMMANDS"]).COMMANDS.get("@camp") == "move")

# ------------------------------------------------------------ walk to the wait room, latch, one step in
lc.anchors = {L1: {"kill": now - 150}, L2: {"kill": now}, L3: {"kill": now}}   # L1 back in 60 s: the soonest
g.candidates = [A]
lc._next_look = 0
lc.tick()
check(f"walking to the wait room first ({lc.state}, {gotos})", lc.state == "approach" and gotos == [B])
for _ in range(5):
    lc.tick()
check(f"…asked once, not every tick ({gotos})", gotos == [B])
Clock.t += 4
arrive(B)
lc.tick()
check(f"in the wait room: latched ({lc.state}, enters at +{lc.entry_at - Clock.t:.0f} s)",
      lc.state == "wait" and abs(lc.entry_at - (now - 150 + 210)) < 0.01)
latched = lc.entry_at
lc.anchors[L1]["kill"] = Clock.t                  # (a later kill wouldn't move it: latched, not recomputed)
Clock.t += 30
lc.tick()
check(f"waiting, latched instant unchanged, nothing sent ({lc.state}, {gotos})",
      lc.state == "wait" and lc.entry_at == latched and gotos == [B])
lc.anchors[L1]["kill"] = now - 150
Clock.t = latched - 0.5
lc.tick()
check("never early: still waiting half a second before", lc.state == "wait" and gotos == [B])
Clock.t = latched + 0.1
lc.tick()
lc.tick()
check(f"at the instant: one step in, asked once ({lc.state}, {gotos})", lc.state == "enter" and gotos == [B, L1])
Clock.t += 2
arrive(L1)
lc.tick()
check(f"in the lair: engaging ({lc.state})", lc.state == "engage")

# ------------------------------------------------------------ the 3 s grace
Clock.t += 2
lc.tick()
check("empty for 2 s: still looking", lc.state == "engage")
Clock.t += 1.1
lc.tick()
check(f"empty after 3 s: moving on ({lc.state})", lc.state in ("choose", "approach", "enter", "wait"))

# ------------------------------------------------------------ the 30 s cap
lc.state, lc.target = "choose", None
lc.target = L1
g.candidates = [L1]
lc._begin_engage(Clock.t)
t0 = Clock.t
mobs[:] = [("statue", None)]                      # something here we won't stop fighting / that won't die
g.in_combat = True
Clock.t = t0 + 31
lc.tick()
check("past 30 s but still in combat: never walks out mid-fight", lc.state == "engage" and lc._engage["capped"])
g.in_combat = False
Clock.t = t0 + 29
lc._engage["capped"] = False
lc.tick()
check("29 s with monsters standing about: still in", lc.state == "engage")
Clock.t = t0 + 31
lc.tick()
check(f"31 s, no fight on: leaves anyway ({lc.state})", lc.state != "engage")
mobs[:] = []

# a kill in the lair is its clock start
lc.target = L1
g.candidates = [L1]
lc._begin_engage(Clock.t)
mobs[:] = [("orc", None)]
lc.tick()
lc._on_exp(500)
kill_t = Clock.t
mobs[:] = []
Clock.t += 1
lc.tick()
check("loot first: not out 1 s after the kill", lc.state == "engage")
Clock.t += 1.5
lc.tick()
check(f"then out, the kill anchoring the clock ({lc.state}, {lc.anchors.get(L1)})",
      lc.state != "engage" and lc.anchors[L1]["kill"] == kill_t)

# standing in the only lair left, not back yet: step out to its wait room, don't stand in it early
saved = st.lair_camp_rooms
st.lair_camp_rooms = ["1/3"]
lc.anchors = {L1: {"kill": Clock.t}}
lc.state, lc.target, lc._disp, lc._next_look = "choose", None, None, 0
g.candidates = [L1]
b.walking = False
gotos.clear()
lc.tick()
check(f"in a lair that isn't back: out to its wait room ({lc.state}, {gotos})", lc.state == "approach" and gotos == [B])
st.lair_camp_rooms = saved
b.walking, b.path = False, None

# ------------------------------------------------------------ failed entry back-off, door drop, no-route cache
lc.state, lc.target, lc._disp = "choose", None, None
g.candidates = [A]
lc.anchors = {}
lc._next_look = 0
gotos.clear()
lc.tick()
check(f"(off to L1 again: {gotos}, {lc.state})", gotos == [L1] and lc.state == "enter")
b.walking, b.path = False, None                   # the walk stopped, still in the square
Clock.t += 3.5
lc.tick()
check(f"failed entry: L1 waits 2 s ({lc.backoff.get(L1)})", L1 in lc.backoff and lc.backoff[L1][1] == 2)
lc.state, lc.target, lc._disp = "enter", L1, None
lc.dispatch(L1, "enter")
b.walking, b.path = False, None
Clock.t += 3.5
lc.tick()
check(f"again: 4 s ({lc.backoff.get(L1)})", lc.backoff[L1][1] == 4)
lc.backoff = {L1: (Clock.t, 32)}
lc._failed(L1, "")
check("…doubling up to 60 s", lc.backoff[L1][1] == 60)
lc._failed(L1, "")
check("…and no further", lc.backoff[L1][1] == 60)
lc.backoff = {}
goto_ret.update(v=False, msg="No walkable route from 1/1 to 1/7 — blocked by the north exit of Glade (1/6): "
                             "locked door (needs a key)")
lc.state, lc.target = "enter", L3
lc.dispatch(L3, "enter")
check(f"door it can't open: L3 dropped for the run ({list(lc.dropped)})", L3 in lc.dropped)
goto_ret.update(v=False, msg="No walkable route from 1/1 to 1/4")
lc.state, lc.target = "enter", L2
lc.dispatch(L2, "enter")
check(f"no route: L2 cached 30 s ({lc.no_route.get(L2, 0) - Clock.t:.0f})",
      abs(lc.no_route.get(L2, 0) - Clock.t - 30) < 0.01 and L2 not in lc.dropped)
check("…and not picked meanwhile", all(x["room"] != L2 for x in lc.candidates()))
Clock.t += 31
check("…asked again after 30 s", any(x["room"] == L2 for x in lc.candidates()))
check("a dropped lair stays out", all(x["room"] != L3 for x in lc.candidates()))
goto_ret.update(v=True)
lc.dropped, lc.no_route, lc.backoff = {}, {}, {}

# ------------------------------------------------------------ trips pause and resume it
lc.state = "choose"
s.trips.trip = {"kind": "deposit", "room": A, "cmds": [], "back": (lc.mp, True), "t": time.time(),
                "phase": "going", "next_at": 0, "why": "test"}
lc.tick()
check(f"a bank trip pauses camping ({lc.state})", lc.state == "paused" and lc.on)
s.trips._back("deposit done")                     # its way back: start_path(our marker path)
check(f"the trip's way back resumes camping ({lc.state})", lc.state == "choose" and lc.on and not b.walking)
gotos.clear()
lc.tick()
check("…after a moment to settle", gotos == [])
Clock.t += LC.RESUME_SETTLE + 0.1
lc._next_look = 0
lc.tick()
check(f"…then on to a lair ({gotos})", len(gotos) == 1)
called = []
s.trips.lap_end = lambda mp: called.append(mp) or True
lc.target = L1
g.candidates = [L1]
b.walking = False
lc._begin_engage(Clock.t)
Clock.t += 3.5
lc.tick()
check(f"after a lair, the end-of-lap trips are asked (pauses: {lc.state})",
      called and called[0] is lc.mp and lc.state == "paused")
del s.trips.lap_end

# ------------------------------------------------------------ reconnect keeps the clocks
lc.state = "wait"
lc.anchors = {L1: {"kill": Clock.t}}
s._drop_resume = {"path": None, "target": B}
s._connected_at = time.time() + 5
lc.tick()
check(f"reconnect: picks again from here, clocks kept, the old Rego dropped ({lc.state})",
      lc.state == "choose" and lc.anchors[L1]["kill"] == Clock.t and s._drop_resume is None and lc.on)

# ------------------------------------------------------------ Stop, Hands off, @camp stop
b.stop("Stopped by you")
check("Stop ends it", not lc.on)
lc.start()
st.hands_off = True
lc.tick()
check("Hands off ends it", not lc.on)
st.hands_off = False
lc.start()
r = s.remote.c_camp("Revolution", "stop")
check(f"@camp stop ({r!r})", not lc.on)
lc.start()
b.walking = False
r = s.remote.c_stop("Revolution", "")
check(f"@stop while waiting by a lair ends it ({r!r})", not lc.on)
r = s.remote.c_camp("Revolution", "")
check(f"@camp alone lists ({r})", isinstance(r, list) and r[0] == "not camping")

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
