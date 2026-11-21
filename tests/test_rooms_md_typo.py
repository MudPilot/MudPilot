"""0.8.208 (Dan, 2026-11-19): MegaMUD's Rooms.md lists 'Ship Captains Quarters-16 1617', but its checksum (3D710000)
is 16/1517 — 16/1617 is in the Undermountain Caverns, behind a raft, rope and a golden idol each. A room number in
the name that doesn't fit the checksum, when the checksum fits a room of that exact name: the checksum wins.
The pyramid's twins (the number fits the checksum too) still go by the number."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
type(s).rooms_md_path = property(lambda self: os.path.join(here, "tests", "fixtures", "Paradigm_Rooms.md"))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
rows = s.known_rooms()
scq = [k for g, n, k in rows if n.lower().startswith("ship captains quarters")]
check(f"Ship Captains Quarters → 16/1517 ({scq})", scq and tuple(scq[0]) == (16, 1517))
pyr = [k for g, n, k in rows if n.startswith("Great Pyramid (Below Pharoah)")]
check(f"pyramid twin still by its number ({pyr})", not pyr or tuple(pyr[0]) == (12, 2085))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
