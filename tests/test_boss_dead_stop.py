"""0.8.189 (realm walk sweep): a wandering boss has a row of rooms on MME's map — the Bloody Executioner, 17/590-594
on the Winding Trail. Killed in the first, the walk still stopped before each of the others ("Stopped before Bloody
Executioner — Alt+R to go in"), so an unattended Go to just stood there. A boss that's dead by its own clock (the
Bosses tab: killed, not due back yet) isn't stopped for, or walked round; one that's due back is, as before."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ["MUDPILOT_DATA_DIR"] = tempfile.mkdtemp(prefix="mudpilot_test_boss_dead_")
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
st.stop_before_boss = True; st.boss_stop_pct = 0          # stop for any boss
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
s.on_alert = lambda m: None
b, w = s.bot, s.world
s.state.max_hp = 715
ex = w.monster_names.get("bloody executioner")
rooms = sorted(k for k, bs in w.bosses_by_room().items() if any(x is ex for x in bs))
check(f"the Bloody Executioner has a row of rooms ({rooms[:6]})", len(rooms) >= 3)
r1, r2 = rooms[0], rooms[1]
check("alive (no clock): Go to stops before its rooms", b._boss_stops(r1) and b._boss_stops(r2))
s.bosses.record_kill(ex)
check(f"killed: not stopped for in its other rooms ({s.bosses.status(ex['num'])[0]})",
      not b._boss_stops(r2) and not b._boss_stops(r1))
step = Step(w.room(r1).mega_hash, 0, "N", [], r1, r2)
b._goto_target = (1, 1)
check("…and the walk doesn't hold before them", not b._boss_ahead(step) and not getattr(b, "_boss_hold", None))
# due back: stopped for again
s.bosses.rec(ex)["dead_since"] = time.time() - s.bosses.respawn_secs(ex["num"]) - 60
check("due back by its clock: stopped for again", b._boss_stops(r2) and b._boss_ahead(step))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
