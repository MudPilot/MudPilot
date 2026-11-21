"""Miserable PVE, 2026-11-06: parted ways with Skittles on purpose; Skittles relogged and MudPilot kept trying to
rejoin them — '@where Skittles' for 10 minutes, then a walk off to 17/1773 right after a Go to Chancellor Annora.
Your own Go to, or leading your own party without them, means you've gone your own way: stop."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def make():
    st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    sent = []
    s.send = lambda c, from_bot=False: sent.append(c)
    s.bot.send = lambda c, **k: sent.append(c)
    s.state.candidates = [(1, 1333)]
    return s, sent
# leading your own party (you and Revolution), a minute after Skittles came back
s, sent = make()
s.state.party = {"Miserable": {}, "Revolution": {}}
s.bot.x.leading = lambda: True
s._rejoin = {"leader": "Skittles", "t": time.time() - 70, "asked": time.time() - 70, "tries": 1, "joined": False}
s.comeback.missing["Skittles"] = {"t": time.time(), "why": "left behind"}
s._rejoin_tick()
check("own party without Skittles: stops trying to rejoin them", s._rejoin is None and "Skittles" not in s.comeback.missing)
check(f"…and no @where sent ({sent})", not any("@where" in c for c in sent))
# your own Go to after they came back
s, sent = make()
s.state.party = {}
s._rejoin = {"leader": "Skittles", "t": time.time() - 5, "asked": time.time() - 5, "tries": 1, "joined": False}
s.bot._user_goto_at = time.time()
s._rejoin_tick()
check("your own Go to: stops trying to rejoin them", s._rejoin is None)
# just back in, alone, leader not here yet: still rejoins (the restart case)
s, sent = make()
s.state.party = {}
s._rejoin = {"leader": "Revolution", "t": time.time() - 5, "asked": time.time() - 30, "tries": 0, "joined": False}
s._rejoin_tick()
check("a follower just back from a restart still rejoins its leader", s._rejoin is not None)
sys.exit(0 if ok else 1)
