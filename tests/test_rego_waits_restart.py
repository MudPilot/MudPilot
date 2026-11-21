"""Dan, 2026-11-04: "buddy just ran off without evolution". Revolution and Evolution both @stop'd Buddy for a restart;
Revolution came back first and sent @rego, and Buddy set off while Evolution was still logging in. Now an @rego waits
for everyone who stopped us for a restart, and the walk carries on once they're following again."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.party_comeback = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, r, cb = s.bot, s.remote, s.comeback
s.log = lambda m, *a, **k: None
s.state.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
b.walking = True
b.stop = lambda why="", **k: setattr(b, "walking", False)
regos = []
b.rego = lambda *a, **k: regos.append(time.time()) or True
r.c_stop("Revolution", "")
r.c_stop("Evolution", "")
del s.state.party["Evolution"]                      # (logged off: off the party list while he's away)
out = r.c_rego("Revolution", "")
check(f"Revolution's @rego with Evolution still restarting: waits ({out})", "Evolution" in str(out) and not regos)
cb.feed_line("Revolution started to follow you.")
check("Revolution following again: still waiting for Evolution", not regos)
cb.feed_line("Evolution started to follow you.")
check("Evolution following again: off it goes", len(regos) == 1)
# nobody else away: @rego goes straight away, as before
regos.clear()
cb.away = {}
b.resume = {"target": (12, 1805)}
out = r.c_rego("Revolution", "")
check(f"nobody else away: carries on at once ({out})", regos and "carrying on" in str(out))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
