"""The map's Record Path / Record Loop, and saving into the right area folder.
Dan, 2026-10-29: a treasure-digging loop made in Tierra del Fuego was filed under "MudPilot" instead of the folder
that area's other loops are in."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import read_mp, write_mp, path_from_route
from mudpilot import areafolder
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_combat = st.auto_rest = st.auto_bless = st.auto_heal = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, w, rr = s.state, s.world, s.routerec
WORDS = {"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast", "NW": "northwest",
         "SE": "southeast", "SW": "southwest", "U": "up", "D": "down"}
def at(key):
    r = w.rooms[key]
    s._line([("[HP=300/MA=250]:" + r.name, Style())])
    s._line([("Obvious exits: " + (", ".join(WORDS[d] for d in r.exits if d in WORDS) or "none"), Style())])
    g.candidates = [key]
    s.bot.tick()
# a square of four rooms somewhere: A → B → C → … back to A (find one in the data)
def ring():
    for a, ra in w.rooms.items():
        for d1, e1 in ra.exits.items():
            b = e1.to
            if d1 not in WORDS or b not in w.rooms or e1.kind != "normal":
                continue
            for d2, e2 in w.rooms[b].exits.items():
                if e2.to == a and d2 in WORDS and e2.kind == "normal":
                    return a, d1, b, d2
A, dAB, B, dBA = ring()
at(A)
check(f"start the loop in {A}", rr.start_rec("loop") is None and rr.active and rr.start == A)
s.send(dAB.lower())
at(B)
check(f"a room change is a step ({rr.steps()})", rr.steps() == 1 and rr.rooms == [A, B])
s.send("ne"); s._line([("There is no exit in that direction!", Style())]); at(B)
check("a failed move isn't recorded", rr.steps() == 1)
s.send("open door"); s.send("bash door")
s.send(dBA.lower()); at(A)
check(f"door commands go with the step through it ({rr.route})",
      rr.steps() == 2 and rr.route[1:3] == ["open door", "bash door"])
check("back at the start", rr.back_at_start())
# undo: take the last step off, walk back, carry on
rr.undo()
check(f"undo takes the step (and its door commands) off ({rr.route})", rr.steps() == 1 and len(rr.route) == 1)
at(B)
check("walking back after undo isn't a step", rr.steps() == 1 and rr.rooms == [A, B])
s.send(dBA.lower()); at(A)
check("…and the next move is", rr.steps() == 2 and rr.back_at_start())
mp, err = rr.build("Test ring")
check(f"builds a loop ({err or [ (x.room, x.dest, x.move) for x in mp.steps]})", mp and mp.is_loop and len(mp.steps) == 2)
# a loop that isn't back at the start won't build
rr.start_rec("loop"); s.send(dAB.lower()); at(B)
mp2, err2 = rr.build("x")
check(f"not back at start: {err2!r}", mp2 is None and "Not back at the start" in err2)
rr.cancel()
check("cancel stops it", not rr.active)
# path mode
at(A); rr.start_rec("path"); s.send(dAB.lower()); at(B)
mp3, err3 = rr.build("A to B")
check(f"a path ({err3})", mp3 and not mp3.is_loop and mp3.steps[-1].dest == B)
rr.finish()

# area folders
tmp = tempfile.mkdtemp()
try:
    # an imported loop in "Terra Fuego" passing through A (and its neighbours)
    imp = path_from_route(w, A, [w.rooms[A].exits[dAB], w.rooms[B].exits[dBA]], name="Fuego loop")
    imp.start_group = imp.end_group = "Terra Fuego"
    fn = os.path.join(tmp, "Fuego_loop.mp")
    write_mp(imp, fn)
    imp = read_mp(fn)
    for x, y in zip(imp.steps, path_from_route(w, A, [w.rooms[A].exits[dAB], w.rooms[B].exits[dBA]]).steps):
        x.room, x.dest = y.room, y.dest
    s.paths = [imp]
    check(f"start room on a loop in a folder → that folder ({areafolder.folder_for(s, A)})",
          areafolder.folder_for(s, A) == "Terra Fuego")
    # a room nearby, same area, not on any path
    near = next((e.to for e in w.rooms[B].exits.values() if e.to not in (A, B) and e.to in w.rooms
                 and areafolder.area_name(w, e.to) == areafolder.area_name(w, B)), None)
    if near:
        check(f"a room next to it in the same area → same folder ({near})", areafolder.folder_for(s, near) == "Terra Fuego")
    far = next(k for k in w.rooms if k[0] != A[0])
    check("nowhere near any folder → None (you're asked)", areafolder.folder_for(s, far) is None)
    # move: the MudPilot-folder loop goes to Terra Fuego, file header rewritten, nothing else
    mine = path_from_route(w, A, [w.rooms[A].exits[dAB], w.rooms[B].exits[dBA]], name="Dig loop")
    fn2 = os.path.join(tmp, "Dig_loop.mp")
    write_mp(mine, fn2)
    before = open(fn2, encoding="latin-1").read()
    m2 = read_mp(fn2)
    check(f"made the old way it's in 'MudPilot' ({m2.start_group})", m2.start_group == "MudPilot")
    check("move to Terra Fuego", areafolder.set_folder(m2, "Terra Fuego") and m2.start_group == "Terra Fuego")
    after = open(fn2, encoding="latin-1").read()
    m3 = read_mp(fn2)
    check(f"re-read: Terra Fuego ({m3.start_group})", m3.start_group == "Terra Fuego")
    check("only the folder changed", before.replace(":MudPilot:", ":Terra Fuego:") == after)
    check(f"folders list ({areafolder.folders(s)})", areafolder.folders(s) == ["Terra Fuego"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
