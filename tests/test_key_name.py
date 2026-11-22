"""0.8.189 (realm walk sweep): a key door is unlocked with 'use <last two words of the key> <dir>' ('use lion key w').
Carrying the iron AND the copper house key, 'use house key s' at the iron house door (6/569) is the copper one as far
as the game can tell. When another key you carry ends the same way, the whole name goes out."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_key_name"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, g = s.bot, s.state
g.carrying, g.keys = "golden idol", "iron house key"
check(f"one house key: the whole name (Dan, 2026-11-21) ({b._door_key((6, 569), 'S')})", b._door_key((6, 569), "S") == "iron house key")
g.keys = "copper house key, iron house key"
check(f"the copper one too: the whole name ({b._door_key((6, 569), 'S')})", b._door_key((6, 569), "S") == "iron house key")
check(f"…and at the copper door its own ({b._door_key((6, 568), 'N')})", b._door_key((6, 568), "N") == "copper house key")
g.keys = "golden lion key, silver key"
check(f"nothing alike: the whole name ({b._door_key((12, 2034), 'W')})", b._door_key((12, 2034), "W") in ("golden lion key", None))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
