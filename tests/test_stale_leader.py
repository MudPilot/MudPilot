"""Evolution, 2026-11-21 (Revolution: "mudpilot doesn't like to sit still"): camping outside Lallim, not in anyone's
party for 3.5 hours, Miserable — followed earlier that evening — restarted for an update. 'Miserable just
disconnected' / 'just entered the Realm' made Evolution treat him as its leader again: @where, then a 481-step Go to
through 10 dangerous lairs to the zombie pen. A leader only counts while we follow them, or followed them in the last
half hour (Session.LEADER_MEMORY) — a real leader's restart still brings the follower back."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.leader_watch = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
s.bot.log = lambda m, *a, **k: None
s.notify.send = lambda *a, **k: None
s.on_alert = lambda *a, **k: None
x = s.bot.x

def run(followed_ago, following=None):
    s._rejoin = None
    x._following = following
    x._followed = "Miserable"
    x._followed_t = time.time() - followed_ago
    x._leader_gone_since = 0
    now = time.time()
    x._leader_lines("Miserable just disconnected!!!", now)
    gone = bool(x._leader_gone_since)
    x._leader_lines("Miserable just entered the Realm.", now + 30)
    return gone, getattr(s, "_rejoin", None)

gone, rj = run(3.5 * 3600)
check(f"followed 3.5 h ago: their restart is nothing to us (gone={gone}, rejoin={rj})", not gone and not rj)
gone, rj = run(60)
check(f"followed a minute ago (the party broke as they restarted): wait, then rejoin them ({rj and rj.get('leader')})",
      gone and rj and rj.get("leader") == "Miserable")
gone, rj = run(3.5 * 3600, following="Miserable")
check(f"following them right now: rejoin them ({rj and rj.get('leader')})", gone and rj and rj.get("leader") == "Miserable")
print("ALL PASS" if ok else "SOME FAILED")
