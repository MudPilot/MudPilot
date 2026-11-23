"""0.8.223 party fixes (Dan's picks 1-3 from bug_hunt/HUNT_1121.md "For Dan"):
1. An errand's own walk asks the party '@have' (rafts, idol) like a normal Go to, and keeps the errand (party3 #2);
   not on the walk to the shop buying theirs. The party's items no shop sells are asked about before your own
   errand (party3 #4).
2. A door only a follower can pick / bash: they're asked ('@do pick south'), the tries are paced on them, not on the
   instant "locked" answers (partyB P4, party3 D3, partyA #4). A key that turns up at its door gets used (partyA #5).
3. Refusals name the member: "Buddy's whole max HP", "Druids only — Revolution (Mage) can't go through" (partyA D4,
   partyB P3/P5)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
from mudpilot import errands as errands_mod
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 40
st.auto_get_items = True; st.check_needed_items = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
s.on_no_route = lambda m: None
w, b, g, er = s.world, s.bot, s.state, s.bot.errands
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def path(title, steps):
    return type("P", (), {"steps": steps, "title": title, "is_loop": False, "filename": "", "needed_item": "",
                          "resolved": True})()


RAFT, IDOL, KEY = 690, 1281, 593
g.level, g.max_hp, g.hp, g.max_hp_read = 40, 700, 700, True
g.party = {"Tester": {}, "Buddy": {}}
s.comeback.leading = lambda: True
b.x.leading = lambda: True
shop = {"kind": "shop", "room": (1, 1813), "dist": 12, "what": "sold: Boat Launch"}
er.source_for = lambda n, *a, **k: None if n == IDOL else dict(shop, num=n)
real_carry_sets, real_missing = b.carry_sets, b.missing_items

# ---- 1a. an errand's own leg asks the party @have, and keeps the errand
outer = path("Go to 16/317 Armour Shop", [Step("N", 0, "N", [], (1, 1), (1, 2))])
er.active = {"todo": [{"num": KEY, "kind": "monster", "room": (1, 2342), "what": "drop: king crab", "dist": 0}],
             "then": (outer, None), "started": time.time(), "at": None, "tries": 0, "after": None,
             "target": (16, 317)}
b.carry_sets = lambda mp: [frozenset({RAFT})]
b.missing_items = lambda mp: ([], [])
b.path_toll = lambda mp: 0
b._goto_target = (1, 2342)
leg = path("Go to 1/2342 Sandbar", [Step("S", 0, "S", [], (1, 1), (1, 2342))])
sent.clear()
b.start_path(leg)
check(f"errand leg: asks the party @have ({sent})", "/Buddy @have log raft" in sent and not b.walking)
check("…as the errand's leg", er.asking and er.asking.get("leg") and er.asking["gmp"] is outer)
er.have_answer("Buddy", "{no log raft}")
er.tick()
a = er.active or {}
check(f"Buddy has none: a raft bought for him first, then on with the errand ({[t.get('for') or t['num'] for t in a.get('todo', [])]})",
      a.get("then", (None,))[0] is outer and a["todo"][0].get("for") == "Buddy" and a["todo"][1]["num"] == KEY)
check("…the errand keeps its Go to's target", a.get("target") == (16, 317))

# ---- 1b. the walk to the shop buying theirs isn't asked again
held = []
b.partyflags.check = lambda mp, loop: held.append(mp) or True
sent.clear()
b.start_path(path("Go to 1/1813 Pier", [Step("S", 0, "S", [], (1, 1), (1, 1813))]))
check(f"the walk to the shop for Buddy's raft: no @have ({sent})", not [c for c in sent if "@have" in c] and held)

# ---- 1c. the idol nobody can buy is asked about before your own errand
er.cancel(); er._rounds.clear(); er.known_have.clear()
planned = []
real_plan = er.plan
er.plan = lambda mp, loop, missing, near=None: planned.append(list(missing)) or (True, "")
b.carry_sets = lambda mp: [frozenset({IDOL})]
b.missing_items = lambda mp: ([KEY, IDOL], [])
b._goto_target = (16, 317)
main = path("Go to 16/317 Armour Shop", [Step("N", 0, "N", [], (1, 1), (16, 317))])
sent.clear()
b.start_path(main)
check(f"party Go to past the idol teleport: the party's asked about the idol first ({sent})",
      "/Buddy @have golden idol" in sent and not planned)
check("…a round that plans the walk again after", er.asking and er.asking.get("recheck"))
er.have_answer("Buddy", "{yes: golden idol}")
er.tick()
check(f"Buddy has one: now the errand for your own key ({planned})", planned and KEY in planned[0])
er.cancel(); er._rounds.clear(); er.known_have.clear(); planned.clear()
sent.clear()
b.start_path(main)
er.asking["t"] -= errands_mod.ASK_SECS + 1           # (Buddy never answers)
er.tick()
check(f"nobody says yes: refused up front, no errand walked ({planned}; {b.status[:90]})",
      not planned and "golden idol for Buddy" in b.status)
er.plan = real_plan
er.source_for = lambda n, *a, **k: None              # (the door's key: nowhere to get one — partyB P4)
b.carry_sets, b.missing_items = real_carry_sets, real_missing
del b.path_toll
er.cancel(); er._rounds.clear(); er.known_have.clear()
b.stop("Stopped by you")
del b.partyflags.check

# ---- 2. a picklocks-only door Buddy can pick (2/176 S '[or 81 picklocks]'), the leader can't
door = (2, 176)
ex = w.room(door).exits["S"]
g.candidates = [door]; g.picklocks, g.strength = 0, 40
g.carrying, g.keys = "vortex staff (Weapon Hand)", ""; g.inv_seq += 1
s.partysync.command("Buddy", "me lvl=40 str=40 pick=120 hp=300 cls=Thief")
s.partysync.members = lambda: ["Tester", "Buddy"]
s.partysync.peers["Buddy"]["t"] = time.time()
g.view = RoomView(w.room(door).name, {"N", "S"}, [], [], ["Buddy"], time.time(), closed={"S"})
fetched, rounded = [], []
b._fetch_door_key = lambda room, d, ex_: fetched.append(d) or False
b.route_around = lambda here_, d, why: rounded.append(why) or False
b.walking, b.path, b.idx = True, path("Go to 2/2519", [Step("S", 0, "S", [], door, ex.to)]), 0
b._lock_tries, b._lock_room, b._unlocked, b._help_door = {}, door, None, None


def tick(n=1):
    for _ in range(n):
        b._door_wait_until = 0
        g.pending.clear()
        b._step_sent_at = 0
        if b._locked_dir is None:
            b._locked_dir = "S"                      # ("The door is locked." came back at once)
        b.walk([], True)


sent.clear(); b._cool.clear()
tick(12)
check(f"the follower who can pick it is asked ({[c for c in sent if '@do' in c]})",
      any(c.startswith("/Buddy @do pick south") for c in sent))
check(f"…12 instant 'locked' answers don't use the tries up: no key errand, no going round ({fetched}, {rounded})",
      not fetched and not rounded and b.walking)
check(f"…the leader tries 'open', paced ({sent.count('open south')})", 1 <= sent.count("open south") <= 2)
check(f"…and never bashes it ({[c for c in sent if 'bash' in c]})", not [c for c in sent if "bash" in c])
b._help_door["t0"] -= b.HELP_SECS + 1
tick(3)
check(f"after a minute: round it once, no 'quest item?' key errand ({rounded}, {fetched})",
      len(rounded) == 1 and not fetched)
check("…the only way: they keep at it", any("only way" in l for l in s.logs[-10:]) and b.walking)
b._help_door["t0"] -= b.HELP_MAX
tick()
check(f"…3 minutes: stopped, saying who couldn't ({b.status[:90]})", not b.walking and "Buddy" in b.status)
# Buddy bashes it open meanwhile: the walk goes through
b.walking, b.idx, b._help_door, b._locked_dir = True, 0, None, None
sent.clear(); tick()
b._opened = (g.view_seq, "S")
b._locked_dir = "S"; b._door_wait_until = 0
b.walk([], True)
check("door opened by the helper: no more waiting on it", b._help_door is None)
# nobody to ask (Buddy isn't here): as before after a short wait
b.walking, b.idx, b._help_door, b._locked_dir = True, 0, None, None
b._bash_help = None
g.view = RoomView(w.room(door).name, {"N", "S"}, [], [], [], time.time(), closed={"S"})
sent.clear(); tick()
b._help_door["t0"] -= b.HELP_ASK_WAIT + 1
tick(3)
check(f"helper not here: the usual tries go on after a short wait ({fetched or rounded})", fetched or rounded)

# ---- 2b. a key that turns up at its door is used (partyA #5, 1/1224 E black star key)
b.stop("Stopped by you")
g.party = {"Tester": {}}
door2 = (1, 1224)
ex2 = w.room(door2).exits["E"]
g.candidates = [door2]
g.view = RoomView(w.room(door2).name, {"N", "S", "E"}, [], [], [], time.time(), closed={"E"})
b.walking, b.path, b.idx = True, path("Go to 1/1313", [Step("E", 0, "E", [], door2, ex2.to)]), 0
b._lock_room, b._unlocked, b._help_door = door2, None, None
b._lock_tries = {"E": 1}                            # ('open east' tried before the key came)
g.keys = "black star key"; g.inv_seq += 1
sent.clear()
b._locked_dir = "E"; b._door_wait_until = 0; g.pending.clear()
b.walk([], True)
check(f"the key that just arrived is used ({sent})", "use black star key east" in sent)
b.stop("Stopped by you")
g.keys = ""; g.inv_seq += 1

# ---- 3. wording
g.party = {"Tester": {}, "Buddy": {}}
s.partysync.command("Buddy", "me lvl=40 str=40 pick=120 hp=90 cls=Thief")
s.route_char()
check(f"route_char: the weakest HP is Buddy's ({w.char.get('max_hp')}, {w.char.get('max_hp_who')})",
      w.char.get("max_hp") == 90 and w.char.get("max_hp_who") == "Buddy")
bl = w.why_no_route((8, 1835), (8, 1831), level=40, have=set())
check(f"…the refusal says Buddy's whole max HP ({bl[:1]})",
      any("Buddy's whole max HP (90)" in why for _r, _d, why in bl))
w.char = dict(w.char, max_hp=156, max_hp_who=None)
bl = w.why_no_route((8, 1835), (8, 1831), level=40, have=set())
check(f"…yours when it's yours ({bl[:1]})", any("your whole max HP (156)" in why for _r, _d, why in bl))
gate = w.room((16, 1001)).exits["N"]
w.char = dict(w.char, **{"class": 13, "party_classes": [12], "party_names": ["Revolution"]})
check(f"class gate names the follower ({w.gate_why(gate)})", w.gate_why(gate) == "Druids only — Revolution (Mage) can't go through")
w.char = dict(w.char, **{"party_classes": [13]})
check("…nothing to say when everyone may pass", w.gate_why(gate) is None)
al = w.room((1, 1322)).exits["N"]
w.char = dict(w.char, align="Good", party_aligns=["Villain"], party_names=["Bob"])
check(f"alignment gate names the follower ({w.gate_why(al)})", w.gate_why(al) == "Saint to Neutral only — Bob (Villain) can't go through")
w.char = dict(w.char, align="Fiend", party_aligns=["Villain"])
check(f"…and you, when it's you too ({w.gate_why(al)})", w.gate_why(al) == "Saint to Neutral only — you (Fiend) and Bob (Villain) can't go through")
bar = w.room((14, 237)).exits["@ask barmaid adventure"]
w.char = dict(w.char, **{"class": 9, "party_classes": [1], "party_names": ["Revolution"]})
check(f"barmaid: names who isn't a Bard ({w.req_who_bits(bar.req)})", w.req_who_bits(bar.req) == ["Bard (Revolution (Warrior) isn't)"])

del er.source_for

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
