"""Dan, 2026-11-04: 'when i give someone an @status i'd like it to tell me what its doing, like not just walking to
rotting glade rm#, but what its waiting on, disease, buddy, etc'."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.send = lambda c, from_bot=False: None
r, b, gs = s.remote, s.bot, s.state
gs.resting, gs.meditating = True, True
b._rest_reason = "mana below 60% (20%)"
a = r._activity()
check(f"why it's resting ({a})", "meditating (mana below 60% (20%))" in a)
s.msgrules.conditions["losing_hp"] = {"rule": "disease"}
a = r._activity()
check(f"what it has ({a})", "has losing hp" in a)
s.msgrules.conditions.clear()
s.msgrules._waiting = "blindness"
check(f"a message wait ({r._activity()})", "waiting for blindness to wear off" in r._activity())
s.msgrules._waiting = None
# waiting on a member: who and how far along, not a second 'waiting on the party'
b._rest_reason = "waiting on the party"
b.walking = True
b.x.waiting_on = ["Buddy"]
gs.party = {"Buddy": {"hp": 92, "ma": 15}}
a = r._activity()
check(f"waiting on Buddy, said once ({a})", "waiting for Buddy to rest up (HP 92%, MA 15%)" in a
      and "waiting on the party" not in a)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
