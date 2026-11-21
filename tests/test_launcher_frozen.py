"""The compiled build's updates (Dan, 2026-11-05: an exe for players outside the house, no source in it). Each
version unpacks into app\\<version>\\ beside the one running — a running character's compiled files can't be
written over, and three characters share the mini PC's install. Source zips and compiled zips don't mix."""
import os, sys, shutil, tempfile, zipfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import launcher as L
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

tmp = tempfile.mkdtemp()
root = os.path.join(tmp, "MudPilot")
os.makedirs(os.path.join(root, "app", "0.8.160"))
open(os.path.join(root, "app", "0.8.160", "MudPilot.exe"), "w").close()
L.ROOT, L.APPS = root, os.path.join(root, "app")
L.CONTROL = os.path.join(root, "data", "control")
L.log = lambda m: logs.append(m)
logs = []

def frozen_zip(v, extra=()):
    p = os.path.join(tmp, f"MudPilot-{v}.zip")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"MudPilot/app/{v}/version.txt", v + "\n")
        z.writestr(f"MudPilot/app/{v}/MudPilot.exe", "exe " + v)
        z.writestr(f"MudPilot/app/{v}/mudpilot/bundled/Paradigm.db", "db")
        z.writestr("MudPilot/MudPilot.exe", "starter " + v)
        for n, body in extra:
            z.writestr(n, body)
    return p

def source_zip(v):
    p = os.path.join(tmp, f"src-{v}.zip")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("MudPilot/mudpilot/__init__.py", f'__version__ = "{v}"\n')
    return p

L.FROZEN = True
L.running_version = lambda: "0.8.160"
check(f"installed: {L.app_versions()}", L.app_versions() == ["0.8.160"])
check("a newer compiled zip installs", L.install("0.8.161", frozen_zip("0.8.161")))
check(f"…beside the old one, not over it ({L.app_versions()})", L.app_versions() == ["0.8.160", "0.8.161"])
check("…the starter on top replaced", open(os.path.join(root, "MudPilot.exe")).read() == "starter 0.8.161")
check("…nothing left half-done", not os.path.exists(os.path.join(root, "app", "0.8.161.part")))
check(f"newest: 0.8.161 ({L.newest_app()})", L.newest_app() == "0.8.161")
check("a source zip is refused by the compiled build", not L.install("0.8.162", source_zip("0.8.162")))
check("a zip reaching outside app/<version>/ is refused",
      not L.install("0.8.163", frozen_zip("0.8.163", [("MudPilot/mudpilot/evil.py", "x")])))
L.install("0.8.164", frozen_zip("0.8.164"))
L.install("0.8.165", frozen_zip("0.8.165"))
L.running_version = lambda: "0.8.161"
L.prune_apps()
check(f"pruned to the newest two and the one running ({L.app_versions()})",
      L.app_versions() == ["0.8.161", "0.8.164", "0.8.165"])
L._skip("0.8.165")
check(f"a crashed one is passed over ({L.newest_app()})", L.newest_app() == "0.8.164")
check("…and rolling back works while an older one is there", L.roll_back())

L.FROZEN = False
src = os.path.join(tmp, "src")
os.makedirs(os.path.join(src, "mudpilot"))
open(os.path.join(src, "mudpilot", "__init__.py"), "w").write('__version__ = "0.8.159"\n')
with zipfile.ZipFile(frozen_zip("0.8.170")) as z:
    try:
        L.check_zip(z, "0.8.170"); refused = False
    except ValueError:
        refused = True
check("a compiled zip is refused by a source install", refused)
check("source zips still install on a source install", L.install("0.8.162", source_zip("0.8.162"), root=src)
      and open(os.path.join(src, "mudpilot", "__init__.py")).read().count("0.8.162"))
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
