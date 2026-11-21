"""Dan, 2026-10-30: walking to the mummy, the gate (1/1056 N) needs the levers in 1/1038 and 1/1044 pulled and shuts on a
timer — it walked too slowly and the gate closed. Pull each lever in its own room, then run (no fighting, no resting)
to the gate; 'no exit' there = it shut: back round the levers (RUSH_TRIES more tries)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route, STEPF
st = config.Settings(); st.save = lambda: None; st.my_name = "Kang"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b, g = s.world, s.bot, s.state
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


gate = w.room((1, 1056)).exits["N"]
mp = path_from_route(w, (1, 1056), [gate], name="mummy")
pulls = [(x.room, x.pre) for x in mp.steps if x.pre]
check(f"a lever pulled in each room ({pulls})", pulls == [((1, 1038), ["pull lever"]), ((1, 1044), ["pull lever"])])
check("back to the gate and through", mp.steps[-1].room == (1, 1056) and mp.steps[-1].move == "N")
r = mp.rush[0]
check("no fighting from the first lever on", all(x.flags & STEPF["NOATTACK"] for x in mp.steps[r["first"]:]))
check("…but fights on the way to the first lever", not mp.steps[0].flags & STEPF["NOATTACK"])
b.path, b.walking, b.idx = mp, True, r["first"] + 3
check("rushing between the levers and the gate", b._rushing())
check("no resting while rushing", not b.should_rest([], True))
b.idx = r["gate"]
g.candidates = [(1, 1056)]
b.note_line("There is no exit in that direction!") if hasattr(b, "note_line") else None
check(f"gate shut → back round the levers (idx {b.idx})", b.idx == r["begin"] and r.get("tries") == 1)
for _ in range(b.RUSH_TRIES - 1):
    b.idx = r["gate"]
    b._rush_retry()
check(f"keeps going back round the levers ({b.RUSH_TRIES} tries)", b.walking)
b.idx = r["gate"]
b._rush_retry()
check(f"…and only stops after {b.RUSH_TRIES} more", not b.walking)
w2 = path_from_route(w, (1, 1055), [w.room((1, 1055)).exits["N"]] if "N" in w.room((1, 1055)).exits else [])
check("an ordinary path has no lever gates", not getattr(w2, "rush", None))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
