"""0.8.226 (Dan: "wall it off"): a boss you'd stop before is a wall for routing — any way round, however long, unless
that boss's room is where you're going. Miserable PVE's Go to the Great Pyramid went through the Crazed Inquisitor's
Command Room because the Khazarad way was 160 rooms longer than the 'about as short' rule allowed; the every-key
fallback didn't go round bosses at all. A boss you'd just fight keeps the 'about as short' rule."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_boss_wall"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
st.stop_before_boss = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
g.level, g.wealth = 55, 5000000
g.carrying, g.keys = "rope and grapple", ""
g.candidates = [(1, 1)]
s.route_char()
start, goal = (1, 1), (6, 1334)
base = w.route(start, goal, level=55, have=b.held_items() or set())
check(f"a way {start} → {goal} ({len(base) if base else None} rooms)", base)
# a room on it whose way round is much more than a quarter longer
boss_room, long_way = None, None
for ex in base[3:-3]:
    alt = w.route(start, goal, level=55, have=b.held_items() or set(), avoid=frozenset({ex.to}))
    if alt and len(alt) > len(base) + max(20, len(base) // 4):
        boss_room, long_way = ex.to, alt
        break
check(f"a room whose way round is long ({boss_room}: {len(long_way) if long_way else None} vs {len(base)})", boss_room)
kind = {"stop": True}
b._boss_area = lambda rooms, goals: set(rooms)
b._boss_stops = lambda dest, easy_too=False: ([{"name": "Test Boss"}] if dest == boss_room and (kind["stop"] or easy_too)
                                              else [])
b._boss_avoids = lambda dest: b._boss_stops(dest, easy_too=True)
r = b._boss_free_route(start, goal, base)
check(f"a boss you'd stop for: the long way round is taken ({len(r)} rooms)",
      r and not any(ex.to == boss_room for ex in r[:-1]) and len(r) > len(base))
r = b._boss_free_route(start, boss_room, base[:[e.to for e in base].index(boss_room) + 1])
check("…unless the boss's room is where you're going", r and r[-1].to == boss_room)
kind["stop"] = False
r = b._boss_free_route(start, goal, base)
check("a boss you'd just fight: still the 'about as short' rule (walks through)", r is base)
kind["stop"] = True
kr = b.keyed_route(start, goal)
check(f"the every-key fallback goes round it too ({len(kr) if kr else None})",
      kr and not any(ex.to == boss_room for ex in kr[:-1]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
