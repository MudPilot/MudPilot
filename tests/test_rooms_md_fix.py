"""Rooms.md entries whose number is wrong, glued or missing (Revolution, 2026-11-20): Goto took Evolution to the
Crimson Fortress for 'Choira Pyromancer-15 1168' and to 2/10 Top of Mountain Stair for 'Stone Giant Chieftain-1601095'.
The audit of the shared Rooms.md that followed (Dan, 2026-11-21) adds the rest."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mudpilot.worlddb import WorldDB
from mudpilot.session import Session

w = WorldDB(os.path.join(os.path.dirname(__file__), "..", "data", "boards", "Paradigm", "world.db"))
MD = """\
CA701555:00000000:0:0:0:CLSD:Arlysia:Crystal Lake, Southern Dock-17 569
70500004:00000010:0:0:0:BHGC:Barren Hills:Stone Giant Chieftain-1601095
A4F00056:00004040:0:0:0:FRT3:Black Fort:Outside Master Assassin-8 1262
C7300005:00000010:0:0:0:BFDL:Blackwood Forest:Darken Beast Lord-17 831
57205004:00000000:0:0:0:DLPR:Blackwood Forest:Outside Darken Beast Lord-17 2812
36F01000:00000002:0:0:0:BT3N:Darkwood Forest:Blue Tower, Weapons (sharp)
B8100041:00000000:0:0:0:ECOK:Jungle:Earthen Catacombs, Outside Kuel-16  2268
0C100004:00000010:0:0:13:LFCP:Lava Fields:Choira Pyromancer-15 1168
E5300051:00004040:0:0:0:TTFK:Shad-Thieves Town:Thieves Town-5 382
91800501:00000000:0:0:0:IMP1:Terra Ista:Icy Mountain Path Level 1-13 1171
6ED00040:00000018:0:0:0:KPTH:Trainers:Kingsport Training Hall (50-75)-14 1792
17C00040:00000008:0:29:0:RTRA:Trainers:Rhudaur Grizzled Trainer (12-30)
"""
tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
tmp.write(MD); tmp.close()
s = Session.__new__(Session)
s.world, s.paths = w, []
type(s).rooms_md_path = property(lambda self: tmp.name)
s.places = lambda: []
s._apply_places = lambda out, pl: out
got = {n: k for _g, n, k in s.known_rooms()}
os.unlink(tmp.name)
ok = True
def check(name, want, why):
    global ok
    k = got.get(name)
    print(("PASS " if k == want else "FAIL ") + f"{name} → {k} ({why})")
    ok &= k == want

check("Choira Pyromancer", (15, 1165), "the Lava Pool she stands in, not the Temple of Fire behind a key")
check("Stone Giant Chieftain", (16, 1095), "glued number; not 2/10 near Annora")
check("Outside Master Assassin", (7, 1262), "map typo")
check("Crystal Lake, Southern Dock", (17, 1569), "a digit dropped")
check("Blue Tower, Weapons (sharp)", (1, 3304), "no number: the hash room in the Blue Tower")
check("Earthen Catacombs, Outside Kuel", (16, 2268), "two spaces in the number")
check("Thieves Town", (5, 341), "six look-alikes: the one nearest the number")
check("Rhudaur Grizzled Trainer (12-30)", (2, 2570), "not the Kingsport hall another entry names")
check("Icy Mountain Path Level 1", (13, 1171), "number backed by the room's name: kept")
check("Darken Beast Lord", (17, 831), "swapped hashes: neither entry hides the other")
check("Outside Darken Beast Lord", (17, 2812), "swapped hashes: neither entry hides the other")
check("Kingsport Training Hall (50-75)", (14, 1792), "a plain good entry")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
