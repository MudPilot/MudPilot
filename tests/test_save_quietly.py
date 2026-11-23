"""0.8.225 (bug hunt #28): a settings save that fails is logged — at most once every 10 minutes — instead of being
swallowed. What gets saved doesn't change."""
import os, sys, json, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

tmp = tempfile.mkdtemp()
config.PROFILES_DIR = os.path.join(tmp, "profiles")
config.APP_STATE = os.path.join(tmp, "app.json")
s = config.Settings()
s.profile = "Tester"
logs = []

# a working save: True, nothing logged, the file holds the same fields as before
check("good save returns True", s.save_quietly(logs.append) is True)
check("good save logs nothing", logs == [])
with open(config.Settings.profile_path("Tester"), encoding="utf-8") as f:
    saved = json.load(f)
check("the private warn clock isn't saved", "_save_warned_at" not in saved)
check("saved fields unchanged", set(saved) == set(config.asdict(s)))

# a failing save: False, one line in the log with the error
real = config.Settings.save
def boom(self):
    raise OSError("disk full")
config.Settings.save = boom
t = [1000.0]
import time as _time
real_time = _time.time
_time.time = lambda: t[0]
try:
    check("bad save returns False", s.save_quietly(logs.append) is False)
    check("bad save logged once", len(logs) == 1 and "Couldn't save your settings (disk full)" in logs[0]
          and "won't survive a restart" in logs[0])
    t[0] += 60
    s.save_quietly(logs.append)
    check("again a minute later: not logged again", len(logs) == 1)
    t[0] += 600
    s.save_quietly(logs.append)
    check("ten minutes on: logged again", len(logs) == 2)
    check("no log function: no crash", s.save_quietly() is False)
    def badlog(m):
        raise RuntimeError("log broke")
    t[0] += 700
    check("a log that raises doesn't escape", s.save_quietly(badlog) is False)
finally:
    config.Settings.save = real
    _time.time = real_time

# the session's quiet save goes through it
from mudpilot.session import Session
class Fake:
    settings = s
    hangup_items = type("H", (), {"snapshot": lambda self, why: None})()
    def __init__(self): self.lines = []
    def log(self, m): self.lines.append(m)
fk = Fake()
config.Settings.save = boom
s._save_warned_at = 0.0
try:
    Session._save_quietly(fk)
finally:
    config.Settings.save = real
check("Session._save_quietly logs a failed save", len(fk.lines) == 1 and "Couldn't save your settings" in fk.lines[0])

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
