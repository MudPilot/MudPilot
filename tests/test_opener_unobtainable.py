"""0.8.189 (realm walk sweep): solo, a Go to from Silvermere (1/1) to Dark-Elf City (8/559) said "the only way is
through Black Wasteland, which you're avoiding". The way in with every key went over the roofs with the amber
talisman — an item MME has nowhere to get (its dying slaver leader spawns nowhere) — so the whole 'fetch the opener
instead' plan was dropped. Now the item nobody can get is left out and the way without it is used: the Fungus
Tunnel, with the bloodstone orb fetched on the way."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_opener"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
st.char_class, st.char_race, st.char_alignment = "Mage", "Human", "Good"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
g.level, g.wealth = 55, 500000
g.carrying, g.keys = "golden idol, rope and grapple", ""
s.route_char()
talisman = next(n for n, it in w.items.items() if it.get("name") == "amber talisman")
check("the amber talisman has nowhere to come from", b.errands.source_for(talisman, frm=(1, 1)) is None)
avoid = b.avoid_set()
r = b.plan_route((1, 1), (8, 559))
check(f"solo, Silvermere → Dark-Elf City has a way ({len(r) if r else None} rooms)", r)
check("…that keeps out of the avoided areas (Black Wasteland)", r and not any(x.to in avoid for x in r[:-1]))
need = b._route_items((1, 1), r or [], b.held_items() or set())
check(f"…and doesn't need the talisman ({sorted(w.item_name(n) for n in need)})", r and talisman not in need)
check(f"…but the orb, fetched on the way ({[l for l in logs if 'normal way in' in l][:1]})",
      any("bloodstone orb" in l for l in logs if "normal way in" in l))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
