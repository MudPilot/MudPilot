"""Dan, 2026-11-14: Miserable carries the golden idol, but the game lists it under "You have the following keys:
golden idol." — @have only looked at "You are carrying", answered Revolution "{no golden idol}", and Revolution
wouldn't route to the Stone Chief (the idol teleport needs every walker to have one)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.send = lambda c, from_bot=False: None
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


for line in ("You are carrying 12 runic coins, vortex staff (Weapon Hand), rope and grapple, white keyring",
             "You have the following keys: golden idol.",
             "Wealth: 12452600 copper farthings"):
    s.state.feed_line([(line, None)])
check(f"keys line read ({s.state.keys!r})", "golden idol" in (s.state.keys or ""))
r = s.remote
r._inv_dirty = False
out = r.c_have("Revolution", "golden idol")
check(f"@have golden idol → yes ({out})", out == "yes: golden idol")
check("carried items still found", r.c_have("Revolution", "rope") == "yes: rope and grapple")
check("missing item still no", r.c_have("Revolution", "log raft") == "no log raft")
s.state.keys = ""
check("no keys: still no", r.c_have("Revolution", "golden idol") == "no golden idol")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
