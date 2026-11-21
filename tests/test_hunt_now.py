"""Dan, 2026-11-03: hunt the crimson mist now — never killed by us, so no clock says it's due, and a Go to only walks
to the nearest of its 16 lairs. Hunt now / @hunt: every lair, nearest next, no clock. MME has two crimson mists:
the 300k one with a 7-hour regen is the one meant."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet = type("T", (), {"connected": True, "send_line": lambda self, x: None, "close": lambda self: None})()
s._entered = True
s.bosses.save = lambda: None
bh, b = s.bosshunt, s.bot
mon = bh.named("crimson mist")
check(f"the crimson mist meant is the 300k one with the regen ({mon and mon['num']})", mon and mon["num"] == 309)
lairs = bh.lairs(mon)
start = min(lairs)                                   # stand near: one of its lairs' neighbours would do
s.state.candidates = [(17, 1622)]
gone = []
b.goto = lambda room, **k: gone.append(room) or True
msg = bh.hunt_now(mon)
check(f"hunt now: goes, no clock needed ({msg})", gone and bh.active and bh.active["num"] == 309)
check(f"…checks every lair ({bh.active and bh.active['lairs']} of {len(lairs)})",
      bh.active and bh.active["lairs"] == len(lairs) and set([bh.active["room"]] + bh.active["sweep"]) == set(lairs))
check("…walks straight in (no stop-before-boss at its door)", b._boss_ok == bh.active["room"])
check("it's on the Bosses tab now", str(mon["num"]) in s.bosses.data)
check(f"twice: says it's busy ({bh.hunt_now(mon)})", "already hunting" in bh.hunt_now(mon))
# killed: done, back where it was
s.bosses.data[str(mon["num"])]["dead_since"] = time.time()
bh.active["killed"] = time.time() - 10
gone.clear()
s.state.candidates = [bh.active["room"]]
bh._follow_up()
check(f"killed: back to where it started ({gone})", not bh.active and gone == [(17, 1622)])
# behind doors he picks: the golem (1/1797, the green metal and large iron key doors) — 'no route' was wrong
bh.active = None
s.state.candidates = [(17, 1635)]
golem = bh.named("guardian golem")
msg = bh.hunt_now(golem)
check(f"the guardian golem, behind locked doors: goes ({msg})", bh.active and bh.active["num"] == golem["num"])
# not there: back to the loop by a Go to (through the doors), not 'lost and no route back to the path'
from mudpilot.pathbuilder import route_to_mpath
glade = route_to_mpath(s.world, (17, 1622), s.world.route((17, 1622), (17, 1630)), "Rotting Glade Full")[0]
bh.active["back"] = (glade, True)
s.state.candidates = [(1, 1797)]
thens = []
b.goto = lambda room, then=None, **k: thens.append((room, then)) or True
b.walking = False
bh._done("guardian golem wasn't there (someone got it first?)")
check(f"golem not there: Go to the loop's start, then the loop ({[(r, t and t.title) for r, t in thens]})",
      thens and thens[-1][1] is glade and thens[-1][0] == glade.steps[0].room)
b.goto = lambda room, **k: gone.append(room) or True
bh.active = None
# fetching a raft on the way (at the Pier, standing still a moment to buy): still hunting, not 'the walk stopped'
s.state.candidates = [(17, 1622)]
bh.hunt_now(mon)
bh.active["leg_t"] = bh.active["t"] = time.time() - 30
b.walking = False
b.status = "Buying a log raft"
b.errands.active = {"todo": [{"kind": "shop"}], "then": (None, False)}
bh._follow_up()
check("buying the raft on the way: the hunt goes on", bh.active is not None)
b.errands.active = None
bh.active = None
# not looping (stopped, on a Go to) with a last loop: the hunt goes back to that loop after
b.walking, b.loop = False, False
b.path = None
b.last_path, b.last_loop = glade, True
s.state.candidates = [(17, 1622)]
bh.hunt_now(mon)
check(f"stopped, last loop Rotting Glade: back to it after ({bh.active and bh.active['back'] and bh.active['back'][0].title})",
      bh.active and bh.active["back"] == (glade, True))
bh.active = None
# a restart told to hunt: once in, hunts with the loop after
b.last_path = None
s._hunt_resume = {"num": 309, "back": glade, "t": time.time() - 30}
s._regroup = None
s.state.in_combat = False
bh.tick()
check(f"restart with 'hunt': hunting, then the loop ({bh.active and bh.active['name']})",
      bh.active and bh.active["num"] == 309 and bh.active["back"] == (glade, True))
bh.active = None
# @hunt
s.remote._channel = "telepath"
replies = []
s.remote.reply = lambda ch, who, txt: replies.append(txt)
s.state.candidates = [(17, 1622)]
out = s.remote.c_hunt("Buddy", "crimson mist")
check(f"@hunt crimson mist: hunting ({out or replies})", bh.active and bh.active["num"] == 309)
check(f"@hunt nonsense: says so ({s.remote.c_hunt('Buddy', 'zzqq')})", "no monster" in s.remote.c_hunt("Buddy", "zzqq"))
# not caught in any lair: looked for again one respawn (7 h) later, and again, till it's caught
bh.active = None
s.bosses.data[str(mon["num"])].pop("dead_since", None)
s.bosses.data[str(mon["num"])].pop("check_at", None)
s.state.candidates = [(17, 1622)]
bh.hunt_now(mon)
bh._done("crimson mist wasn't in any of its 16 lairs")
rec = s.bosses.data[str(mon["num"])]
left = rec.get("check_at", 0) - time.time()
check(f"empty sweep: next look booked in ~7 h ({left / 3600:.1f} h)", 6.9 * 3600 < left < 7.1 * 3600)
check("not due yet", not bh.due())
rec["check_at"] = time.time() - 1
check("7 h on: due again", [m["num"] for m, _r, _k in bh.due()] == [309])
# the timed look sets off from the loop, however far (you asked for it by name)
st.boss_hunt_on, st.boss_hunt_max_steps = True, 80
b.walking, b.loop = True, True
b.path = type("P", (), {"title": "Rotting Glade Full", "steps": []})()
s.state.in_combat = s.state.resting = False
s.state.max_hp = 0
gone.clear()
bh.tick()
check(f"…and goes from the loop, past the 80-step limit ({gone[:1]})", bh.active and gone)
check("…once per booked look", not bh.due())
# caught: its own clock takes over
s.bosses.record_kill(mon)
check("killed: no more blind looks", "check_at" not in rec)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
