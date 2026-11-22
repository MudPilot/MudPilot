"""Dan, 2026-11-21: "it should use the entire text of the item … smash large stitched zombie instead of smash stitched
zombie, use large iron key instead of use iron key". Attacks name the monster exactly as the room shows it, and a door
key always goes by its whole name (Revolution's 'use iron key e' at Thrag's door clashed with his iron keyring)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot.automation import Automation as A
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
z = {"name": "stitched zombie"}
for shown, rec, want in [("large stitched zombie", z, "large stitched zombie"),
                         ("stitched zombie", z, "stitched zombie"),
                         ("a large stitched zombie", z, "large stitched zombie"),
                         ("2 stitched zombies", z, "stitched zombie"),
                         ("angry stonecap", {"name": "stonecap"}, "angry stonecap"),
                         ("glowing wisp", None, "glowing wisp"),
                         ("", {"name": "Lallim Whitemane"}, "Lallim Whitemane")]:
    got = A.target_word((shown, rec))
    check(f"{shown!r} -> {got!r}", got == want)

import types
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b = s.bot; w = s.world
# a door that needs a multi-word key
found = None
for key, r in list(w.rooms.items())[:200000]:
    for d, ex in r.exits.items():
        need = w.exit_need(ex)
        if need and len((w.item_name(need[0]) or "").split()) >= 3:
            found = (key, d, need[0], w.item_name(need[0])); break
    if found: break
check(f"found a door that takes a 3-word key ({found and found[3]})", found)
if found:
    key, d, num, name = found
    b.held_items = lambda: {num}
    check(f"the door key goes by its whole name ({b._door_key(key, d)!r})", b._door_key(key, d) == name)
print("ALL PASS" if ok else "SOME FAILED")
