"""0.8.185 (Dan, 2026-11-12): "i'd like it to wipe recent rego's with an extra @stop". PVEREV kept an old 'Rego carries
on to 13/825' through two restarts. A character that's already stopped clears what Rego would carry on with when it
gets another @stop; the first @stop still stops it and keeps Rego."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "PVEREV"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.send = lambda c, **k: None
s.log = lambda m, *a, **k: None
b, r = s.bot, s.remote
trip = MPath(name="Go to 13/825 Pirate Galleon", author="", start_hash="a", end_hash="b")
b.path, b.walking, b.loop = trip, True, False
b._goto_target = (13, 825)
out = r.c_stop("Evolution", "")
check(f"first @stop stops the walk ({out})", not b.walking and out.startswith("stopped"))
check(f"…and keeps Rego ({b.resume})", bool(b.resume))
out = r.c_stop("Evolution", "")
check(f"second @stop clears Rego ({out})", not b.resume and "Rego cleared" in out)
out = r.c_stop("Evolution", "")
check(f"a third has nothing to clear ({out})", out == "already @stopped")
check("Rego now does nothing", b.rego() is False and not b.walking)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
