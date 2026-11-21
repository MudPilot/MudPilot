"""0.8.182 (Dan, 2026-11-12): "everybody in the party should at least be able to request @health… Just @health though."
A party member with no @ permissions gets @health answered; nothing else opens up, and strangers still get nothing."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.remote_enabled = True
st.remote_channels = {k: True for k in ("telepath", "say", "gangpath", "broadcast")}
st.remote_players = {"Revolution": ["query"]}
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, **k: sent.append(c)
s.log = lambda m, *a, **k: None
s.state.party = {"Miserable": {}, "Elbar": {}}
r = s.remote
r.handle("telepath", "Elbar", "@health")
check(f"party member, no permissions: @health answered ({sent})", any(c.startswith("/Elbar ") for c in sent))
sent.clear()
for cmd in ("@exp", "@inventory", "@do look", "@stop"):
    r.handle("telepath", "Elbar", cmd)
check(f"…nothing else opens up ({sent})", all("not allowed" in c for c in sent))
sent.clear()
r.handle("telepath", "Stranger", "@health")
check(f"not in the party: refused ({sent})", all("not allowed" in c for c in sent))
sent.clear()
r.handle("telepath", "Revolution", "@health")
check(f"a query permission still works outside the party ({sent})", any(c.startswith("/Revolution ") for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
