"""0.8.201 (Dan): hang-up item pickup (hangupitems.py), from MudPlay's hang-up item recheck.
On a Stock-type board set to drop items on a penalised hang-up, MudPilot snapshots what it carries (worn, carried,
keys; no coins) at its save points once 'i' has been read this connection; back in, it holds the walk, reads 'i',
works out what's missing, checks it's the same room and it can see (no dark, no monster), and gets each missing item
up to the floor count, never more than the board's item count; puts worn gear back on; once per connection.
Snapshot near death + one life fewer somewhere else = a death, left to death recovery. Paradigm: never (only HP)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MUDPILOT_NO_RECORD", "1")
from mudpilot import config, hangupitems as H
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


# ------------------------------------------------------------ the pure parts
c = H.counts("2 torch, vortex staff (Weapon Hand), 40 gold crowns, 3 copper farthings, skull mask (Face), rope and "
             "grapple", "golden lion key, 2 silver key")
check(f"counts: worn + carried + keys, no coins ({c})",
      c == {"torch": 2, "vortex staff": 1, "skull mask": 1, "rope and grapple": 1, "golden lion key": 1,
            "silver key": 2})
miss = H.missing(c, H.counts("torch, rope and grapple, 40 gold crowns", "2 silver key"))
check(f"diff ({miss})", miss == {"torch": 1, "vortex staff": 1, "skull mask": 1, "golden lion key": 1})
floor = [(1, "vortex staff"), (3, "torch"), (1, "golden lion key")]
plan = H.pickup_plan(miss, floor, 10)
check(f"floor cap: no skull mask on the floor, 1 torch not 3 ({plan})",
      sorted(plan) == [("golden lion key", 1), ("torch", 1), ("vortex staff", 1)])
plan = H.pickup_plan(miss, floor, 2)
check(f"realm cap: 2 in all ({plan})", sum(n for _x, n in plan) == 2)
check("cap 0: nothing", H.pickup_plan(miss, floor, 0) == [])


class Tel:
    connected = True
    def __init__(self): self.out = []
    def send_line(self, x): self.out.append(x)
    def close(self): self.connected = False


def make(board="Stock", drop=True, count=3):
    st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
    s = Session(st); s._no_log_file = True
    st.board, st.host = board, "bbs.example.org"
    st.hangup_items_drop, st.hangup_items_count = drop, count
    s.telnet = Tel()
    s._entered = True
    s._connected_at = time.time() - 100
    g = s.state
    g.candidates = [(1, 297)]
    g.hp, g.max_hp, g.lives = 120, 200, 5
    s.hangup_items.tick()                         # (notices the connection: no 'i' read on it yet)
    return s, st, g


def read_inv(s, carrying, keys=""):
    s.state.carrying, s.state.keys = carrying, keys
    s.state.inv_seq += 1


def back_in(s):
    s._connected_at = time.time()
    s.hangup_items.tick()                         # a new connection
    s._entered_at = time.time()
    s.hangup_items.on_entered()


def gets(s):
    return [c for c in s.telnet.out if c.startswith("get ")]


def run(s, secs=12, step=0.5):
    """Let the pass tick on, moving its clock along (the state machine waits on real seconds)."""
    real = H.time.time
    t = [real()]
    H.time.time = lambda: t[0]
    try:
        for _ in range(int(secs / step)):
            t[0] += step
            s.hangup_items.tick()
            if not s.hangup_items.job:
                break
    finally:
        H.time.time = real


FULL = "vortex staff (Weapon Hand), skull mask (Face), 2 torch, 40 gold crowns"

# ------------------------------------------------------------ off by default, Paradigm off
check("off and 0 by default", config.Settings().hangup_items_drop is False and config.Settings().hangup_items_count == 0)
s, st, g = make(board="Paradigm")
read_inv(s, FULL)
check("Paradigm: no snapshot, never armed", not s.hangup_items.snapshot() and not s.hangup_items.enabled())
s, st, g = make(drop=True, count=0)
read_inv(s, FULL)
check("count 0: off", not s.hangup_items.enabled())

# ------------------------------------------------------------ snapshot only after an 'i' this connection
s, st, g = make()
g.carrying = FULL                                 # (left over from before: not read on this connection)
check("no 'i' this connection: no snapshot", not s.hangup_items.snapshot())
read_inv(s, FULL, "golden lion key")
s._save_quietly()                                 # a profile save point
sn = s.hangup_items.snap
check(f"snapshot at a save point ({sn and sn['items']})", sn and sn["items"] == {"vortex staff": 1, "skull mask": 1,
                                                                               "torch": 2, "golden lion key": 1}
      and sn["room"] == [1, 297] and sn["hp"] == 120 and sn["lives"] == 5)

# ------------------------------------------------------------ the pass: same room, items on the floor
g.in_combat = True
s._on_closed("test drop")                         # HP / fight at the drop
check("the drop notes the fight", s.hangup_items.snap["combat"] is True)
g.in_combat = False
back_in(s)
check("back in: the walk is held", "hang-up items" in s.bot.walk_holds())
read_inv(s, "torch, 40 gold crowns", "golden lion key")    # the login's 'i': staff, mask and a torch gone
g.view = RoomView("Arena", {"N", "S"}, items=[(1, "vortex staff"), (1, "skull mask"), (2, "torch")], t=time.time())
run(s, 2)
check(f"gets each missing item, capped at the board's 3 ({gets(s)})",
      sorted(gets(s)) == ["get skull mask", "get torch", "get vortex staff"])
read_inv(s, "vortex staff, skull mask, 2 torch, 40 gold crowns", "golden lion key")
run(s, 10)
eq = [c for c in s.telnet.out if c.startswith("eq ")]
check(f"puts the worn ones back on ({eq})", sorted(eq) == ["eq skull mask", "eq vortex staff"])
check("then lets the walk go", not s.hangup_items.job and "hang-up items" not in s.bot.walk_holds())
n_before = len(s.telnet.out)
s.hangup_items.on_entered()
check("one pass per connection", not s.hangup_items.job and len(s.telnet.out) == n_before)

# ------------------------------------------------------------ a floor with more than we lost: the cap holds
s, st, g = make(count=1)
read_inv(s, "4 torch, rope")
s._save_quietly()
back_in(s)
read_inv(s, "rope")
g.view = RoomView("Arena", {"N"}, items=[(9, "torch")], t=time.time())
run(s, 2)
check(f"realm cap: 1 torch, not 4 ({gets(s)})", gets(s) == ["get torch"])

# ------------------------------------------------------------ not the same room / dark / monster: nothing
for label, room, view in (
        ("a different room", (1, 298), RoomView("Hall", {"E"}, items=[(1, "rope")], t=time.time())),
        ("a dark room", (1, 297), RoomView("(dark)", None, t=time.time())),
        ("a monster here", (1, 297), RoomView("Arena", {"N"}, monsters=[("orc", None)], items=[(1, "rope")],
                                               t=time.time()))):
    s, st, g = make()
    read_inv(s, "rope, torch")
    s._save_quietly()
    back_in(s)
    read_inv(s, "torch")
    g.candidates = [room]
    g.view = view
    run(s, 8)
    check(f"{label}: nothing picked up, walk released ({gets(s)})",
          gets(s) == [] and not s.hangup_items.job and "hang-up items" not in s.bot.walk_holds())

# ------------------------------------------------------------ the login 'i' never comes: we ask
s, st, g = make()
read_inv(s, "rope, torch")
s._save_quietly()
back_in(s)
real = H.time.time
H.time.time = lambda: real() + 5
s.hangup_items.tick()
H.time.time = real
check(f"no 'i' after login: asks for one ({s.telnet.out[-1:]})", s.telnet.out[-1:] == ["i"])

# ------------------------------------------------------------ the death path
s, st, g = make()
g.hp = -3                                          # dropped when the line went
read_inv(s, "vortex staff (Weapon Hand), rope")
s._save_quietly()
deaths = []
s.bot.on_death = lambda: deaths.append(s.bot._last_room)
back_in(s)
read_inv(s, "rope")
run(s, 1)
check(f"near death: reads 'stat' first ({s.telnet.out[-1:]})", s.telnet.out[-1:] == ["stat"])
s.hangup_items.note_line("Lives/CP:      4/12")
g.candidates = [(1, 1)]                            # where the dead arrive
g.view = RoomView("Temple", {"N"}, items=[(1, "vortex staff")], t=time.time())
run(s, 4)
check(f"one life fewer, elsewhere: a death, left to death recovery ({deaths}, {gets(s)})",
      deaths == [(1, 297)] and gets(s) == [] and not s.hangup_items.job)

s, st, g = make()
g.hp = 10
read_inv(s, "rope, torch")
s._save_quietly()
s.bot.on_death = lambda: deaths.append("wrong")
back_in(s)
read_inv(s, "torch")
g.view = RoomView("Arena", {"N"}, items=[(1, "rope")], t=time.time())
run(s, 1)
s.hangup_items.note_line("Lives/CP:      5/12")   # same lives: no death — pick up as usual
run(s, 6)
check(f"low HP but no life lost: picks up ({gets(s)})", gets(s) == ["get rope"] and "wrong" not in deaths)

# ------------------------------------------------------------ the line drops mid-pass: tried again next time
s, st, g = make()
read_inv(s, "rope, torch")
s._save_quietly()
back_in(s)
s.telnet.connected = False
s.hangup_items.tick()
check("drop mid-pass: list kept, hold released", s.hangup_items.snap and not s.hangup_items.job and
      "hang-up items" not in s.bot.walk_holds())
s.telnet.connected = True
back_in(s)
check("…and checked again on the next connection", s.hangup_items.job is not None)

# ------------------------------------------------------------ a clean quit: nothing to check
s, st, g = make()
read_inv(s, "rope, torch")
s._save_quietly()
st.game_exit_cmd = "x"
s.disconnect()
s.telnet = Tel()
back_in(s)
check("a clean quit (the game's exit command): no check", s.hangup_items.job is None)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
