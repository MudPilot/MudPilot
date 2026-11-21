"""Dan, 2026-11-04: "buddy thinks rounds are 8 seconds and revolution thinks they're 5. Revolution is much closer
to spot on" / "it should time rounds and determine that for itself". Buddy's saved round_clock.json said 8.25 s,
and replaying his trace (1,946 rounds, nearly all 5 s apart) through the old clock left it at 8.23 s: once
learned it only refined itself against its own guess. Now the length is always measured from the gaps."""
import json, os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot.combatclock import CombatClock
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
REAL = 5.05
def fight(c, t0, n, skip=()):
    """n rounds REAL s apart; rounds in `skip` have no lines (a double gap)."""
    t = t0
    for i in range(n):
        t += REAL
        if i in skip:
            continue
        c.feed("You slash at the thin bandit for 23 damage!", t)
        c.feed("The thin bandit swipes at you, but misses!", t + 0.3)
    return t
# Buddy's saved clock: 8.25 s
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "round_clock.json")
now = time.time()
json.dump({"period": 8.245, "anchor": now - 100, "t": now - 60}, open(path, "w"))
c = CombatClock(path)
check(f"(starts from the saved 8.25 s: {c.period:.2f})", abs(c.period - 8.245) < 0.01)
t = fight(c, now, 12, skip={3, 7, 8})
check(f"a dozen real rounds (three with nothing in them): back to {c.period:.2f} s", abs(c.period - REAL) < 0.05)
t = fight(c, t + 600, 40, skip=set(range(0, 40, 4)))
check(f"stays right over a long fight with skipped rounds ({c.period:.2f})", abs(c.period - REAL) < 0.03)
# fresh, and from too short a guess
c = CombatClock(None)
fight(c, now, 6)
check(f"fresh: learns it in a few rounds ({c.period:.2f})", c.learned and abs(c.period - REAL) < 0.05)
c = CombatClock(None)
c.period, c.learned = 3.0, True
fight(c, now, 10, skip={2, 5})
check(f"from 3 s too: corrects ({c.period:.2f})", abs(c.period - REAL) < 0.05)
# a few odd early lines don't make a round of their own
c = CombatClock(None)
t = fight(c, now, 8)
c.feed("You miss the thin bandit.", t + 3.9)                # a straggler line, not a round
t = fight(c, t + 3.9, 8)
check(f"a straggler doesn't drag it ({c.period:.2f})", abs(c.period - REAL) < 0.08)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
