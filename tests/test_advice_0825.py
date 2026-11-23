"""0.8.225 (HUNT_1123 #35/#36): loop advice repeats once, not every 10 laps; an upgrade alert once per item per
session, and none for an item your own rule stashes / sells / drops."""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(str(m))
s.on_alert = lambda *a, **k: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
# #35 repeat key
adv = s.advisor
lines = iter([["A loop built around here could do ~4,412k/hr (30 steps, 13 lairs) — Paths → More → Build a loop"],
              ["A loop built around here could do ~4,390k/hr (30 steps, 13 lairs) — Paths → More → Build a loop"]])
adv.advise = lambda mp: next(lines)
s.bot.laps = 10; adv.lap_check(None)
s.bot.laps = 20; adv.lap_check(None)
check(f"the same loop advice with a new figure: said once ({sum('Advice' in l for l in logs)})",
      sum("Advice" in l for l in logs) == 1)
# #36 upgrade alerts
gw = s.gearwatch
st.item_rules = ["runed stone cudgel: get, stash"]
up = ({"name": "runed stone cudgel"}, "Weapon", 23.0, {"name": "runed petrified staff"})
logs.clear()
check("an item your rule stashes: no upgrade alert", not gw._tell("runed stone cudgel", up, "here"))
up2 = ({"name": "shimmering longsword"}, "Weapon", 30.0, None)
check("another upgrade: alerted", gw._tell("shimmering longsword", up2, "here"))
gw.told["shimmering longsword"] = time.time() - 7200
check("…and not again two hours later (once per session)", not gw._tell("shimmering longsword", up2, "here"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
