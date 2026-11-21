"""Run-through rooms (0.8.211, Dan): hold before stepping in until a combat round has just gone off; in the room,
no fighting and no resting."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from types import SimpleNamespace
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st)
b = s.bot
A, B, C, D = (1, 10), (1, 11), (1, 12), (1, 13)
steps = [Step("0", 0, "N", room=A, dest=B), Step("0", 0, "N", room=B, dest=C), Step("0", 0, "N", room=C, dest=D)]
mp = SimpleNamespace(title="Test loop", filename=r"C:\x\Test.mp", steps=steps)
b.path, b.walking, b.idx = mp, True, 0
st.loop_runthru = {"test.mp": ["1/11", "1/12"]}
check("run-through rooms read from the settings", b._runthru_rooms() == {B, C})
class Clock:
    period = 5.0
    rem = 1.0
    def left(self, now=None): return (self.rem, self.rem / self.period)
s.clock = Clock()
rt = b._runthru_rooms()
check("late in the round: hold (two rooms to cross need 2.8 s)", b._round_wait(steps[0], rt) is True
      and "Timing the round" in b.status)
s.clock.rem = 4.6
check("a round just went off: go", b._round_wait(steps[0], rt) is False)
s.clock.rem = 1.0
b._rt_hold = (((B), 0), time.time() - 20)
check("never held more than 3 rounds (clock off)", b._round_wait(steps[0], rt) is False)
s.clock.left = lambda now=None: None
check("no round timing known: go straight through", b._round_wait(steps[0], rt) is False)
b.idx = 1
check("in a run-through room: no attack / don't rest", b._step_flag("NOATTACK") and b._step_flag("DONTREST"))
b.idx = 2
check("…the next one too", b._step_flag("NOATTACK"))
st.loop_runthru = {}
check("…and not when unmarked", not b._step_flag("NOATTACK"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
