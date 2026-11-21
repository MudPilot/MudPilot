"""0.8.179 (Dan, 2026-11-12: "why is evo waiting on buddy, they're all grouped up 100% and ready to roll"): Evolution
noted Buddy 'dropped', Buddy came back 22 s later and they regrouped, but the note was never cleared. Once a dropped
member shows up in the party again (a 'par' since) or in the room, the wait ends."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.party_comeback = True
st.comeback_wait_mins = 5
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, cb = s.bot, s.state, s.comeback
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
s.log = lambda m, *a, **k: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
t0 = time.time()
g.party = {"Evolution": {"t": t0 - 30}, "Buddy": {"t": t0 - 30}, "Revolution": {"t": t0 - 30}}
cb.missing["Buddy"] = {"t": t0 - 5, "why": "dropped"}
cb.tick()
check(f"dropped and not seen since: still waits ({cb.holding()})", cb.holding() == "Buddy")
g.party["Buddy"] = {"t": time.time()}              # a 'par' lists him again
cb.tick()
check(f"back in the party: the wait ends ({cb.holding()})", cb.holding() is None and "Buddy" not in cb.missing)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
