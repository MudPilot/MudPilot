"""Dan, 2026-11-10: pyramid level 2, timer running — bee poison at 65% HP (rest line 70%) and Miserable stood still
'Poisoned — waiting for it to wear off before resting'. No resting on the timed levels means no waiting for that
either: keep running. Outside the pyramid it still waits the poison out before resting."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.cure_poison_cmd = 70, 90, 0, ""
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
s.send = lambda c, **k: None
b.send = lambda c, **k: None
g.max_hp, g.hp, g.max_ma, g.ma = 713, 467, 491, 491
b.x.ailments["poison"] = time.time()
check("poisoned at 65%, no timer: waits it out (as before)", b.should_rest([], False)
      and "Poisoned" in str(b.status))
b._hurry = {"area": "great pyramid", "until": time.time() + 200, "seen": False}
b._no_rest_until = b._hurry["until"]
b.status = ""
check("…on the timed pyramid: doesn't stand there", not b.should_rest([], False) and "Poisoned" not in str(b.status))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
