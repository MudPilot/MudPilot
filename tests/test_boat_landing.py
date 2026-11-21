"""0.8.189 (realm walk sweep): aboard a boat the walk waits until it lands ('At sea — about N s to go'). The Kingsport
boat lands on 14/702 Kingsport Harbor, Wharf — one of 45 rooms of that name, so the room tracker can't say which
and the walk sat on the wharf until its estimate plus 90 s ran out. The landing room among the look-alikes is
landing."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_boat"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, g, w = s.bot, s.state, s.world
twins = [k for k in w.rooms if w.room(k).name == "Kingsport Harbor, Wharf"]
check(f"the wharf has look-alikes ({len(twins)})", len(twins) > 10 and (14, 702) in twins)
now = time.time()
b._boat = {"land": (14, 702), "until": now + 590, "secs": 500}
g.candidates = [(14, 721)]                      # aboard the Swiftwind
check("aboard: still at sea", b._at_sea(now) and b._boat)
g.candidates = list(twins)                       # ashore on 'a' Kingsport Harbor, Wharf
check(f"ashore on a wharf look-alike: landed ({b.status})", not b._at_sea(now + 30) and not b._boat)
check(f"…placed on the landing room ({g.room})", g.room == (14, 702) and "Landed" in logs)
b._boat = {"land": (14, 702), "until": now + 590, "secs": 500}
g.candidates = [(14, 759)]                       # still at the far dock (boarding): not landed
check("somewhere else: still at sea", b._at_sea(now) and b._boat)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
