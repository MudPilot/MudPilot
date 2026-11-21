"""0.8.167 (Evolution's log, 2026-11-09):
1. 'You cannot afford wooden skiff.' then "You don't have wooden skiff to give!" — and it logged 'Gave a wooden skiff
   to Revolution'. The hand-over now reads what the game says back: no cash → the bank or don't go; nothing to give →
   buy again; 'You give log raft to Buddy.' → given; '<name> cannot accept your offer' (even after the prompt) →
   @makeroom and give again.
2. 'asked twice already — walking on' walked to the Ancient Ruin with no rafts; 'no shop sells it' stood idle after
   the crimson mist. Now: don't go, say why — a boss hunt / a Go to off a loop goes back to the loop.
3. 'use silverm' (5 uses a day) got learned as a way to the Pier and Go to spent it. Never planned now.
4. A Go to you start (the Goto button/dialog, @goto) turns Hands off off, like Rego."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from types import SimpleNamespace
from mudpilot import config, errands
from mudpilot.session import Session
from mudpilot.megamud_files import MPath, Step
from mudpilot.worlddb import Exit
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def __init__(self): self.sent = []
    def send_line(self, x): self.sent.append(x)
    def close(self): pass
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet = Tel(); s._entered = True
b, er, g, w = s.bot, s.bot.errands, s.state, s.world
logs = []
b.log = lambda m, *a, **k: logs.append(m)
s.log = lambda m, *a, **k: logs.append(m)
b.ready = lambda *a, **k: True
b.set_mode = lambda m: None
raft = w.item_names["log raft"]["num"]
pier = (1, 1813)
g.candidates = [pier]
sent = s.telnet.sent

def errand(who, then=(None, False), after=None, target=None):
    er.active = {"todo": [{"kind": "shop", "num": raft, "room": pier, "for": who, "what": "the pier"}],
                 "then": then, "started": time.time(), "at": None, "tries": 0, "after": after, "target": target}
    return er.active["todo"][0]

# ---------------------------------------------------------------- 1. the hand-over
cur = errand("Revolution")
er.tick()
check(f"buys ({sent[-1:]})", sent[-1:] == ["buy log raft"])
b.note_line("You cannot afford log raft.")
check("'You cannot afford' noted", cur.get("broke"))
gave_up = []
real_give_up = b.give_up
b.give_up = lambda why, *a: gave_up.append(why)
er._bank_for = lambda c, a: False
er.tick()
check(f"no cash, no bank: doesn't go, says why ({gave_up[-1:]})", gave_up and "can't afford" in gave_up[-1])
check("…and never logged 'Gave'", not any(m.startswith("Gave a") for m in logs))
cur = errand("Revolution")
er._bank_for = lambda c, a: True
er.tick(); b.note_line("You cannot afford log raft."); er.tick()
check(f"no cash, a bank near: the bank first ({logs[-1]})", "to the bank first" in logs[-1])
del er._bank_for

cur = errand("Buddy")
er.tick(); cur["bought"] -= 5; er.tick()
check(f"gives ({sent[-1]})", sent[-1] == "give log raft to Buddy")
b.note_line("You don't have log raft to give!")
er.tick()
check(f"'You don't have it to give': buys again ({logs[-1]})", "buying it again" in logs[-1] and not cur.get("given"))
er.tick()
check(f"…buy sent ({sent[-1]})", sent[-1] == "buy log raft")
cur["bought"] -= 5; er.tick()
b.note_line("You don't have log raft to give!"); er.tick()
er.tick(); cur["bought"] -= 5; er.tick()
b.note_line("You don't have log raft to give!"); er.tick()
check(f"…not bought after {errands.SHOP_TRIES} tries: doesn't go ({gave_up[-1:]})",
      gave_up and "couldn't buy a log raft for Buddy" in gave_up[-1])

cur = errand("Buddy")
er.tick(); cur["bought"] -= 5; er.tick()
b.note_line("You give log raft to Buddy.")
er.tick()
check(f"'You give log raft to Buddy.': given straight away ({logs[-1]})", logs[-1] == "Gave a log raft to Buddy")

cur = errand("Buddy")
er.tick(); cur["bought"] -= 5; er.tick()
b.note_line("[HP=368/MA=299]:Buddy cannot accept your offer.")
er.tick()
check(f"refusal after the prompt on the same line: @makeroom ({sent[-1]})", sent[-1] == "/Buddy @makeroom log raft")
b.give_up = real_give_up

# ---------------------------------------------------------------- 2. not walking without it
def mpath(title, room):
    return MPath(name=title, author="", start_hash="a", end_hash="a" if "Go to" not in title else "b",
                 steps=[Step("x", 0, "N", room=room, dest=room)], resolved=True)
loop = mpath("Rotting Glade Full", (17, 183))
s.comeback.leading = lambda: True
g.party = {"Evolution": {}, "Revolution": {}}
b.carry_pick = lambda items, own=True: raft
ruin = mpath("Go to 3/588 Ancient Ruin", (1, 1813))
b.after_goto, b._goto_target = loop, (3, 588)
er._rounds[ruin.title] = (2, time.time())
stopped, started, gotos = [], [], []
b.stop = lambda why="Stopped": stopped.append(why)
b.start_path = lambda mp, loop=None, checked=False: started.append((mp.title, loop))
b.goto = lambda t, then=None, ask=None: gotos.append((t, getattr(then, "title", None))) or True
held = er.party_check(ruin, False, [frozenset({raft})])
check("asked twice already: holds the walk (no 'walking on')", held and not any("walking on" in m for m in logs))
b._gave_up_at = 0
er.tick()
check(f"…then doesn't go and says why ({stopped[-1:]})", stopped and "Not walking 'Go to 3/588" in stopped[-1]
      and "asked the party twice" in stopped[-1])
check(f"…and goes back to the loop ({gotos[-1:]} {started[-1:]})",
      (gotos and gotos[-1] == ((17, 183), "Rotting Glade Full")) or (started and started[-1][0] == "Rotting Glade Full"))

# _asking_tick 'no shop sells it' on the Go to back to the loop: the loop is where it was going — stop, say why
home = mpath("Go to 17/183 Rotting Glade, Trail", (3, 605))
g.candidates = [(3, 605)]
er.asking = {"mp": home, "loop": False, "picks": [raft], "sets": [frozenset({raft})], "t": time.time() - 99,
             "ans": {("Revolution", raft): False}, "q": {"Revolution": []}, "after": loop, "target": (17, 183)}
er.source_for = lambda *a, **k: None
stopped.clear(); gotos.clear(); started.clear()
b._gave_up_at = 0
er.tick()
check(f"no shop: stops with the reason, no idle 'Stopped' without one ({stopped[-1:]})",
      stopped and "no shop we can get to sells it" in stopped[-1] and not gotos and not started)

# a boss hunt: given up, back to its loop
er.asking = {"mp": ruin, "loop": False, "picks": [raft], "sets": [frozenset({raft})], "t": time.time() - 99,
             "ans": {("Revolution", raft): False}, "q": {"Revolution": []}, "after": None, "target": (3, 588)}
done = []
s.bosshunt.active = {"num": 1, "back": (loop, True)}
s.bosshunt._done = lambda why: done.append(why)
b._gave_up_at = 0
er.tick()
check(f"boss hunt: the hunt is given up (back to its loop) ({done})", done and "not going" in done[0])
del er.source_for
s.bosshunt.active = None

# an errand that can't buy, on a Go to off a loop: back to the loop
stopped.clear(); gotos.clear(); started.clear()
g.candidates = [pier]
er.active = {"todo": [{"kind": "shop", "num": raft, "room": pier, "what": "the pier"}], "then": (ruin, False),
             "started": time.time(), "at": 0, "tries": errands.SHOP_TRIES, "after": loop, "target": (3, 588),
             }
er.active["todo"][0]["roomed"] = True
er._bank_for = lambda c, a: False
s.remote.making_room = lambda: False
b._gave_up_at = 0
er.tick()
check(f"couldn't buy: back to the loop ({stopped[-1:]} {gotos[-1:]})",
      stopped and "couldn't buy" in stopped[-1] and "back to Rotting Glade Full" in stopped[-1]
      and gotos and gotos[-1][1] == "Rotting Glade Full")

# ---------------------------------------------------------------- 3. the token of Silvermere
check("'use silverm' is the token of Silvermere (limited uses)", w.limited_use_item("use silverm") == "token of Silvermere")
check("…not learned as a way", not w.add_learned((6, 3109), "use silverm", pier))
logs.clear()
s.learn_exit((6, 3109), "use silverm", pier)
check(f"…learn_exit says why ({logs[-1:]})", logs and "limited uses" in logs[-1])
r = w.rooms[(6, 3109)]
tok = Exit("@use silverm", pier, "(Text: use silverm)", False, False, "text")
r.exits = {**r.exits, "@use silverm": tok}
w.forget_routes()
check("…an exit that spends it is never planned", not w.can_use(tok, level=50, have=set()))
rt = w.route((6, 3109), pier, level=50)
check(f"…and a route doesn't use it ({len(rt) if rt else rt} steps)", not rt or tok not in rt)
check("a one-shot the carry check buys (potion of levitation) still plans",
      w.limited_use_item("use potion of levitation", single=False) == "")

# ---------------------------------------------------------------- 4. Go to clears Hands off
st.hands_off = True
logs.clear()
check("hands_on: was on", s.hands_on("You started a Go to"))
check(f"…off now, and said ({logs[-1:]})", not st.hands_off and "Hands off is off" in logs[-1])
st.hands_off = True
b._planning = False
import mudpilot.bgplan as bgplan
bgplan.plan = lambda *a, **k: None
s.remote._goto_bg("Dan", (1, 1813), "the Pier")
check("@goto turns Hands off off", not st.hands_off)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
