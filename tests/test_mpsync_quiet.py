"""Dan, 2026-11-04: "whats this mpsync telepath all about i get them alot and i dont think they're necessary" —
'Revolution telepaths: @mpsync sk 3|90|2|0|jackal-headed warrior' on the game screen. They're MudPilots syncing (rests,
levels, spell tuning): still read, kept in Conversations, but not on the game screen. (Every 6 kills instead of
3 broke tuning together.) And in the timed pyramid followers keep blessing (only the leader skips it)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config, spelltune
from mudpilot.session import Session, MPSYNC_SCREEN_RE
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
check("an incoming @mpsync is kept off the screen",
      MPSYNC_SCREEN_RE.match("Revolution telepaths: @mpsync sk 3|90|2|0|jackal-headed warrior"))
check("…and ours going out", MPSYNC_SCREEN_RE.match("/Revolution @mpsync hi tune"))
check("a real telepath isn't", not MPSYNC_SCREEN_RE.match("Revolution telepaths: hey, wait up"))
check("…nor an @command", not MPSYNC_SCREEN_RE.match("Revolution telepaths: @rego"))
check("spell tuning still reports every 3 kills (the coordinator needs them)", spelltune.REPORT_EVERY == 3)
# through the session: read (remote sees it), not shown
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
shown, seen = [], []
s.on_line = lambda segs: shown.append(segs)
real = s.remote.feed_line
s.remote.feed_line = lambda t: seen.append(t) or real(t)
class T:
    connected = True
    def send_line(self, x): pass
s.telnet = T()
try:
    s._line([("Revolution telepaths: @mpsync sk 3|90|2|0|jackal-headed warrior", {})])
    s._line([("Revolution telepaths: hey", {})])
    check(f"through the session: the @mpsync line is read but not shown ({len(seen)} read, {len(shown)} shown)",
          len(seen) == 2 and len(shown) == 1)
except Exception as ex:
    print("  (session line format:", repr(ex)[:100], ")")
# timed pyramid: followers bless, the leader doesn't
b = s.bot
b._hurry = {"until": time.time() + 600, "area": "great pyramid", "up_from": None, "ups": 0, "seen": False}
calls = []
class Watched(list):
    def __iter__(self):
        calls.append("looked")                       # buffs_tick got as far as the bless list
        return super().__iter__()
st.buffs = Watched([{"name": "bless", "cast": "bles", "every": 0, "enabled": True}])
b._prelude_at = 0
b.x._following = None
b.buffs_tick([], False)
check("leading in the timed pyramid: no bless upkeep", not calls)
b.x._following = "Buddy"
b.buffs_tick([], False)
check("following: bless upkeep runs as usual", calls)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
