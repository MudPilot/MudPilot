"""0.8.189 (realm walk sweep): Silvermere → Dark-Elf City needs the black star key, the gate key (the obsidian statue
at the Black Steel Gate, 8/461) and the bloodstone orb ('ask commander orb', 8/459) — and the statue is past the
orb's door (8/398 south, 'rub bloodstone orb'). The fetches went key, statue, orb: the walk to the statue stopped at
8/398 ("no exit s") without the orb. The every-key fallback that lets a fetch plan through doors you pick was also
counting on the orb still to be fetched. Now the orb comes before the statue."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_errand_order"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 45   # (0.8.225: under 50, where the Negative Power Plane is still avoided — at 55 the way goes through it)
st.char_class, st.char_race, st.char_alignment = "Mage", "Human", "Good"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
g.level, g.wealth = 45, 5000000
g.carrying, g.keys = "golden idol, rope and grapple", ""
g.candidates = [(1, 1)]
s.route_char()
name = lambda n: w.item_name(n)
orb = next(n for n, it in w.items.items() if it.get("name") == "bloodstone orb")
gate = next(n for n, it in w.items.items() if it.get("name") == "gate key")
r = b.plan_route((1, 1), (8, 559))
check(f"a way to Dark-Elf City ({len(r) if r else None} rooms)", r)
mp = path_from_route(w, (1, 1), r or [], name="Go to 8/559 Dark-Elf City, Moatside")
need = [n for n, soft in b.path_needs(mp) if not soft or n == gate]
check(f"it needs the orb and the gate key ({[name(n) for n in need]})", orb in need and gate in need)
okp, why = b.errands.plan(mp, False, [n for n, soft in b.path_needs(mp) if n not in (b.held_items() or set())])
todo = [t["num"] for t in (b.errands.active or {}).get("todo", [])]
check(f"the fetches are planned ({okp}, {why}; {[name(n) for n in todo]})", okp and todo)
check("…the orb before the gate key's statue (it's past the orb's door)",
      orb in todo and gate in todo and todo.index(orb) < todo.index(gate))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
