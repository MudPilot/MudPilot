"""HUNT_1123 #4: Evolution (wearing a phoenix feather) led Revolution (carrying one) through 51 rooms of 'magma heat'
(spell 526; MME NegateSpell: magma amulet 487, phoenix feather 1000) and took nothing, but the rooms-that-hurt count
said up to 3,060. Leading, only items every follower's 'kit=' lists count against room damage, and 'kit=' only had
the carry-for-everyone items (the idol). Now it lists room-spell counters too."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_party_negate_kit"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import Exit
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 41
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w, g = s.bot, s.world, s.state
FEATHER, AMULET, HEAT = 1000, 487, 526
check("MME: the phoenix feather and magma amulet negate magma heat", {FEATHER, AMULET} <= set(w.negates.get(HEAT, [])))
check("kit items: the counters are in, the idol still is", {FEATHER, AMULET, 1281} <= w.kit_item_set())
check("…carry_item_set (door / idol planning) is unchanged", FEATHER not in w.carry_item_set())
g.level, g.keys = 41, ""
g.carrying = "woven ivy crown (Head), phoenix feather (Neck), golden idol"
info = s.partysync.my_info()
check(f"our party sync says we carry the feather and the idol ({info})", "kit=" in info and
      {str(FEATHER), "1281"} <= set(info.split("kit=")[1].split()[0].split(".")))
tube = [(15, n) for n in range(1137, 1165)]
route = [Exit("E", tube[i + 1], "", True, False, "normal") for i in range(len(tube) - 1)]
def hurt():
    s.route_char()
    return sum(d for _r, d in w.hurt_stretches(route))
g.party = {"Tester": {}, "Revolution": {}}
s.partysync.members = lambda: ["Revolution"]
s.partysync.info = lambda: {"Revolution": {"kit": [1281]}}
d0 = hurt()
check(f"leading Revolution with no feather known: the Lava Tube still counts ({d0})", d0 == 60 * len(route))
s.partysync.info = lambda: {"Revolution": {"kit": [1281, FEATHER]}}
d1 = hurt()
check(f"his kit= lists the feather: the Lava Tube hurts nobody ({d1})", d1 == 0)
g.party = {}
d2 = hurt()
check(f"alone, wearing the feather: 0 ({d2})", d2 == 0)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
