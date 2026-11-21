"""Miserable PVE, 2026-11-06: the rotting beholder's stench ('You feel nauseous!', then 'You retch uncontrollably!'
eating commands) — every retch broke the rest, the fighting gear went back on, the next rest swapped the regen gear
on again: a wall of eq lines for minutes. Sick: one swap, then sit in it till 'You feel less sick.'"""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
b.send = lambda c, **k: sent.append(c)
b.send_macro = lambda m: sent.append("MACRO " + m)
b._swap_cmds = lambda kind: ("", "eq shawl^Meq pho")
b._regen_gear = lambda kind: (["eq runed cape"], ["eq faded shawl"])
line = lambda t: s._line([(t, Style())])
line("You feel nauseous!")
check("nauseous → sick", b._sick())
b._begin_swap("rest")
check(f"first rest: the regen gear goes on ({sent})", sent == ["eq runed cape"])
sent.clear()
g.resting = True; b._swap_tick([], False)
g.resting = False
line("You retch uncontrollably!")
b._swap_tick([], False)
check(f"a retch broke the rest: the regen gear stays on ({sent})", not sent and b._swap == "rest")
b._begin_swap("med")
check(f"…and meditating instead doesn't swap again ({sent})", not sent and b._swap == "rest")
line("You feel less sick.")
g.confused_fail_at = 0
b._swap_tick([], False)
check(f"well again: the fighting gear goes back on ({sent})", "eq faded shawl" in sent and b._swap is None)
sys.exit(0 if ok else 1)
