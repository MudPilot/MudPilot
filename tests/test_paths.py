import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route, write_mp, read_mp, resolve_path, MPath
w = WorldDB(config.WORLD_DB)
# loop: town gates -> some room -> back
out = w.route((1, 1), (1, 16)); back = w.route((1, 16), (1, 1))
mp = path_from_route(w, (1, 1), out + back, name="Town loop")
assert mp.is_loop
d = tempfile.mkdtemp(); f = os.path.join(d, "test.mp"); write_mp(mp, f)
print(open(f).read().splitlines()[:6])
mp2 = read_mp(f)
for s in mp2.steps: s.room = s.dest = None
ok = resolve_path(w, mp2)
print("resolved:", ok, mp2.resolve_note, "loop:", mp2.is_loop, "steps:", len(mp2.steps))
assert ok and [s.room for s in mp2.steps] == [s.room for s in mp.steps]
# a path whose start hash is shared by many rooms still resolves uniquely by walking it
print("start-hash rooms:", len(w.by_hash[mp2.steps[0].hash]))
print("OK")
