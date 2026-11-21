"""Revolution, 2026-10-30: Go to the dark-elf prison (8/493 Dark Corridor) with Buddy (15) and Evolution (20):
'the only way is through the Negative Power Plane / Hazy Swamp — members aren't big enough'. Not true: there's a way
on their level through the Black Steel Gate (its key, or a bash). The 'too small' check came before the keyed route."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.level = 55
s.state.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
s.partysync.levels = lambda: {"Buddy": 15, "Evolution": 20}
b = s.bot
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


check("routes on the party's level (15)", b.route_level() == 15)
k = b.keyed_route((1, 297), (8, 493))
check(f"a way exists on their level, through the gate ({k and len(k)} rooms)", k is not None)
check(f"…so it isn't 'too small' ({b._too_small((1, 297), (8, 493))})", b._too_small((1, 297), (8, 493)) is None)
s.telnet.sock = object()
s.state.candidates = [(1, 297)]
s.send = lambda c, from_bot=False: None
b.held_items = lambda: set()
started = b.goto((8, 493))
check(f"Go to the prison sets off ({started}, {b.status}, {b.no_route_msg[:80]})", started and not b.no_route_msg)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
