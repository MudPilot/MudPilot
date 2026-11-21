"""0.8.190 (Dan, "weigh by HP + rest first"): a trap costs the route by what it does against the walker's HP (the
weakest member's max HP in a party), down to the hang-up line — one that could take you there is a wall, used only
when there's no other way; smaller ones scale in between. And the walk rests to full before a trap it couldn't take
with the HP it has. 14/8543 east (Farnholme) is a 400-damage trap with a 39-room way round; 17/2883 west in the
Hedge Maze is a 500-damage one."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_trap_hp"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
from mudpilot.worlddb import Exit
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
trap = lambda n: Exit("N", (1, 1), f"(Trap, {n} damage)", True, False, "trap")
w.char = {}
check(f"HP not known: as before ({w.exit_cost(trap(400))})", w.exit_cost(trap(400)) == 21)
g.max_hp, g.hp, g.level = 715, 715, 55
s.route_char()
check(f"the walker's max HP and hang-up line go to the map ({w.char.get('max_hp')}, {w.char.get('hangup_pct')})",
      w.char.get("max_hp") == 715 and w.char.get("hangup_pct") == 25)
c40, c300, c600 = w.exit_cost(trap(40)), w.exit_cost(trap(300)), w.exit_cost(trap(600))
check(f"a 600-damage trap at 715 HP (hang-up at 25%) is a wall ({c600})", c600 >= w.TRAP_WALL)
check(f"smaller ones scale in between ({c40} < {c300} < {c600})", 1 < c40 < c300 < c600)
s.partysync.info = lambda: {"Weakling": {"hp": 300}}
s.route_char()
check(f"in a party, the weakest member's HP counts ({w.char.get('max_hp')}: 300 → 300 is a wall)",
      w.char.get("max_hp") == 300 and w.exit_cost(trap(300)) >= w.TRAP_WALL)
s.partysync.info = lambda: {}
s.route_char()
to = w.room((14, 8543)).exits["E"].to
r = w.route((14, 8543), to, level=55)
check(f"round the 400-damage trap at 14/8543 E: 39 rooms, no trap ({len(r) if r else None} rooms)",
      r and len(r) > 1 and not any(x.kind == "trap" for x in r))
w.char["max_hp"] = 3000
w.forget_routes()
r = w.route((14, 8543), to, level=55)
check(f"…but at 3000 HP straight through it ({len(r) if r else None})", r and len(r) == 1)
# ---- the walk: rest to full before the trap when the hit would take you under the hang-up line
s.route_char()
ex = w.room((17, 2883)).exits["W"]
mp = path_from_route(w, (17, 2883), [ex], name="Go to 17/2888")
b.path, b.idx = mp, 0
st.auto_rest = True
g.hp = 400
held = b._hurt_ahead(mp.steps[0])
check(f"at 400/715 HP the walk rests to full before the 500 trap ({held}, {b._danger_hp}, {logs[-1:]})",
      held and b._danger_hp == 100 and "resting to full" in (logs[-1] if logs else ""))
b._danger_hp = 0
g.hp = 715
check("at full HP it goes on (it can take it)", not b._hurt_ahead(mp.steps[0]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
