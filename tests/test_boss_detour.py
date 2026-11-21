"""0.8.183 (Dan, 2026-11-12): a Go to to Tidepool rowed out to the Pirate Galleon, walked the deck past Captain Flintlock
(stop before boss room) and jumped back to the beach; the shore way is no longer. A way round a stop-before boss's
area is taken when it isn't much longer; going to the boss itself still goes straight there."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
g, b, w = s.state, s.bot, s.world
g.max_hp = 600
gal = {k for k, r in w.rooms.items() if r.name.startswith("Pirate Galleon")}
boss_rooms = [k for k in gal if w.bosses_by_room().get(k)]
check(f"the galleon has a boss room ({boss_rooms[:3]})", bool(boss_rooms))
b._boss_stops = lambda dest, **k: [{"name": "Captain Flintlock"}] if dest in boss_rooms else []
# the shore and the galleon are a tie (32 steps each) — which the map picks varies; take the galleon on purpose
direct = (w.route((13, 337), (13, 820)) or []) + (w.route((13, 820), (13, 503)) or [])  # row out, the deck, the plank
check(f"the galleon way crosses the ship ({len(direct or [])} steps)", direct and any(x.to in gal for x in direct))
r = b._boss_free_route((13, 337), (13, 503), direct)
check(f"the planner goes round on the shore ({len(r)} steps)", r and not any(x.to in gal for x in r))
check("…and not much longer", len(r) <= len(direct) + max(20, len(direct) // 4))
r2 = b._boss_free_route((13, 337), boss_rooms[0], w.route((13, 337), boss_rooms[0]))
check(f"a Go to the boss itself still goes there ({len(r2 or [])} steps)", r2 and r2[-1].to == boss_rooms[0])
st.stop_before_boss = False
check("stop-before-boss off: still walks round (0.8.185 route-round)", b._boss_free_route((13, 337), (13, 503), direct) is not direct)
st.boss_route_round = False
check("both off: the route is left alone", b._boss_free_route((13, 337), (13, 503), direct) is direct)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
