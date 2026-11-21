"""Running by hand faster than the game answers (8 moves typed in 2 s): the map keeps up."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, g = s.world, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
route = w.route((12, 1811), (12, 2002), level=47)
plain = []
for ex in route:
    if ex.kind != "normal":
        break
    plain.append(ex)
plain = route[1:9] if len(plain) < 8 else plain[:8]
start = (12, 1819) if route[0].kind != "normal" else (12, 1811)
g.candidates = [start]
cur = start
legs = []
for ex in [e for e in w.route(start, (12, 2002), level=47) if e.kind == "normal"][:8]:
    legs.append((ex.dir, ex.to))
for d, _to in legs:
    g.note_command(d.lower())                        # all typed before any answer
for d, to in legs:
    r = w.rooms[to]
    vis = ", ".join(sorted({"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast", "NW": "northwest",
                            "SE": "southeast", "SW": "southwest", "U": "up", "D": "down"}[x]
                           for x, e in r.exits.items() if e.visible))
    for l in (r.name, f"Obvious exits: {vis}", "[HP=684/MA=473]:"):
        s._line([(l, Style())])
check(f"8 moves typed ahead: ends in the right room ({g.candidates[:3]} vs {legs[-1][1]})", g.candidates == [legs[-1][1]])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
