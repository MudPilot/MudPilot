"""0.8.190 (Dan, "fix both"): a locked door's '[N picklocks/strength]' is compared with your picklocks and strength when
planning — leading, with the party's best picker / basher (party sync). One nobody can beat (and no key) costs a lot,
so another way is used when there is one, instead of walking there and stopping at "the door is locked" (the sweep:
14/332 Harbor Road Gate, '[61 picklocks/strength]', strength 60). 8/489 south is a 61 door with a 6-room way round."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_door_power"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w, g = s.bot, s.world, s.state
g.level = 55
door = w.room((8, 489)).exits["S"]
to = door.to
def through(r):
    return bool(r) and r[0].dir == "S" and len(r) == 1
s.route_char()
check(f"strength / picklocks not known: as before, through the door ({w.char.get('door_power')})",
      w.char.get("door_power") is None and through(w.route((8, 489), to, level=55)))
g.strength, g.picklocks = 60, 0
s.route_char()
r = w.route((8, 489), to, level=55)
check(f"strength 60 against [61]: the way round ({len(r) if r else None} rooms)", r and not through(r))
check(f"…the door costs {w.exit_cost(door)} (a wall unless there's no other way)", w.exit_cost(door) >= w.DOOR_WALL)
g.strength = 61
s.route_char()
check("strength 61: through it", through(w.route((8, 489), to, level=55)))
g.strength, g.picklocks = 0, 80
s.route_char()
check("picklocks 80 (no strength): picked, through it", through(w.route((8, 489), to, level=55)))
g.strength, g.picklocks = 50, 0
g.party = {"Tester": {}, "Bruiser": {}}
s.partysync.info = lambda: {"Bruiser": {"str": 90}}
s.partysync.members = lambda: ["Bruiser"]
s.route_char()
check(f"leading, a member with strength 90 bashes it: through ({w.char.get('door_power')})",
      w.char.get("door_power") == (0, 90) and through(w.route((8, 489), to, level=55)))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
