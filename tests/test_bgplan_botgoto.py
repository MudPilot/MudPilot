"""HUNT_1123 #24: Go tos the bot starts itself (back to the loop, errands, trips, Comeback…) froze the window for 2-13 s
while the route was worked out on its thread. Now they go through the same background planner as yours (bgplan):
the planning runs on the 'route-plan' thread, the walk waits meanwhile, and what the caller did with goto()'s answer
runs on the window's thread when it's in."""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st); s._no_log_file = True
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b = s.bot

calls, gate, answer = [], threading.Event(), {"v": True}
def fake_goto(target, then=None, ask=None, _retry=False, _looked=False):
    calls.append({"target": target, "then": then, "retry": _retry, "by": b.__dict__.pop("_goto_by_next", None),
                  "thread": threading.current_thread().name, "planning": getattr(b, "_planning", False)})
    gate.wait(5)
    return answer["v"]
b.goto = fake_goto

cbs = []
def after(ms, f): cbs.append(f)
def pump(limit=10):
    t0 = time.time()
    while cbs and time.time() - t0 < limit:
        cbs.pop(0)()
        time.sleep(0.005)

# 1: without the window (tests, headless): straight through, goto()'s answer back, done right away
s.tk_after = None
gate.set(); got = []
r = b.goto_bg((1, 2), done=got.append)
check(f"headless: on this thread, answer returned ({r}, {calls[-1]['thread']})",
      r is True and calls[-1]["thread"] == threading.current_thread().name and got == [True])

# 2: a real call site (a shop trip's 'cash for an item: plan it again') goes through the planner's thread
s.tk_after = after
calls.clear(); gate.clear()
s.trips.trip = {"kind": "withdraw", "back": (type("P", (), {"title": "Orc loop"})(), False), "goto": (1, 543), "then": None}
s.trips._back("done")
time.sleep(0.1)
check(f"trip's Go to planned on the worker thread ({[c['thread'] for c in calls]})",
      len(calls) == 1 and calls[0]["thread"] == "route-plan" and calls[0]["target"] == (1, 543))
check(f"…who started it is said as before ({calls[0]['by'] if calls else None!r})",
      bool(calls) and str(calls[0]["by"]).startswith("shoptrips._back"))
check("…the window's thread wasn't held up: still planning", b._planning)
b.walking = True
b.walk([], False)
check(f"…the walk waits meanwhile ({b.status!r})", b.status.startswith("Calculating route"))
b.walking = False
gate.set(); pump()
check("…and it's over afterwards", not b._planning and getattr(b, "_bg_goto", None) is None)

# 3: done(ok) on the window's thread with goto()'s answer; the same Go to again while planning isn't a 2nd plan
calls.clear(); gate.clear(); answer["v"] = False; got = []
r = b.goto_bg((3, 4), done=lambda ok_: got.append((ok_, threading.current_thread().name)))
time.sleep(0.05)
r2 = b.goto_bg((3, 4), done=lambda ok_: got.append(("again", ok_)))
check(f"worker: returns None at once ({r})", r is None)
check(f"the same Go to while it's being worked out: not planned twice ({len(calls)}, {r2})", len(calls) == 1 and r2 is None)
gate.set(); pump()
check(f"done gets 'no route' on the window's thread ({got})", got == [(False, threading.current_thread().name)])

# 4: a Stop while it's worked out: what the caller would have done with the answer doesn't happen
calls.clear(); gate.clear(); got = []
b.goto_bg((5, 6), done=got.append)
time.sleep(0.05)
b._stop_seq = getattr(b, "_stop_seq", 0) + 1
gate.set(); pump()
check(f"stopped meanwhile: no done ({got})", got == [])

# 5: back to the loop (give_up): no way to its start → started from here, as before — once the answer's in
from mudpilot.megamud_files import MPath
started = []
b.start_path = lambda mp, loop=None, checked=False: started.append((mp, loop))
class Step:
    def __init__(self, room): self.room = room
import mudpilot.automation as A
A.MPath = type("MP", (), {})          # give_up checks isinstance(after, MPath)
class Loop(A.MPath):
    title = "Orc loop"; resolved = True
    steps = [Step((1, 100)), Step((1, 101))]
loop = Loop()
s.state.candidates = [(1, 5)]
calls.clear(); gate.clear(); answer["v"] = False; b._gave_up_at = 0
b.stop = lambda *a, **k: None
r = b.give_up("Not walking 'Go to 1/543': no way", after=loop, target=(1, 543))
time.sleep(0.05)
check(f"give_up: back-to-the-loop Go to on the worker ({[c['thread'] for c in calls]}, {r})",
      r is True and len(calls) == 1 and calls[0]["thread"] == "route-plan" and calls[0]["target"] == (1, 100) and not started)
gate.set(); pump()
check(f"…no way to its start: the loop starts from here ({started})", started == [(loop, True)])
A.MPath = MPath

print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
