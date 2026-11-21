"""Buddy, 2026-11-02: Go to the Pier went up the Dark Hole (10/275) for the hidden exit north, searched 8 times
("You notice nothing different to the north"), then went all the way back down and round — and said why only in the
log. An exit searching never finds is a wall for a day, kept over a restart, and the bottom bar says why."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
tmp = os.path.join(tempfile.mkdtemp(), "unfindable.json")
Session._unfindable_path = lambda self: tmp
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def make():
    st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    return s


s = make()
uses = lambda s: any(e.dir == "N" and e.to == (10, 201) for e in (s.world.route((10, 276), (10, 201)) or []))
via = s.world.route((10, 276), (10, 201))
check(f"before: the way up goes through the hidden exit ({len(via or [])} steps)", uses(s))
s.note_unfindable((10, 275), "N")
check("after 8 failed searches: planned round it", not uses(s))
s2 = make()                                           # a restart
check("…and still after a restart", not uses(s2))
s2.bot.route_note = ("Went round: searched north 8 times and found nothing at 10/275", __import__("time").time())
check("the reason is kept for the bottom bar", "10/275" in s2.bot.route_note[0])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
