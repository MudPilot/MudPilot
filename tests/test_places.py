"""0.8.60: Goto list = Rooms.md, one entry per room number (the number in a name wins over a look-alike hash);
your own adds / renames / removals on top."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot import megamud_files as mf
import mudpilot.session as sess
from mudpilot.megamud_files import MPath, Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = tempfile.mkdtemp()
class S(sess.Session):
    rooms_md_path = os.path.join(d, "Rooms.md")
    places_file = os.path.join(d, "goto_places.json")
open(S.rooms_md_path, "w").write("x")
st = config.Settings(); st.save = lambda: None
s = S(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w = s.world
h = lambda k: w.rooms[k].mega_hash
rows = [("Wastelands Vortex (Mossy Tunnels)+3 681", (3, 681)), ("Negative Power Plane Vortex", (8, 978)),
        ("Negative Power Plane Vortex-8 978", (8, 958)), ("Great Pyramid (Below Pharoah)-12 2085", (12, 1808)),
        ("Darkwood Forest Vortex", (3, 784))]
sess.read_rooms_md = None
mf.read_rooms_md = lambda p: [{"hash": h(k), "name": n, "group": "G"} for n, k in rows]
s.paths = [MPath("p", "", "a", "b", end_label="Some path end", end_group="X", steps=[Step("", 0, "N", [], (1, 1), (1, 2))])]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
kr = s.known_rooms()
keys = [k for _g, _n, k in kr]
check(f"one entry per room ({kr})", len(keys) == len(set(keys)) == 4)
check("the numbered name wins: NPP vortex at 8/978, Pharoah at 12/2085", (8, 978) in keys and (12, 2085) in keys and (12, 1808) not in keys)
check("path start/end labels aren't mixed in any more", not any(n == "Some path end" for _g, n, _k in kr))
s.place_rename((8, 978), "NPP vortex")
s.place_remove((3, 784))
s.place_add((12, 1239), "Firepit under pyramid", "Scorching Desert")
kr = s.known_rooms()
check("renamed", ("G", "NPP vortex", (8, 978)) in kr)
check("removed", not any(k == (3, 784) for _g, _n, k in kr))
check("added", ("Scorching Desert", "Firepit under pyramid", (12, 1239)) in kr)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
