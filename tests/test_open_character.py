"""0.8.180 (Dan, 2026-11-12): Miserable PVE froze and was closed; reopening it gave a second PvP Miserable (the
picker's 20 s auto-choice opened data\\ though it was already open), and the two kept logging each other off.
- the picker's auto-choice never opens a folder that's already open; the launcher won't run a second copy on one
- File -> Open character lists every character, marks this window's and open ones, and opens a pick via --data
- the lair-danger fight simulation is reused across small AC/DR changes (buffs on/off) instead of re-run"""
import os, sys, json, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

from mudpilot import launcher
src = open(os.path.join(here, "mudpilot", "launcher.py"), encoding="utf-8").read()
check("auto-choice skips data\\ when it's open", 'if folder_in_use(os.path.join(root, "data")):' in src)
check("_run refuses a second copy on an open folder", "def _run(just):\r\n    if folder_in_use(DATA)" in src
      or "def _run(just):\n    if folder_in_use(DATA)" in src)

root = tempfile.mkdtemp()
for d, who in (("data", "Miserable"), ("data-PVE", "MiserablePVE"), ("data-Buddy", "Buddy pve2")):
    os.makedirs(os.path.join(root, d, "control"))
    json.dump({"profile": who}, open(os.path.join(root, d, "app.json"), "w"))
json.dump({"pid": os.getppid() or 4}, open(os.path.join(root, "data", "control", launcher.IN_USE), "w"))
chars = launcher.character_folders(root)
check(f"lists every character ({[c[2] for c in chars]})", [c[2] for c in chars] == ["Miserable", "Buddy pve2", "MiserablePVE"]
      or sorted(c[2] for c in chars) == ["Buddy pve2", "Miserable", "MiserablePVE"])
check("a running one counts as open", launcher.folder_in_use(os.path.join(root, "data")))
check("a closed one doesn't", not launcher.folder_in_use(os.path.join(root, "data-PVE")))

app = open(os.path.join(here, "mudpilot", "app.py"), encoding="utf-8").read()
check("File menu has Open character…", 'label="Open character…", command=self.open_character' in app)
check("…and opens through the launcher with --data", '"-m", "mudpilot.launcher", "--data", name' in app)

from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
d = s.danger
import mudpilot.monattack as ma
calls = []
real = ma.simulate
ma.simulate = lambda *a, **k: (calls.append(1), {"avg": 12.0})[1]
mon = {"num": 1, "attack_data": {}}
s.state.ac, s.state.dr = 80, 10
v1 = d.mob_dpr(mon)
s.state.ac = 86                                    # a buff came back on
v2 = d.mob_dpr(mon)
check(f"small AC change: no new simulation ({len(calls)} run)", len(calls) == 1 and v1 == v2 == 12.0)
s.state.ac = 120
d.mob_dpr(mon)
check(f"a big change does simulate again ({len(calls)} runs)", len(calls) == 2)
ma.simulate = real
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
