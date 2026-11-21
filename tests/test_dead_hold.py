"""Dan, 2026-10-30: after a death MudPilot must never try to recover by itself (back to its gear, naked and solo, it
dies again) — no rejoin, comeback, errand, Rego or resume walking. A friend's @goto, or you, still can."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
s.send = lambda c, from_bot=False: None
b = s.bot
b.held_items = lambda: set()
s.state.candidates = [(1, 2189)]; s.state.level = 55
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


b._last_room = (17, 183)
b.on_death()
check("died: held", b.dead_hold)
# MudPilot's own walks: comeback answering, the restart rejoin, an errand
s.comeback.fetch = {"name": "Miserable", "phase": "asked", "room": None, "back": None, "t": time.time()}
s.comeback.answer("Miserable", "{Rotting Glade, Trail - map 17 room 1637; exits: south}")
check(f"comeback doesn't walk back ({b.walking}, {b.status})", not b.walking and b.dead_hold)
from mudpilot.megamud_files import MPath
b.resume = {"path": None, "loop": False, "after": None, "target": (17, 1637)}
s._drop_resume, s._resume_at = {"path": MPath("Full Glades", "t", "A", "A"), "loop": True, "after": None,
                                "target": None}, time.time() - 1
s._resume_tick()
check(f"no resuming the loop by itself ({b.walking})", not b.walking and b.dead_hold)
# a friend's @goto
s.remote._channel = "telepath"
out = s.remote.c_goto("Miserable", "bank of godfrey")
check(f"a friend's @goto still works ({out}, hold now {b.dead_hold})", b.walking and not b.dead_hold)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
