"""0.8.223, the 11-21 bug hunt's smaller oddities (HUNT_1121 "For Dan" 16 and notes): a pyramid segment door re-spliced
forever (m12pyr L1), grave digging (m12 #4), look-alike grid anchoring (m1617c R1), the rejoin that skips a spur (dark3
D2), "Arrived" in a dark look-alike (dark3 D3), 'key(1264)' in path commands (m1617c K1b), the bronze keys (m58 #4), the
'st' park (regr3 #5), a fare stop's reason (regr3 #2) and the HP-wall wording for a key (m14c M14C-3)."""
import copy, os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step, path_from_route, anchor_path
from mudpilot.automation import path_text
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
sent, logs, stops = [], [], []
s.send = lambda c, from_bot=False: sent.append(c)
b.log = lambda m, *a, **k: logs.append(m)
real_stop = b.stop
b.stop = lambda why="Stopped": stops.append(why)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
P = lambda title, steps=(), loop=False: type("P", (), {"title": title, "steps": list(steps), "is_loop": loop,
                                                         "resolve_note": ""})()

# --- K1b: 'use chiseled key(1264) SW' — the item number isn't part of the name
check("path_text strips a MegaMud item number", path_text("use chiseled key(1264) SW") == "use chiseled key SW")
check("…any item, not only keys", path_text("use shimmering spike(3668) n") == "use shimmering spike n")
check("…and leaves other brackets alone", path_text("say hello (5)") == "say hello (5)" and path_text("n") == "n")
room_ = (16, 2063)
g.candidates = [room_]
g.view = RoomView("Red Tunnels", {"SW", "N"}, [], [], [], time.time(), closed={"SW"}); g.view_seq += 1
stp = Step("00000000", 0, "SW", ["use chiseled key(1264) SW"], room_, (16, 2064))
b._opened = None; b._key_done = None; b._door_wait_until = 0; b._key_tries = {}
del sent[:]
b._key_door(stp, room_, time.time())
check(f"the path's key step goes out without the number ({sent})", sent == ["use chiseled key SW"])

# --- m58 #4: both bronze keys on you — the vault door's key by its whole name
b.held_items = lambda: {2135, 2141}                  # bronze house key, ornate bronze key
check(f"vault door 6/3468 N: '{b._door_key((6, 3468), 'N')}'", b._door_key((6, 3468), "N") == "ornate bronze key")
del b.held_items

# --- m12pyr L1: one exit gone round again and again stops after a few minutes
goes = []
b.back_route = lambda h, t: ["way"]
b.goto = lambda dest, then=None, ask=None, _retry=False, _looked=False: goes.append(dest) or True
b.path = P("Go to 12/2052 Great Pyramid", [Step("0", 0, "S", [], (12, 2002), (12, 2052))])
door = ((12, 2002), "S")
r3 = [b.route_around(*door, "the door south never opened") for _ in range(3)]
check(f"the first few times: round it (the timed doors' retries) {r3}", all(r3) and len(goes) == 3)
b._round_tries[door] = (60, time.time() - 200, time.time() - 3)
check("…after minutes of the same door back to back: no more 'going round it'",
      b.route_around(*door, "the door south never opened") is False)
check("…another door isn't held to it", b.route_around((12, 2032), "S", "the door south never opened") is True)
b._round_tries[door] = (5, time.time() - 700, time.time() - 120)
check("…the same door failing once a lap, minutes apart, isn't counted together", b.route_around(*door, "x") is True)
for k in list((getattr(w, "failed_edges", None) or {})):
    w.failed_edges.pop(k, None)
del b.back_route, b.goto

# --- m12 #4: 'dig grave' (a chance exit) isn't 'gone round', and a lost shovel is noticed
grave = (1, 840)
ex = w.room(grave).exits["@dig grave"]
check("'dig grave' is a chance exit", b._chance_exit(grave, "dig grave") is ex and b._chance_exit(grave, "n") is None)
rounds = []
b.route_around = lambda h, d, why: rounds.append((h, d)) or True
b.path = P("Graveyard dig", [Step("0", 0, "dig grave", [], grave, (1, 9462))], loop=True)
b.walking = True
b._lock_tries = {}
b._resends = ((grave, "dig grave"), 7)
check("8th dig: keep digging here, no 'going round it'", b._resend_guard(grave, "dig grave") is False and not rounds)
b._resends = ((grave, "dig grave"), 39)
del stops[:]
b._resend_guard(grave, "dig grave")
check(f"…40 digs: stop, saying why ({stops})", stops and "40 tries" in stops[-1])
b._resends = ((grave, "n"), 7)
b._resend_guard(grave, "n")
check("an ordinary exit still goes round after 8", rounds == [(grave, "N")])
del b.route_around
g.carrying, g.keys = "shovel, torch", ""
b._resends = ((grave, "dig grave"), 2)
b._step_sent_at = time.time()
b._chance_need = None
del sent[:]
b.note_line("Your command had no effect.")
check(f"'no effect' on the dig: read the pack ({sent})", "i" in sent and b._chance_need and b._chance_need["num"] == 1415)
check("…waiting for it", b._resend_guard(grave, "dig grave") is True)
g.carrying = "torch"; g.inv_seq += 1
del stops[:]
b._resend_guard(grave, "dig grave")
check(f"no shovel any more: stop, naming it ({stops})", stops and "shovel" in stops[-1])
g.carrying = "shovel, torch"
b._resends = ((grave, "dig grave"), 2); b._step_sent_at = time.time(); b._chance_need = None
b.note_line("Your command had no effect.")
g.inv_seq += 1
del stops[:]
check("shovel still there: dig on", b._resend_guard(grave, "dig grave") is False and not stops)
b.walking = False

# --- m1617c R1: started one room beside a loop in an open grid — no re-anchoring onto a parallel copy
a_, z_ = (16, 3832), (16, 3712)
mp = path_from_route(w, a_, (w.route(a_, z_, level=55) or []) + (w.route(z_, a_, level=55) or []), name="Ocean loop")
mp.end_hash, mp.resolve_note, mp.name = mp.start_hash, "", "Ocean Floor loop"   # (a loop file, not an MME plan)
check("(it's a loop)", mp.is_loop and not mp.title.startswith("Go to "))
off = (16, 3833)
rooms_before = [x.room for x in mp.steps]
hs = [j for j, x in enumerate(mp.steps) if x.hash == w.room(off).mega_hash and off not in rooms_before]
would = any(anchor_path(w, copy.deepcopy(mp), j, off) for j in hs)
check(f"(the old anchor would have slid the loop onto the next column: {would})", would)
b.path, b.idx = mp, 0
g.candidates = [off]
check("beside the loop: walk back, no re-anchor", b._anchor() is False and [x.room for x in mp.steps] == rooms_before)
far = next(k for k in w.rooms if k[0] == 16 and w.room(k).name == w.room(off).name and k not in rooms_before
           and not b._loop_rooms_near(k, mp))
check(f"(far from it, {far}: the anchor's still allowed to look)", b._loop_rooms_near(far, mp) is False)
b.path = None

# --- dark3 D2: knocked off mid-lap — back to the step we were on when it's only a little further
calls, own_len = [], [2]
def br(h, t):
    calls.append(t)
    return ["x"] if isinstance(t, (set, frozenset)) else ["y"] * own_len[0]
b.back_route = br
b._send_exit = lambda e: None
b._drifted = lambda why: False
def knocked():
    del calls[:]
    b.path, b.loop, b.walking, b.idx, b.detour = mp, True, True, 1, None
    b._replan_at = 0; b._last_progress = time.time()
    b._door_wait_until = 0; b._opening_dir = b._locked_dir = b._timed_dir = None; b._key_done = None
    g.locate_until = 0; g.pending.clear()
    g.candidates = [off]
    g.view = RoomView(w.room(off).name, set(w.room(off).exits), [], [], [], time.time()); g.view_seq += 1
    b.walk([], [])
    return b.detour
check(f"knocked off mid-lap: back to the step's own room (2 rooms), not the nearest loop room (1) ({knocked()})",
      b.detour == ["y", "y"] and mp.steps[1].room in calls)
own_len[0] = 5
check(f"…but not when that's a lot further ({knocked()})", b.detour == ["x"])
b.detour, b.walking, b.path = None, False, None
del b.back_route, b._send_exit, b._drifted

# --- dark3 D3: about to say "Arrived" in a dark look-alike — one 'pro' first
pl = b.pilot
pl._reset()
pl.target = (1, 9448)
g.candidates = [(1, 9448)]
g.located = None
g.view = RoomView("(dark)", None, [], [], [], time.time()); g.view_seq += 1
st.locate_cmd = "pro"
b._locate_failed = 0
asks = []
b.locate_now = lambda why="": asks.append(why) or True
check("dark look-alike target: asks the board first", pl._check_dark_arrival((1, 9448)) is True and asks)
check("…only once per Go to", pl._check_dark_arrival((1, 9448)) is False)
pl._reset()
g.located = ((1, 9448), time.time())
check("the board said so already: no asking", pl._check_dark_arrival((1, 9448)) is False)
del b.locate_now
g.located = None

# --- regr3 #5: the 'st' park waits for the answer (up to 10 s)
now = time.time()
pa = ((1, 1), None, None, now - 4)
b._cool["goto_st"] = pa[3]
g.max_hp_read, g.strength, g.picklocks = False, 0, 0
check("'st' not answered at 4 s: wait", b._st_unanswered(pa, now) is True)
check("…10 s is the most", b._st_unanswered(((1, 1), None, None, now - 11), now) is False)
g.max_hp_read, g.strength = True, 60
check("answered: re-plan", b._st_unanswered(pa, now) is False)
g.max_hp_read, g.strength = False, 0
b._cool["goto_st"] = now - 100
check("an 'abil' park isn't held up", b._st_unanswered(pa, now) is False)

# --- regr3 #2: a fare stop names the fare, not an old plan's door
class Trips:
    go = False
    def withdraw_for(self, mp, loop, short, why=""):
        b.no_route_msg = "No route: The north door in Harbor Road, Gate is in the way"
        return self.go
real_trips, s.trips = s.trips, Trips()
b.path_toll = lambda mp: 7_000_000
b.missing_items = lambda mp: ([], [])
g.wealth = 5_000_000
st.check_needed_items = True
fp = path_from_route(w, (1, 1), w.route((1, 1), (1, 2), level=55) or [], name="Go to 1/2")
fp.resolved = True
b.start_path(fp, loop=False, checked=False)
check(f"no bank can cover it: @status says the fare ({b.no_route_msg!r})", b.no_route_msg.startswith("Not walking")
      and "7,000,000" in b.no_route_msg)
s.trips.go = True
b.start_path(fp, loop=False, checked=False)
check(f"off to the bank: no stale door reason ({b.no_route_msg!r})", b.no_route_msg == "")
s.trips = real_trips
del b.path_toll, b.missing_items

# --- m14c M14C-3: the HP wall named when it's what keeps you from a key
num = next(n for n, it in w.items.items() if (it.get("name") or "").lower() == "large brass key")
w.char = dict(w.char or {}, max_hp=390)
g.candidates = [(14, 3541)]
why = b.errands._hp_wall_why([num])
check(f"L30 thief (390 HP), large brass key: {why}", why and "14/8542" in why and "390" in why)
w.char["max_hp"] = 403
check("403 HP: not the HP wall", b.errands._hp_wall_why([num]) is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
