"""Revolution PVE, 2026-11-21: MudPilot crashed three times in 10 minutes. A Go to was being planned in the background
(bgplan swaps session.send for a queue meanwhile) when the crozier bless went out as '#etc'. Played back, the swap's
own 'eq crozier / use crozier / eq sceptre' went into the same queue; the 'use' came out after the swap was over, was
expanded into another swap, and so on: 130,000 'eq' lines without a single 'use', the window frozen, then a crash.
Now the swap goes straight out, once, and a drain pass can't spin for ever."""
import os, sys, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config, bgplan
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.char_class = "Priest"; st.char_level = 59
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x):
        sent.append(x)
        if len(sent) > 200:
            raise RuntimeError("runaway")
    def close(self): pass
s.telnet = Tel(); s._entered = True
s.state.carrying = ("platinum sceptre (Weapon Hand), golden chalice (Off-Hand), emerald-tipped crozier, iron keyring, "
                    "2 rations")

# a fake Tk 'after': callbacks run when we pump them
cbs = []
def after(ms, f): cbs.append(f)
gate = threading.Event()
def fn(ask):
    gate.wait(5)            # the planner is busy while the bless goes out on the window's thread
    return None
bgplan.plan(s, fn, after=after)
s.send("#etc", from_bot=True)          # the bless, sent while the plan runs: queued
gate.set()
t0 = time.time()
while cbs and time.time() - t0 < 10:
    f = cbs.pop(0); f()
    time.sleep(0.01)
c = [l for l in sent if l.strip()]
check(f"the swap goes out once, use included ({c})", c == [
    "remove golden chalice", "eq emerald-tipped crozier", "use emerald-tipped crozier",
    "eq platinum sceptre", "eq golden chalice"])
check("send is the session's own again afterwards", "send" not in s.__dict__)

# outside a plan: unchanged
sent.clear()
s.send("#etc", from_bot=True)
check(f"…and the same outside a plan ({[l for l in sent if l.strip()]})", [l for l in sent if l.strip()] == c)
print("ALL PASS" if ok else "SOME FAILED")
