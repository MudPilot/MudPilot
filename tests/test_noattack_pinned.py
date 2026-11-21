"""No-attack rooms are for running through, not for being pinned (Dan, 2026-11-20: Miserable PVE knocked down in the
zombie pen's no-attack room took 920 -> 88 HP in 33 s without a swing or a spell)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from types import SimpleNamespace
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step, STEPF
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st)
b = s.bot
A, B = (17, 2594), (17, 2593)
steps = [Step("0", 0, "SW", room=A, dest=B)]
steps[0].flags |= STEPF["NOATTACK"]
b.path, b.walking, b.idx = SimpleNamespace(title="Zombie pen", filename=r"C:\x\zp.mp", steps=steps), True, 0
s.state.candidates = [A]
b._room_at = (A, time.time())
b._being_hit = False
check("running through, not hit: no attack", b._step_flag("NOATTACK"))
b._being_hit = True
check("just walked in and hit once: still running through", b._step_flag("NOATTACK"))
b.x.ailments["knocked"] = time.time()
check("knocked down while being hit: fight back at once", not b._step_flag("NOATTACK"))
b._being_hit = False
check("knocked down before any hit lands: fight back at once", not b._step_flag("NOATTACK"))
b.x.ailments["knocked"] = 0
b.x.ailments["held"] = time.time()
check("held: fight back at once", not b._step_flag("NOATTACK"))
b.x.ailments["held"] = 0
b._being_hit = True
b._room_at = (A, time.time() - 3)
b._step_sent_at = time.time() - 2.5
check("being hit, the move sent 2.5 s ago didn't take: fight back", not b._step_flag("NOATTACK"))
b._step_sent_at = time.time() - 0.5
check("…but a move just sent gets its moment", b._step_flag("NOATTACK"))
b._room_at = (A, time.time() - 5)
check("hit 5 s in the same room, whatever the reason: fight back", not b._step_flag("NOATTACK"))
b._being_hit = False
check("…but not when nothing's hitting us", b._step_flag("NOATTACK"))
b._being_hit = True
check("don't-rest is untouched", not b._step_flag("DONTREST"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
