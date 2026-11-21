"""Route sweep, 2026-10-28 (tests/sweep_report.txt) and Dan's calls on it:
- the 'as if you had every key' fallback walked 14 Go tos through Black Wasteland — avoided areas get asked about
- a door you can pick or bash yourself ('[or 91 picklocks/strength]', the Crimson Fortress) is bashed, not a key run
- Seher'Sahham's shortcut (the king crab claw opens 16/2141: ~226 rooms with the fetch instead of 324) is taken"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47; st.auto_get_items = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = T(); s._entered = True
g, b, w = s.state, s.bot, s.world
g.level, g.max_hp, g.hp, g.picklocks, g.strength = 47, 830, 830, 182, 80
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def at(room, carrying="astral staff (Weapon Hand), log raft"):
    b.stop("x"); b.errands.cancel(); b._shortcut_no = {}; b._trip_allow = {}; b._trip_deny = {}
    g.candidates = [room]; g.carrying = carrying; g.keys = ""; g.inv_seq += 1
# doors
ex = w.room((15, 1053)).exits["S"]
check(f"Crimson Fortress gate ({ex.etype}): picklocks 182 → bash/pick it, no key run", b.door_doable(ex) is True)
ex2 = w.room((15, 1095)).exits["S"]
check(f"a 1000-strength key door ({ex2.etype}) isn't", b.door_doable(ex2) is False)
# avoided areas: the key fallback asks, and doesn't go when no one's there to answer
av = b.avoid_set()
at((1, 1))
b.goto((15, 1054))
crossed = b.path and any(x.room in av or x.dest in av for x in b.path.steps)
check(f"Go to the Crimson Fortress gate doesn't cut through Black Wasteland unasked "
      f"({b.path and len(b.path.steps)} steps; {b.no_route_msg[:80]})", not crossed)
asked = []
at((1, 1))
b.goto((15, 1054), ask=lambda short, long, area: asked.append(area) or True)
# Dan, 2026-11-11: the gate bashes at ~90 strength, and its dirty obsidian key is a witchunter's quest ('ask witchunter'
# in a town shop on another map) — never a key run for it. Picklocks 182: walk there and bash/pick the gate.
ea = b.errands.active
via_key = bool(ea and ea.get("then") and ea["then"][0] and not any(x.room in av or x.dest in av
                                                                   for x in ea["then"][0].steps))
check(f"no key run for the bashable Crimson Fortress gate ({ea and [w.item_name(t['num']) for t in ea['todo']]})",
      not (ea and any(t["num"] == 1076 for t in ea["todo"])))
check(f"…with someone to ask, it asks — or takes a way that doesn't cross it ({asked}, key run: {via_key})",
      asked or via_key or (b.path and not any(x.room in av for x in b.path.steps)))
# Seher'Sahham shortcut
at((1, 1))
b.goto((16, 2666))
todo = (b.errands.active or {}).get("todo") or []
check(f"Seher'Sahham: fetches the king crab claw for the shortcut ({[w.item_name(t['num']) for t in todo]})",
      any(w.item_name(t["num"]) == "king crab claw" for t in todo))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
