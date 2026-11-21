"""Dan, 2026-11-16: knocked off his feet in Stonecaps, the path's step got 'Your command had no effect.' and MudPilot
asked 'pro' every few minutes, always to find the room it already thought. Knocked down / held: not the wrong room."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
b = s.bot
asked = []
b.locate_now = lambda why: asked.append(why) or True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def step():
    b.walking, b.path = True, type("P", (), {"steps": [], "title": "Stonecaps"})()
    b._last_cmd = ("nw", False); b._step_sent_at = time.time(); b._macro_at = 0
b.x.ailments["knocked"] = time.time()
step(); b.note_line("Your command had no effect.")
check(f"knocked down: no 'pro' ({asked})", not asked)
b.x.ailments.pop("knocked", None)
s.msgrules.conditions["held"] = {"since": time.time(), "rule": "knockdown"}
step(); b.note_line("Your command had no effect.")
check(f"held (Messages): no 'pro' ({asked})", not asked)
s.msgrules.conditions.pop("held", None)
step(); b.note_line("Your command had no effect.")
check(f"on our feet: still checks where we are ({asked})", len(asked) == 1)
s.msgrules.conditions["held"] = {"since": time.time(), "rule": "knockdown"}
s.msgrules._clear("held", "wore off")
asked.clear(); step(); b.note_line("Your command had no effect.")
check(f"held wore off a moment ago: still no 'pro' ({asked})", not asked)
s.msgrules.cleared_at["held"] = time.time() - 30
step(); b.note_line("Your command had no effect.")
check(f"long since back up: checks again ({asked})", len(asked) == 1)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
