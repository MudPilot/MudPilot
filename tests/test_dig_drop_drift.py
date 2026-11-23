"""0.8.225.1 (Dan: "why does PVE Miserable keep stopping his treasure digging loop?"): the loop is one step, 'dig
treasure' at Jungle Trail, Lagoon (13/211). A dig drops you into the Dark Pit (13/315-323) now and then; the walker
climbs back out and digs on. But every climb out counted as being knocked off the path — at 2-3 laps a minute that
was 7 in 5 min: 'Stopped: knocked off the path 7 times in 5 min again'. Off the path right after a dig isn't drift."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_dig_drop"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import read_mp, resolve_path
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 60
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs, sent = [], []
s.log = lambda m, *a, **k: logs.append(m)
s.send = lambda c, from_bot=False: sent.append(c)
s.on_alert = lambda m: None
b, g, w = s.bot, s.state, s.world
fn = os.path.join(tempfile.mkdtemp(), "treasure_digging.mp")
with open(fn, "w", encoding="latin-1") as f:
    f.write("[treasure digging][MudPilot]\n[FFFF:Terra Fuego:Jungle Trail, Lagoon]\n"
            "B6D00051:B6D00051:1:-1:0:::\nB6D00051:0000:[dig treasure]\n")
mp = read_mp(fn)
resolve_path(w, mp)
check(f"the loop is matched to the map ({mp.resolved}, {[x.room for x in mp.steps]})",
      mp.resolved and mp.steps[0].room == (13, 211))
# (only the off-path part of the walker counts here — nothing else may act on its own)
b._anchor = lambda: False


def climbs(dug_ago, n=8):
    """n laps, each ending in a Dark Pit room the dig dropped us in: how the walk stands after."""
    b.start_path(mp, loop=True, checked=True)
    b._drift, b._drift_warned, b._drift_soft_at = [], 0, 0
    logs.clear()
    for i in range(n):
        g.candidates = [(13, 316 + i % 7)]
        b._dig_at = time.time() - dug_ago
        b.detour, b._replan_at, b.idx, b._expect_seq, b._step_sent_at = None, 0, 0, None, 0
        b.hold_reasons = {} if hasattr(b, "hold_reasons") else None
        try:
            b.walk([], False)
        except TypeError:
            b.walk([], [])
        if hasattr(b, "_holds"):
            b._holds = {}
    return [l for l in logs if "drift" in l.lower() or "Stopped" in l], [l for l in logs if "Off path" in l]


bad, back = climbs(5)
check(f"8 dig drops in a row: walked back out each time ({len(back)})", len(back) >= 7)
check(f"…and not one counted as drift / stopped ({bad[:2]})", not bad and b.walking)
bad, back = climbs(10 * 60)
check(f"knocked off with no dig just before still counts ({bad[:1]})", bad)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
