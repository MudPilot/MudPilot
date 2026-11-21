"""Dan, 2026-11-10: Revolution, confused by a terror beast, told Miserable '@wait (confused)'. The fear split the
party; the confusion wore off while he was out of it, so no @ok — Miserable sat 2 min on the @wait. The @ok goes
to whoever was told to wait, the moment it clears, party or no party."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, x = s.bot, s.state, s.bot.x
sent = []
s.send = lambda c, **k: sent.append(c)
x.send = lambda c, **k: sent.append(c)
b.walking = False
g.party = {"Miserable": {}, "Revolution": {}}
g.max_hp, g.hp = 500, 500
x.ailments["confused"] = time.time()
x.full_tick()
check(f"confused in the party: @wait to the leader ({sent})", any(c.startswith("/Miserable @wait") for c in sent))
sent.clear()
g.party = {}                                    # the fear split the party
x.ailments.pop("confused", None)                # 'confused gone (wore off)'
x.full_tick()
check(f"wore off while the party's split: @ok to Miserable anyway ({sent})", "/Miserable @ok" in sent)
sent.clear(); x.full_tick()
check("…once", not any("@ok" in c for c in sent))
# still confused while the party's split: no @ok yet
g.party = {"Miserable": {}, "Revolution": {}}
x.ailments["confused"] = time.time(); x.full_tick(); sent.clear()
g.party = {}
x.full_tick()
check("still confused, party split: no @ok", not any("@ok" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
