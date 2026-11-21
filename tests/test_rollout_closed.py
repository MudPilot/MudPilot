"""Evolution (2026-11-03, twice): closed for the restart at once, but restart.request outlived it on R: (still locked
over the network), so the rollout waited 7 minutes for him. A fresh 'Holding' counts; the app retries the delete."""
import os, sys, time, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
import rollout
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
d = tempfile.mkdtemp()
c = os.path.join(d, "control"); os.makedirs(c)
rollout.DIRS["--t"] = d
log, req = os.path.join(c, "launcher.log"), os.path.join(c, "restart.request")
open(log, "w", encoding="utf-8").write("x  Holding (settings being edited)\n")
os.utime(log, (time.time() - 3600, time.time() - 3600))      # an old Holding from the last restart
asked = time.time()
open(req, "w").close()
check("asked, still running (old Holding, request there): not closed", not rollout.closed_held("--t", asked))
open(log, "a", encoding="utf-8").write("y  MudPilot closed for a restart\ny  Holding (settings being edited)\n")
check("closed (fresh Holding) though the request file is stuck: closed", rollout.closed_held("--t", asked))
os.remove(req)
os.utime(log, (time.time() - 3600, time.time() - 3600))
check("old Holding, request gone: closed (as before)", rollout.closed_held("--t", asked))
# the app's delete tries again
from mudpilot.control import ControlBox
cb = ControlBox.__new__(ControlBox)
cb.s = type("S", (), {"log": lambda self, m: None})()
open(req, "w").close()
real, n = os.remove, {"i": 0}
def flaky(p):
    n["i"] += 1
    if n["i"] < 3:
        raise PermissionError("in use")
    real(p)
os.remove = flaky
cb._drop(req)
os.remove = real
check(f"locked for a moment: removed on a retry ({n['i']} tries)", not os.path.exists(req))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
