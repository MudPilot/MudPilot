"""0.8.185 (Dan, 2026-11-12): "No reason i should try to afk kill shadow master as i walk from bank to abandoned inn
when it might be 1 room farther out of the way". The bank trip only went round bosses you'd stop before; a level-55
Mage rates Shadow Master easy (under 40% of his HP), so it walked down Haven Street into him. And the way back to the
loop (back_route) didn't look at bosses at all. Both go round any boss you aren't hunting when it's about as short."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55; st.char_class = "Mage"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
g, b, w = s.state, s.bot, s.world
g.max_hp = 10 ** 6                                  # Shadow Master can't do 40% of this: no stop for him
BANK, INN = (17, 2435), (17, 2800)
sm = {k for k, ms in w.bosses_by_room().items() if any(m["name"] == "Shadow Master" for m in ms)}
check(f"Shadow Master's rooms ({sorted(sm)})", (17, 2393) in sm)
check("he's easy: no stop before him", not b._boss_stops((17, 2393)))
raw = w.route(BANK, INN, level=b.route_level(), have=b.held_items() or set(), avoid=b.avoid_set())
# down Haven Street past him is about as short as up through the Town Square (which the map picks can vary): take it
via = (w.route(BANK, (17, 2393)) or []) + (w.route((17, 2393), INN) or [])
check(f"Haven Street past him is about as short ({len(via)} steps vs {len(raw)})", via and len(via) <= len(raw) + 2)
r = b._boss_free_route(BANK, INN, via)
check(f"the bank → inn walk goes round him ({len(r)} steps)", r and not any(x.to in sm for x in r))
check("…and isn't much longer", len(r) <= len(via) + 2)
back = b.back_route(BANK, {INN, (17, 2801)})
check(f"the way back to the loop goes round him too ({len(back)} steps)", back and not any(x.to in sm for x in back))
r2 = b.plan_route(BANK, (17, 2393))
check("a Go to his room still goes there", r2 and r2[-1].to == (17, 2393))
st.boss_route_round = False
r3 = b._boss_free_route(BANK, INN, via)
check("setting off: an easy boss on the way isn't gone round", r3 == via)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
