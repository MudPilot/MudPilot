"""Boss hunt: a ticked boss comes due → leave the loop, kill it, go back to the loop."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, bosses
from mudpilot.session import Session
bosses.BOSS_FILE_OVERRIDE = os.path.join(config.DATA_DIR, "test-bosshunt.json")
try: os.remove(bosses.BOSS_FILE_OVERRIDE)
except OSError: pass
st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
s.bosses.load()
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w = s.bot, s.world
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
mon = next(m for m in w.monsters.values() if m.get("boss") and m.get("regen_h") and m.get("spawn_rooms") and (m.get("exp") or 0) > 100)
class P:  # a stand-in loop
    title = "My loop"; steps = []; is_loop = True; resolved = True
loop = P()
b.walking, b.loop, b.path = True, True, loop
s.state.candidates = [next(iter(w.rooms))]
s.state.max_hp = s.state.hp = 500
calls = []
b.plan_route = lambda a, c, ask=None: [1] * 10
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title, loop)) or True
rec = s.bosses.rec(mon)
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
rec["kills"] = [{"t": rec["dead_since"], "by": "you", "room": list(mon["spawn_rooms"][0])}]
s.bosses.save()
s.bosshunt.tick()
check("not ticked for hunting → stays on the loop", not calls)
rec["hunt"] = True
s.bosshunt.tick()
check(f"due + ticked → walks to it ({calls})", calls and calls[0] == ("goto", tuple(mon["spawn_rooms"][0])))
check("stop-before-boss lets it in", b._boss_ok == tuple(mon["spawn_rooms"][0]))
# killed it
s.bosses.record_kill(mon)
b.walking = False
s.bosshunt.tick()
check("killed → grabs the loot first", s.bosshunt.active and s.bosshunt.active["killed"])
s.bosshunt.active["killed"] -= 10
s.bosshunt.tick()
check(f"killed → back to the loop ({calls})", calls[-1] == ("loop", "My loop", True) and s.bosshunt.active is None)
calls.clear()
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
b.walking = True
rec["hunt_tried"] = rec["dead_since"]
s.bosshunt.tick()
check("only once per spawn", not calls)
rec["hunt_tried"] = None
s.bosshunt.tick()
s.state.candidates = [list(w.rooms)[5]]
b.walking = False; b.status = "Stopped by you"
s.bosshunt.active["t"] = time.time() - 10
s.bosshunt.tick()
check("you stopped it → no dragging back to the loop", s.bosshunt.active is None and not any(c[0] == "loop" for c in calls))
b.plan_route = lambda a, c, ask=None: [1] * 500
rec["hunt_tried"] = None; b.walking = True; calls.clear()
s.bosshunt.tick()
check("too far → doesn't go", not calls)
# boss farm: standing somewhere → goes for the due boss, then back to where it was
b.plan_route = lambda a, c, ask=None: [1] * 10
st.boss_farm_on = True
spot = list(w.rooms)[7]
s.state.candidates = [spot]
b.walking, b.loop, b.path = False, False, None; b.status = "Arrived"
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
rec["hunt_tried"] = None; calls.clear()
s.bosshunt.tick()
check(f"boss farm: standing still → goes to kill it ({calls})", calls and s.bosshunt.active and not s.bosshunt.active["back"])
s.bosses.record_kill(mon); s.bosshunt.tick(); s.bosshunt.active["killed"] -= 10
s.state.candidates = [tuple(mon["spawn_rooms"][0])]; calls.clear()
s.bosshunt.tick()
check(f"…then back to where it was ({calls})", calls == [("goto", spot)])
os.remove(bosses.BOSS_FILE_OVERRIDE)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
