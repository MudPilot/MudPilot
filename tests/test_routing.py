"""Avoid areas (Negative Power Plane by default), ask/avoid/allow, level-restricted exits."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
s = Session(st)
s.bot.DEFAULT_PROMPT_AREAS = ()          # isolate the generic avoid logic (defaults covered by test_default_prompt)
w = s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
check("default avoids Negative Power Plane, mode ask", st.avoid_names == ["Negative Power Plane"] and st.avoid_mode == "ask")
# find a route of 8+ steps, then avoid a room in its middle
start = goal = mid = direct = None
for k in list(w.rooms)[:4000]:
    r = w.route(k, list(w.rooms)[(hash(k) % len(w.rooms))])
    if r and len(r) >= 8:
        start, goal, direct = k, r[-1].to, r; mid = r[len(r) // 2].to; break
check("found a test route", direct is not None)
st.avoid_names = []; st.avoid_rooms = [f"{mid[0]}/{mid[1]}"]
s.state.candidates = [start]
asked = []
def ask(short, scenic, area):
    asked.append((short, scenic, area)); return False
st.avoid_mode = "ask"
rt = s.bot.plan_route(start, goal, ask=ask)
check(f"ask mode prompts ({asked})", asked and asked[0][0] == len(direct))
check("said no → route stays out of the avoided room", rt is None or all(ex.to != mid for ex in rt))
asked.clear()
rt = s.bot.plan_route(start, goal, ask=lambda a, b, c: True)
check("said yes → short way", rt is not None and len(rt) == len(direct))
rt = s.bot.plan_route(start, goal, ask=None)
check("a 'yes' sticks: the replan on the way keeps the short way", rt is not None and len(rt) == len(direct))
s.bot._trip_allow = {}
rt = s.bot.plan_route(start, goal, ask=None)
check("unattended (no yes) never goes through", rt is None or all(ex.to != mid for ex in rt))
st.avoid_mode = "allow"
check("allow mode goes through", len(s.bot.plan_route(start, goal)) == len(direct))
st.avoid_mode = "avoid"
rt = s.bot.plan_route(start, goal, ask=ask)
check("avoid mode never asks", not asked and (rt is None or all(ex.to != mid for ex in rt)))
# NPP name matching
st.avoid_names = ["Negative Power Plane"]; st.avoid_rooms = []
npp = [k for k, r in w.rooms.items() if "negative power plane" in r.name.lower()]
check(f"avoid set holds the NPP rooms ({len(npp)})", set(npp) <= s.bot.avoid_set())
# level-restricted exits
lv = None
for k, r in w.rooms.items():
    for d, ex in r.exits.items():
        m = w.LEVEL_RE.search(ex.etype or "") if ex.kind == "restricted" else None
        if m and ex.to in w.rooms and int(m.group(1)) > 0:
            lv = (k, ex, int(m.group(1)), int(m.group(2))); break
    if lv: break
if lv:
    k, ex, lo, hi = lv
    r_lo = w.route(k, ex.to, level=lo)
    check(f"level {lo} uses the '{ex.etype}' exit", r_lo is not None and r_lo[0].to == ex.to)
    if lo > 1:
        r_no = w.route(k, ex.to, level=lo - 1)
        check(f"level {lo-1} doesn't", r_no is None or r_no[0] is not ex)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
