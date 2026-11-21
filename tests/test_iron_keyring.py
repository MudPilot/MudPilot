"""0.8.220 (Revolution's report, 0.8.212): at Thrag's door (1/1794, east) with the large iron key AND the iron keyring on
you, 'use iron key east' got "Please be more specific. You could have meant any of these: iron keyring, large iron key".
When anything else you carry has the short name in it, the whole key name goes out."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_iron_keyring"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, g = s.bot, s.state
g.carrying = "platinum sceptre (Weapon Hand), iron keyring, rope and grapple"
g.keys = "golden idol, moldy key, large iron key, 2 iron house key"
k = b._door_key((1, 1794), "E")
check(f"Thrag's door with the iron keyring on you: the whole name ({k})", k == "large iron key")
g.carrying = "platinum sceptre (Weapon Hand), rope and grapple"
g.keys = "golden idol, large iron key"
k = b._door_key((1, 1794), "E")
check(f"no keyring: the short name as before ({k})", k == "iron key")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
