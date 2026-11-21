"""Buddy, 2026-10-29: standing with the party, 'Resting to full' — Stop ×4 did nothing (nothing was walking) and it kept
resting. Stop with nothing walking = stop resting: no auto rest for 2 minutes."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.auto_rest = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
b.send = lambda c, *a, **k: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g.max_hp, g.hp = 225, 150
b.stop("Stopped by you")
check(f"says it ({b.status})", "not resting" in b.status)
check("won't rest", not b.should_rest([], True))
sent.clear()
b._cool = {}
b.idle_regen([])
check(f"…not even while waiting on the party ({sent})", not sent)
b._no_rest_until = time.time() - 1
b._cool = {}
b.idle_regen([])
check(f"rests again afterwards ({sent})", sent == [st.rest_cmd])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
