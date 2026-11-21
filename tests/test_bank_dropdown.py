"""0.8.185 (Dan, 2026-11-12): "i would prefer a dropdown theres only 8 banks... just clicking which bank it is with a
friendly name". The bank room box is a dropdown of the realm's banks by name; it still saves the room ('17/2435')."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
banks = dict(s.trips.bank_choices())
for lbl in banks: print("   ", lbl, banks[lbl])
check("eight banks", len(banks) == 8)
check("Arlysia is 17/2435", banks.get("Bank of Arlysia") == (17, 2435))
check("Delanon says it's Shadowmere's", banks.get("Bank of Delanon (Shadowmere)") == (5, 245))
check("Blackwater branch listed", (14, 267) in banks.values())
check("the Lost City's plain 'Bank' gets a name", banks.get("Lost City Bank") == (16, 320))
check("no duplicate names", len(set(banks)) == len(s.trips.bank_choices()))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
