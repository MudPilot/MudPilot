"""Best spots / loop builder exp: a realm-unique monster (GameLimit 1, the Scarecrow) counts once a lap,
a boss on a regen timer (massive fanged spider, 3 h) counts by the hour, not every lap."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, lb = s.world, s.loopbuilder
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
sc = w.monster_names["scarecrow"]
check("GameLimit imported (Scarecrow: 1 in the realm)", sc.get("limit") == 1)
lairs = [k for k, r in w.rooms.items() if r.lair and f"{sc['num']}" in r.lair.split(":")[-1]][:6]
one = lb.lap_exp(lairs[:1]); six = lb.lap_exp(lairs)
check("six Scarecrow lairs aren't worth six Scarecrows a lap", six <= sc["exp"] * 1.01 and six < one * 3)
sp = w.monster_names["massive fanged spider"]
check("the 3-hour spider is a timed boss", lb.timed(sp))
sl = [k for k, r in w.rooms.items() if r.lair and str(sp["num"]) in r.lair.split(":")[-1].split(",")][:3]
v, _m = lb.lair_value(sl[0])
check("…left out of the lap value", v < sp["exp"])
bh, who = lb.boss_hr(sl)
check("…and counted per hour instead (350k / 3 h)", abs(bh - sp["exp"] / 3) < 1 and who)
k = w.by_name["rotting glade, trail"][0]
s.state.candidates = [k]; s.state.level = 47; s.state.max_hp = 684; s.state.hp = 684
t = time.time(); r = s.spots.find(); dt = time.time() - t
check(f"Best spots finishes quickly ({dt:.1f} s)", dt < 60 and r.get("spots"))
check("no spot claims 20M+/hr", all(o["est_hr"] < 20e6 for o in r["spots"]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
