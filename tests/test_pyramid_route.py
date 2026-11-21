"""Great Pyramid (Paradigm map, pMUD's findings): 1000-doors that never open are shut for routing (timed ones and
Dan's walked level 3 excepted), the level 4 maze carries on after its second pass through 12/2052, and the top
sphinx wants 'ask sphinx time'."""
import os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB
from mudpilot import board_fixes
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "world.db")
shutil.copy2(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"), db)
w = WorldDB(db)
check("both pyramid segments fit the map", board_fixes.apply(w) == 2)
R = lambda n: (12, n)
check("12/2004 S (a 1000-door that never opens) is shut", not w.can_use(w.rooms[R(2004)].exits["S"]))
check("12/2004 N (timed) is open", w.can_use(w.rooms[R(2004)].exits["N"]))
check("12/2002 S (on Dan's walked level 3) is open", w.can_use(w.rooms[R(2002)].exits["S"]))
r = w.route(R(2002), R(2085), level=47, have={1175})
rooms = [R(2002)] + [e.to for e in r or []]
check("2002 → top follows Dan's level 3", r and " ".join(e.dir for e in r[:22]) ==
      "S E S S E E E E E N W N N W W E S W W S E U")
check("…never tries 12/2004 S", not any(a == R(2004) and b == R(2049) for a, b in zip(rooms, rooms[1:])))
check("…goes through the level 4 maze to 12/2077 and on to 12/2085", R(2077) in rooms and rooms[-1] == R(2085))
full = w.route(R(2052), R(2077), level=47)
check("from 12/2052 at the start: the whole 22-move maze", full and len(full) == 22)
w.seg_progress = {}
maze = next(s for s in w.segments if "level 4" in s["name"])
for a, b in zip(maze["nodes"][:15], maze["nodes"][1:15]):      # walk it up to the second visit of 12/2052
    board_fixes.note_move(w, a, b)
second = w.route(R(2052), R(2077), level=47)
check(f"second time at 12/2052: carry on with the last 8 moves ({second and len(second)})",
      second and " ".join(e.dir for e in second) == "E E N N N W S U")
w.seg_progress = {R: (14, time.time() - 2000) for R in [maze["name"]]}
again = w.route(R(2052), R(2077), level=47)
check("an old memory of the maze is forgotten (starts over)", again and len(again) == 22)
check("top sphinx (Paradigm): 'ask sphinx E'", w.rooms[R(2085)].exits["U"].action_cmds() == ["ask sphinx E"])
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
