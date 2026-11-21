"""Control folder restart (safe moment, resume.json, launcher-only) and the launcher (install a newer zip, refuse
odd zips, never touch data\\, roll back a version that crashes at once)."""
import json, os, shutil, sys, tempfile, time, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, control, launcher
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

tmp = tempfile.mkdtemp()
box = control.ControlBox(s, folder=os.path.join(tmp, "control"))
s.control = box
fired = []
box.on_restart = lambda: fired.append(1)
loop = MPath(name="Full Glades", author="", start_hash="a", end_hash="a", filename=r"C:\x\Full_Glades.mp")
s.paths = [loop]
s.bot.path, s.bot.walking, s.bot.loop = loop, True, True
s.state.party = {"Miserable": {}, "Revolution": {}}
req = os.path.join(box.dir, "restart.request")

# not opened by the launcher: nothing would reopen MudPilot, so it's refused
os.environ.pop("MUDPILOT_LAUNCHER", None)
open(req, "w").close()
box._next_check = 0; box.tick()
check("restart refused when not opened by the launcher", not fired and not os.path.exists(req))

os.environ["MUDPILOT_LAUNCHER"] = "1"
open(req, "w").close()
s.state.in_combat = True
box._next_check = 0; box.tick()
check("waits while fighting", not fired and os.path.exists(req))
s.state.in_combat = False
box._next_check = 0; box.tick()
check("closes once the fight is over", fired == [1] and not os.path.exists(req))
r = json.load(open(os.path.join(box.dir, "resume.json"), encoding="utf-8"))
check("resume.json has the loop and the party", r["path_file"] == "Full_Glades.mp" and r["walking"] and r["loop"]
      and "Revolution" in r["party"])
old = os.path.join(box.dir, "restart.request")
open(old, "w").close(); os.utime(old, (time.time() - 3600, time.time() - 3600))
fired.clear(); box._next_check = 0; box.tick()
check("a request from before this start is thrown away", not fired and not os.path.exists(old))

# next start: carry on like after a dropped line
s.bot.walking, s.bot.path, s._drop_resume, s._reinvite = False, None, None, None
back = box.load_resume()
check("resume picks the loop back up", s._drop_resume and s._drop_resume["path"] is loop and s._drop_resume["loop"])
check("…and re-invites the party", s._reinvite == ["Revolution"] and back["connect"])
check("resume.json is used once", not os.path.exists(os.path.join(box.dir, "resume.json")) and box.load_resume() is None)
# a Go to on an errand (fetching the golden lion key first) carries on to where it was going
s.bot.walking, s.bot.path = True, MPath(name="Go to 12/2005 Great Pyramid", author="", start_hash="a", end_hash="b")
s.bot.errands.active = {"target": (12, 2085), "after": None, "todo": []}
box.write_resume()
r = json.load(open(os.path.join(box.dir, "resume.json"), encoding="utf-8"))
check("an errand's Go to is remembered with its real goal", r["goto"] == [12, 2085] and r["walking"])
s.bot.errands.active = None
s._drop_resume = None
box.load_resume()
check("…and carried on after the restart", s._drop_resume and s._drop_resume["target"] == (12, 2085))
# Dan, 2026-11-10: Buddy left Evolution's party to loop Crimson Fort himself; after a restart he stood waiting for
# Evolution's invite. Walking a loop of your own: you're not following anyone
s.bot.path, s.bot.walking, s.bot.loop = loop, True, True
s.bot.x._following = "Evolution"; s._rejoin = None; s._reinvite = None
s.state.party = {"Miserable": {}, "Evolution": {}}
box.write_resume()
r = json.load(open(os.path.join(box.dir, "resume.json"), encoding="utf-8"))
check(f"own loop: no leader to wait for ({r['follow']}, party {r['party']})", r["follow"] is None and r["walking"]
      and r["path_file"] == "Full_Glades.mp")
s._drop_resume, s._rejoin = None, None
box.load_resume()
check("…carries on with the loop after the restart, no rejoin", s._drop_resume and s._drop_resume["path"] is loop
      and not s._rejoin)
# a real follower (not walking anything itself) still goes back to its leader
s.bot.walking, s.bot.path = False, None; s.bot.resume = None; s._drop_resume = None; s._reinvite = None
box.write_resume()
r = json.load(open(os.path.join(box.dir, "resume.json"), encoding="utf-8"))
check(f"follower: still rejoins its leader ({r['follow']})", r["follow"] == "Evolution")
box.load_resume()
s.bot.x._following = None; s._rejoin = None; s.state.party = {"Miserable": {}, "Revolution": {}}
box.write_status()
d = json.load(open(os.path.join(box.dir, "status.json"), encoding="utf-8"))
check("status.json written", d["by_launcher"] and "version" in d)

# ---------------------------------------------------------------- launcher
dl = os.path.join(tmp, "Downloads")
root = os.path.join(dl, "MudPilot", "MudPilot")
os.makedirs(os.path.join(root, "mudpilot")); os.makedirs(os.path.join(root, "data", "profiles"))
open(os.path.join(root, "mudpilot", "__init__.py"), "w").write('__version__ = "0.8.70"\n')
open(os.path.join(root, "mudpilot", "app.py"), "w").write("old\n")
open(os.path.join(root, "data", "profiles", "Miserable.json"), "w").write("mine\n")
launcher.CONTROL = os.path.join(root, "data", "control")

def mkzip(name, ver, extra=None, init_ver=None):
    p = os.path.join(dl, name)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("MudPilot/mudpilot/__init__.py", f'__version__ = "{init_ver or ver}"\n')
        z.writestr("MudPilot/mudpilot/app.py", "new\n")
        z.writestr("MudPilot/data/profiles/Miserable.json", "theirs\n")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return p

check("nothing newer → nothing to install", launcher.find_newer(root) is None)
mkzip("MudPilot-0.8.69.zip", "0.8.69")
check("an older zip isn't installed", launcher.find_newer(root) is None)
mkzip("MudPilot-0.8.72.zip", "0.8.72", init_ver="0.8.99")
mkzip("MudPilot-0.8.71.zip", "0.8.71")
v, zp = launcher.find_newer(root)
check("newest zip picked", v == "0.8.72")
check("a zip whose version doesn't match its name is refused", not launcher.install(v, zp, root))
v, zp = launcher.find_newer(root)
check("…and skipped from then on", v == "0.8.71")
check("good zip installs", launcher.install(v, zp, root) and launcher.installed_version(root) == "0.8.71"
      and open(os.path.join(root, "mudpilot", "app.py")).read() == "new\n")
check("data\\ is never touched", open(os.path.join(root, "data", "profiles", "Miserable.json")).read() == "mine\n")
check("old version kept for a roll-back", open(os.path.join(root, ".mp-prev", "mudpilot", "app.py")).read() == "old\n")
check("roll-back restores it", launcher.roll_back(root) and launcher.installed_version(root) == "0.8.70")
bad = mkzip("MudPilot-0.8.80.zip", "0.8.80", extra={"MudPilot/../evil.txt": "x"})
check("a zip reaching outside its folder is refused", not launcher.install("0.8.80", bad, root)
      and not os.path.exists(os.path.join(dl, "MudPilot", "evil.txt")))

# crash right after an install → roll back, skip that version, start afresh
launcher.ROOT = root
calls = []
launcher.run_mudpilot = lambda: 1
launcher._relaunch = lambda *a: calls.append(a)
launcher.find_newer = lambda root=root: None
launcher.install(*("0.8.71", os.path.join(dl, "MudPilot-0.8.71.zip")), root)
launcher.main(["--installed", "0.8.71", "0.8.70"])
check("a version crashing at once is rolled back", launcher.installed_version(root) == "0.8.70" and calls == [()])
check("…and skipped", "0.8.71" in launcher._skipped())
codes = iter([launcher.RESTART_EXIT, 0])
launcher.run_mudpilot = lambda: next(codes)
launcher.main([])
check("exit 3 reopens MudPilot, a normal close ends the launcher", next(codes, "done") == "done")

# --data PVE: same install, its own data folder (settings, logs, control) for a second character set
import subprocess, importlib
check("--data PVE → data-PVE and its own control folder", launcher.use_data("PVE") == "PVE" and
      launcher.DATA == os.path.join(root, "data-PVE") and launcher.CONTROL == os.path.join(root, "data-PVE", "control"))
check("odd characters can't reach outside", launcher.use_data("..\\x") == "x")
check("an update never touches data-PVE", "data-pve/profiles/a.json".startswith(launcher.NEVER))
seen = {}
real_call = subprocess.call
subprocess.call = lambda cmd, cwd=None, env=None: seen.update(env or {}) or 0
importlib.reload(launcher)   # the real run_mudpilot again (patched above)
launcher.ROOT = root
launcher.use_data("PVE")
launcher.run_mudpilot()
subprocess.call = real_call
check("MudPilot is told to use data-PVE", seen.get("MUDPILOT_DATA_DIR") == os.path.join(root, "data-PVE")
      and seen.get("MUDPILOT_LAUNCHER") == "1")
out = subprocess.run([sys.executable, "-c", "from mudpilot import config; print(config.DATA_DIR)"],
                     env={**os.environ, "MUDPILOT_DATA_DIR": os.path.join(tmp, "data-PVE")}, capture_output=True,
                     text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.strip()
check("…and does", out == os.path.join(tmp, "data-PVE"))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
