"""0.8.227.5 (Dan: "rafts are huge -stealth and pretty much make it impossible to sneak unless you're a sneaking class
and have done the perfect stealth quest... MudPilot just attempts to sneak over and over and never moves anywhere").
Miserable with a log raft: 'st' says Stealth -17 (the old pattern only read positive numbers), every 'sn' answers
"You don't think you're sneaking.", and with "don't move unless sneaking" on the walk sent 'sn' every 2 s for good."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_sneak_raft"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, g = s.bot, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
feed("Name: Miserable Revolution             Lives/CP:      8/2",
     "Race: Nekojin     Exp: 2384206880      Perception:    126",
     "Class: Mage       Level: 52            Stealth:       118")
check(f"Stealth 118 read ({g.stealth})", g.stealth == 118 and g.stealth_read)
check("…sneaking can work", not b._sneak_hopeless())
feed("Name: Miserable Revolution             Lives/CP:      8/2",
     "Class: Mage       Level: 52            Stealth:       -17")
check(f"Stealth -17 read (it used to stay at 118: {g.stealth})", g.stealth == -17)
check("…no sneaking with it, and it says why", b._sneak_hopeless() and any("Stealth is -17" in l for l in logs))
# 'st' not read yet, a raft in the pack
g.stealth_read = False; g.stealth = 0; logs.clear()
g.carrying = "90 runic coins, log raft, rope and grapple"
check("a raft in the pack, 'st' not read: no sneaking", b._sneak_hopeless())
g.carrying = "90 runic coins, rope and grapple"
check("no raft: sneaking can work", not b._sneak_hopeless())
# good Stealth, but 'sn' keeps failing: 3 in a row and it walks on for 5 minutes
g.stealth_read, g.stealth = True, 40
for _ in range(3):
    feed("Attempting to sneak...You don't think you're sneaking.")
check(f"3 failed sneaks in a row: walk on without ({g.sneak_fails})", g.sneak_fails == 3 and b._sneak_hopeless())
g.sneak_fail_at -= b.SNEAK_REST_SECS + 1
check("…5 minutes on: try again", not b._sneak_hopeless())
feed("Attempting to sneak...")
check("a sneak that works resets the count", g.sneak_fails == 0 and g.sneaking)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
