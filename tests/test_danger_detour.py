"""Buddy (Dan, 2026-11-03): a Go to from Eastern Road 17/181 to the Frozen Cavern 10/297 set off on 338 rooms — the
28-room way passes the skeletal acid beasts' lair on the Dirt Path (17/4, rated dangerous), and a dangerous lair was
kept out whenever any other way existed, however long. A short detour round one is still taken; a 10x one isn't."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w = s.world
a, b = (17, 181), (1, 1813)                   # Eastern Road → the Pier
base = w.route(a, b)
long_, short_ = None, None
for ex in base[:-1]:                          # lairs on the way: one with a long way round, one with a short one
    alt = w.route(a, b, avoid={ex.to})
    if alt and len(alt) > 2 * len(base) and not long_:
        long_ = (ex.to, len(alt))
    if alt and len(base) < len(alt) <= len(base) + 10 and not short_:
        short_ = (ex.to, len(alt))
check(f"found both kinds on the {len(base)}-room way (long {long_}, short {short_})", long_ and short_)
if long_ and short_:
    w.danger_fn = lambda k: k == long_[0]
    w._memo = {}
    r = w.route(a, b)
    check(f"way round {long_[1]} rooms: goes past the lair ({len(r)})", len(r) == len(base))
    w.danger_fn = lambda k: k == short_[0]
    w._memo = {}
    r = w.route(a, b)
    check(f"way round {short_[1]} rooms: walks round it ({len(r)})", short_[0] not in [e.to for e in r])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
