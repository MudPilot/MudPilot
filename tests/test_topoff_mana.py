"""Top-off waits for the tick of the stat that's short (0.8.227, Dan: Miserable PVE sat at 100% HP / 86% mana —
meditating, HP ticks every ~5 s but mana only every ~15 s, so it waited 7 s on the HP clock and got nothing)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.regenclock import RegenClock
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def clock(hp_every, ma_every):
    """A 120 s sitting: HP rises every hp_every s, mana every ma_every s; the last tick is now."""
    rc = RegenClock()
    t0 = time.time() - 120
    hp, ma = 500, 100
    rc.feed(True, hp, 1000, ma, 1000, now=t0)
    ev = sorted([(t0 + i * hp_every, "hp") for i in range(1, int(120 / hp_every) + 1)] +
                [(t0 + i * ma_every, "ma") for i in range(1, int(120 / ma_every) + 1)])
    for t, k in ev:
        if k == "hp":
            hp += 2
        else:
            ma += 5
        rc.feed(True, hp, 1000, ma, 1000, now=t)
    rc.last_tick = time.time()
    return rc

rc = clock(5, 15)
check(f"HP ticks every ~5 s, mana every ~15 s (hp {rc.stat_period('hp')}, ma {rc.stat_period('ma')}, "
      f"shared {rc.period})", abs(rc.stat_period("ma") - 15) < 1 and rc.period < 8)

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.rest_smart_full = True
s = Session(st); s._no_log_file = True
b, gs = s.bot, s.state
gs.max_hp, gs.max_ma, gs.hp, gs.ma = 1000, 1000, 1000, 860
gs.party = {}
b.regen = rc
rc.ma_gain = [40.0] * 5
rc.hp_gain = [2.0] * 5
check("100% HP / 86% mana, mana tick 15 s away: no top-off, up and walking", not b._topoff_one_more())

rc2 = clock(5, 6)
rc2.ma_gain = [40.0] * 5; rc2.hp_gain = [2.0] * 5
b.regen = rc2; b._topoff = None; b._topoff_used = False
check("mana tick due in ~6 s: still tops off", b._topoff_one_more())
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
