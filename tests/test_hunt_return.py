"""Evolution, 2026-11-06: stood at 17/183 from 00:51 till 03:10. The crimson mist walk paused a second to ask the
party about rafts 3 min in → 'the walk there stopped'; the guardian golem hunt that came due on the Go to back to
the loop took that Go to as home, arrived, stood; and the old raft check's answer restarted the crimson walk in
the golem's room."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, bosses
from mudpilot.session import Session
bosses.BOSS_FILE_OVERRIDE = os.path.join(config.DATA_DIR, "test-hunt-return.json")
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
class P:
    def __init__(s_, t): s_.title, s_.steps, s_.resolved = t, [], True
loop, home = P("Rotting Glade Full"), P("Go to 17/183 Rotting Glade, Trail")
s.state.candidates = [next(iter(w.rooms))]
s.state.max_hp = s.state.hp = 500
st.boss_hunt_on = True
calls = []
real_goto = b.goto
b.plan_route = lambda a, c, ask=None: [1] * 10
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title, loop)) or True
rec = s.bosses.rec(mon)
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
rec["kills"] = [{"t": rec["dead_since"], "by": "you", "room": list(mon["spawn_rooms"][0])}]
rec["hunt"] = True
s.bosses.save()

# 1. on the Go to back to the loop's start → the hunt's home is the loop
b.walking, b.loop, b.path, b.after_goto = True, False, home, loop
s.bosshunt.tick()
a = s.bosshunt.active
check(f"hunt from the way home: back to the loop ({a and a['back'][0].title})",
      a and a["back"][0] is loop and a["back"][1] is True)

# 2. three minutes in, a moment's stop asking the party about rafts: not 'stopped'
a["t"] = time.time() - 180
b.walking = True; s.bosshunt.tick()
b.walking = False
b.errands.asking = {"mp": home, "loop": False, "q": {"Buddy": [1]}, "t": time.time(), "ans": {}}
s.bosshunt.tick()
check("asking the party → still hunting", s.bosshunt.active is not None)
b.errands.asking = None
s.bosshunt.tick()
check("…and a few seconds stood still after → still hunting", s.bosshunt.active is not None)
a["leg_t"] = time.time() - 25
s.bosshunt.tick()
check("stood still 25 s → gives up, back to the loop", s.bosshunt.active is None)

# 3. a new Go to drops the old walk's @have round
b.goto = real_goto
b.errands.asking = {"mp": home, "loop": False, "q": {"Buddy": [1]}, "t": time.time(), "ans": {}}
s.state.candidates = []
b.goto((1, 1797))
check("a new Go to forgets the old @have round", b.errands.asking is None)

try: os.remove(bosses.BOSS_FILE_OVERRIDE)
except OSError: pass
sys.exit(0 if ok else 1)
