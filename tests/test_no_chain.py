"""Dan, 2026-10-30: daisy-chaining @commands is a security risk (MegaMUD doesn't allow it) — an enemy who shares a
trusted friend with you could '@do /Buddy @goto …' through that friend and steer everyone who trusts it. @do never
passes an @command on; ordinary @do still works."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
r = s.remote
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


for bad in ("/Buddy @goto 8 501", "/buddy @summon 1 297", "say @rego", ". @stop", "gos @do drop all",
            "br @invite", ".@goto 8 501", "/Buddy{@goto 1 297}", "bg @goto 1 297", "e^M/Evolution @do drop all"):
    sent.clear()
    out = r.c_do("Enemy", bad)
    check(f"refused: '{bad}' ({out}, sent {sent})", not sent and "can't" in out)
for good in ("go portal^Me", "eq longb", "use blaze", "tel Dan hello there", "get 20 gold"):
    sent.clear()
    r.c_do("Dan", good)
    check(f"still fine: '{good}' ({sent})", bool(sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
