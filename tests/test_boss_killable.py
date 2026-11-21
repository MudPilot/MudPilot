"""Only killable bosses (exp or drops, not 999-protected NPCs) are listed, and only once killed."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import bosses as B
from mudpilot.worlddb import WorldDB
B.BOSS_FILE_OVERRIDE = os.path.join(tempfile.mkdtemp(), "b.json")
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "data", "boards", "Paradigm", "world.db"))
class S: pass
s = S(); s.world = w; s.log = lambda *a: None; s.on_alert = lambda *a: None
class St: room = None; candidates = []; view = None; in_combat = False
s.state = St(); s.settings = None
t = B.BossTracker(s)
name = lambda n: next(m for m in w.monsters.values() if m["name"] == n)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
check("wounded messenger not killable", not t.killable(name("wounded messenger")))
check("guardian golem killable", t.killable(name("guardian golem")))
check("Mayor Godfrey killable", t.killable(name("Mayor Godfrey")))
g = name("guardian golem")
t.rec(g)["seen"] = 1
check("seen-only boss not listed", g not in t.tracked())
t.record_kill(g)
check("killed boss listed", g in t.tracked())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
