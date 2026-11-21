"""Round clock: learns the beat, carries its phase across a quiet walk, re-syncs when a round lands off the beat,
and keeps it across a restart."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.combatclock import CombatClock
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
path = os.path.join(tempfile.mkdtemp(), "round_clock.json")
c = CombatClock(path)
t0 = 1_000_000.0
for i in range(20):                                    # a fight: a round every 5.05 s
    c.feed("The geist claws you for 5 damage!", t0 + i * 5.05)
check(f"learns the round length ({c.period:.3f})", abs(c.period - 5.05) < 0.02)
later = t0 + 19 * 5.05 + 300.0                         # five minutes of walking, no fights
rem, _ = c.left(later)
expect = 5.05 - (300.0 % 5.05)
check(f"phase carried across 5 quiet minutes ({rem:.2f} s left, expected {expect:.2f})", abs(rem - expect) < 0.3)
c.feed("The crab misses you!", later + 2.0)            # the server shifted: a round off the beat
rem2, _ = c.left(later + 3.0)
check(f"re-syncs on a round off the beat ({rem2:.2f} s left)", abs(rem2 - (c.period - 1.0)) < 0.05)
c._saved_at = 0
c.save(time.time())
c2 = CombatClock(path)
check("a restart keeps the beat", c2.learned and abs(c2.period - c.period) < 1e-6 and c2.anchor == c.anchor)
check("…and knows the round timing before the first fight", c2.left() is not None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
