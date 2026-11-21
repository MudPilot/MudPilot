"""Dan, 2026-10-30, Stone Tunnel 2/1306: Revolution said '@party go hole' and went hole. Buddy and Evolution didn't
go (followers' @party only sent 'par'), the party broke, they sent '@comeback 2/1306', and Revolution walked back down.
Now: followers do the command, nobody @comebacks anybody while the party goes through, and they regroup."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name; st.party_comeback = True
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    s.telnet.sock = object(); s._connected_at = time.time() - 60
    sent = []
    s.telnet.send_line = lambda c: sent.append(c)
    return s, sent


# the follower
bud, bs = make("Buddy")
bud.bot.x._following = "Revolution"
bud.state.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
bud.state.candidates = [(2, 1306)]
bud.remote.feed_line('Revolution says "@party go hole"')
check(f"follower goes hole too ({bs})", "go hole" in bs)
bs.clear()
bud._line([("You are no longer following Revolution.", Style())])
bud._line([("Your party has been disbanded.", Style())])
check(f"…no @comeback for the party breaking ({bs})", not any("@comeback" in c for c in bs))
check("…and asks to be invited back on the other side", getattr(bud, "_rejoin", None) and bud._rejoin.get("no_rego"))
# the leader
rev, rs = make("Revolution")
rev.state.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
rev.state.candidates = [(2, 487)]
rev.send("@party go hole")
rs.clear()
called = []
rev.bot.goto = lambda *a, **k: called.append(a) or True
rev.remote.feed_line("Buddy telepaths: @comeback 2/1306")
check(f"leader ignores @comeback while the party goes through ({called})", not called)
rev.comeback._self_left = time.time() - 60          # later on, a real @comeback
rev.remote.feed_line("Buddy telepaths: @comeback 2/1306")
check(f"…a later @comeback still works ({called})", called)
# not from our party: ignored
stranger, ss = make("Evolution")
stranger.state.party = {}
stranger.remote.feed_line('Enemy says "@party go hole"')
check(f"@party from someone not in our party does nothing ({ss})", "go hole" not in ss)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
