"""0.8.208 (Dan): the route preview lists the places a Go to passes; striking one off finds another way, and 'Go this
way' keeps out of it for that Go to only."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.routepreview import summarize
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 60
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, w = s.bot, s.world
start, target = (1, 1), (17, 2435)                   # Silvermere → Bank of Arlysia
s.state.candidates = [start]
r1 = b.plan_route(start, target, None)
check(f"a way there ({len(r1) if r1 else None} rooms)", r1)
rows = summarize(w, start, r1)
check(f"places listed, start first, target last ({len(rows)})", rows[0][1][0] == start and rows[-1][1][-1] == target)
check("a run of same-named rooms is one row", all(rows[i][0] != rows[i + 1][0] for i in range(len(rows) - 1)))
mid = max(rows[1:-1], key=lambda r: len(r[1]))       # strike off the longest stretch on the way
w.user_avoid = frozenset(mid[1])
r2 = b.plan_route(start, target, None)
w.user_avoid = None
check(f"avoid '{mid[0]}': another way, not through it ({len(r2) if r2 else None} rooms)",
      r2 is None or not any(tuple(ex.to) in set(mid[1]) for ex in r2))
check("…and it's different", r2 is None or [tuple(e.to) for e in r2] != [tuple(e.to) for e in r1])
# Go this way: that Go to keeps out of them; another Go to doesn't
b._trip_avoid = (target, frozenset(mid[1]))
b.goto(target)
check("Go to that place: the struck-off rooms apply", w.user_avoid == frozenset(mid[1]))
b.stop("test")
b.goto((1, 297))
check("a Go to somewhere else: they don't", not w.user_avoid)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
