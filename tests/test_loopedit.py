import os, sys, tempfile, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route, write_mp, read_mp, resolve_path, STEPF
from mudpilot import loopedit
w = WorldDB(config.WORLD_DB)
out = w.route((1, 1), (1, 16)); back = w.route((1, 16), (1, 1))
mp = path_from_route(w, (1, 1), out + back, name="Town loop")
d = tempfile.mkdtemp(); f = os.path.join(d, "t.mp"); write_mp(mp, f); mp.filename = f
before = open(f, encoding="latin-1", newline="").read()
rows = loopedit.loop_rooms(mp)
assert sum(len(i) for _k, i in rows) == len(mp.steps)
# a loop out and back walks some rooms twice -> one row each
assert len(rows) < len(mp.steps), (len(rows), len(mp.steps))
key, idx = next((k, i) for k, i in rows if len(i) > 1)
walking = copy.deepcopy(mp)                     # the copy the bot is walking
assert loopedit.apply(mp, {key: {"NOATTACK": True, "DONTREST": True}}, others=[walking])
for i, s in enumerate(mp.steps):
    want = i in idx
    assert s.flag("NOATTACK") == want and s.flag("DONTREST") == want, i
    assert walking.steps[i].flags == s.flags
after = open(f, encoding="latin-1", newline="").read()
assert after.count("\r\n") == before.count("\r\n")          # line endings kept
diff = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
assert len(diff) == len(idx), diff                           # only those step lines changed
mp2 = read_mp(f)
for s in mp2.steps: s.room = s.dest = None
assert resolve_path(w, mp2)
assert [s.flag("NOATTACK") for s in mp2.steps] == [s.flag("NOATTACK") for s in mp.steps]
# clearing puts the file back exactly
assert loopedit.apply(mp, {key: {"NOATTACK": False, "DONTREST": False}})
assert open(f, encoding="latin-1", newline="").read() == before
# a file that changed under us isn't written
mp.steps[idx[0]].hash = "DEADBEEF"
assert not loopedit.apply(mp, {key: {"NOATTACK": True}})
assert open(f, encoding="latin-1", newline="").read() == before
# 0.8.227 (Dan): a room the loop passes twice — No attack on the 2nd time through only
mp.steps[idx[0]].hash = mp2.steps[idx[0]].hash
vis = loopedit.loop_visits(mp)
assert sorted(i for vs in vis.values() for v in vs for i in v) == list(range(len(mp.steps)))
vkey = next(k for k, vs in vis.items() if len(vs) == 2)
v1, v2 = vis[vkey]
assert loopedit.apply(mp, {vkey: {"visits": [{"NOATTACK": False}, {"NOATTACK": True}]}})
for i, s in enumerate(mp.steps):
    assert s.flag("NOATTACK") == (i in v2), (i, v2)
after = open(f, encoding="latin-1", newline="").read()
diff = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
assert len(diff) == len(v2), diff                           # only the 2nd pass's step lines
t1, t2 = (loopedit.visit_text(mp, v, n) for n, v in ((1, v1), (2, v2)))
assert t1.startswith("1st time through — ") and t2.startswith("2nd time through — "), (t1, t2)
assert loopedit.badge({}, False, [{"NOATTACK": False}, {"NOATTACK": True}]) == "NA 2/2"
assert loopedit.badge({}, False, [{"NOATTACK": True}, {"NOATTACK": True}]) == "NA"
assert loopedit.apply(mp, {vkey: {"visits": [{"NOATTACK": False}, {"NOATTACK": False}]}})
assert open(f, encoding="latin-1", newline="").read() == before
# 0.8.210: the map editor — tick No attack + Stash room on a room, save → step flags + this loop's stash
mp.steps[idx[0]].hash = mp2.steps[idx[0]].hash
import tkinter as tk
from types import SimpleNamespace
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
sess = Session(st); sess.world = w
root = tk.Tk(); root.withdraw()
logs = []
app = SimpleNamespace(root=root, s=sess, add_log=logs.append)
dlg = loopedit.edit_loop_dialog(app, mp)
import time; time.sleep(0.15); root.update()
root.update()
def walk(wd):
    yield wd
    for c in wd.winfo_children():
        yield from walk(c)
btn = {getattr(x, "cget")("text"): x for x in walk(dlg) if x.winfo_class() in ("TCheckbutton", "TButton")}
btn["Next room ▶"].invoke(); root.update()       # second room on the loop
k2 = rows[1][0]
btn["No attack here"].invoke(); btn["Stash room here"].invoke(); btn["Run through (time the round)"].invoke()
root.update()
btn["Save"].invoke(); root.update()
assert all(mp.steps[i].flag("NOATTACK") for i in rows[1][1]), "no attack saved"
assert st.loop_stash.get(loopedit.loop_key(mp)) == f"{k2[0]}/{k2[1]}", st.loop_stash
assert st.loop_runthru.get(loopedit.loop_key(mp)) == [f"{k2[0]}/{k2[1]}"], st.loop_runthru
assert not any(mp.steps[i].flags & ~0xFFFF for i in rows[1][1])
assert logs and "1 run-through" in logs[-1] and "1 no-attack" in logs[-1] and "stash " + f"{k2[0]}/{k2[1]}" in logs[-1], logs
# 0.8.227: the room panel's line for the 2nd time through — tick its No attack, save → only that pass
assert loopedit.apply(mp, {k: {"NOATTACK": False, "DONTREST": False} for k, _i in rows})
dlg = loopedit.edit_loop_dialog(app, mp)
time.sleep(0.15); root.update(); root.update()
nav = {x.cget("text"): x for x in walk(dlg) if x.winfo_class() == "TButton"}
keys = [k for k, _i in rows]
for _ in range(len(keys)):
    lines = [x for x in walk(dlg) if x.winfo_class() == "TLabel" and str(x.cget("text")).startswith("2nd time through")]
    if lines:
        break
    nav["Next room ▶"].invoke(); root.update()
assert lines, "no 2nd-time-through line on any room"
row = lines[0].grid_info()["row"]
na2 = [x for x in lines[0].master.grid_slaves(row=row) if x.winfo_class() == "TCheckbutton" and x.cget("text") == "No attack"]
na2[0].invoke(); root.update()
lines = [x for x in walk(dlg) if x.winfo_class() == "TLabel" and str(x.cget("text")).startswith("2nd time through")]
assert "bold" in str(lines[0].cget("font")), lines[0].cget("font")          # the pass picked is in bold
nav["Save"].invoke(); root.update()
marked = [i for i, s in enumerate(mp.steps) if s.flag("NOATTACK")]
vis = loopedit.loop_visits(mp)
two = [vs for vs in vis.values() if len(vs) > 1 and set(vs[1]) == set(marked)]
assert two and not any(mp.steps[i].flag("NOATTACK") for i in two[0][0]), (marked, vis)
assert "only some passes" in logs[-1], logs[-1]
root.destroy()
print("OK")
