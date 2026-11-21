"""Don't-rest rooms rest as long as the room's refill allows (Dan, 2026-11-20: "sometimes they need to leave
immediately, sometimes it's a 90 second regen and he can safely rest for 80 seconds before moving 1 room")."""
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
st.rest_below_hp, st.rest_until_hp = 60, 90
s = Session(st)
b = s.bot
SLOW, FAST, NEW = (17, 2593), (17, 2594), (17, 9999)
lc = s.lairclock
lc._load = lambda: None
lc.data = {"17/2593": {"empty": 0, "s": [[84 + i, 1, 0] for i in range(6)] + [[4, 0, 0]]},
           "17/2594": {"empty": 0, "s": [[8 + i, 1, 0] for i in range(6)]}}
def at(room):
    stp = Step("0", 0, "SW", room=room, dest=(17, 1))
    stp.flags |= STEPF["DONTREST"]
    b.path, b.walking, b.idx = SimpleNamespace(title="Zombie pen", filename=r"C:\x\zp.mp", steps=[stp]), True, 0
    s.state.candidates = [room]
    b._dr_clear = None
s.state.max_hp, s.state.hp = 1000, 100
at(SLOW)
check("slow room (84 s refill), 10% HP, cleared: rests", b._dontrest_window([]) is True)
b._dr_clear = (SLOW, time.time() - 65)
check("…still fine 65 s in (84 - 12 margin = 72)", b._dontrest_window([]) is True)
b._dr_clear = (SLOW, time.time() - 73)
check("…up and gone at 73 s", b._dontrest_window([]) is False)
at(FAST)
check("fast room (8 s refill): no resting", b._dontrest_window([]) is False)
at(NEW)
check("refill not learned yet: no resting, as before", b._dontrest_window([]) is False)
at(SLOW)
check("monsters in the room: no", b._dontrest_window([("x", {})]) is False)
check("should_rest lets the slow room rest at 10% HP", b.should_rest([], False) is True)
at(FAST)
check("…and keeps the fast room moving", b.should_rest([], False) is False)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
