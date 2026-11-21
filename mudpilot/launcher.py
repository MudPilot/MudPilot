"""MudPilot launcher (pythonw -m mudpilot.launcher): opens MudPilot, and when MudPilot closes for a control-folder
restart (exit code 3) installs any newer MudPilot-*.zip from Downloads, waits while data\\control\\hold exists, and
opens it again — logged back in and carrying on (see control.py). Closing MudPilot yourself ends the launcher too.
'--data PVE' runs a second character set from the same install on data-PVE\\ (its own settings, logs and control
folder), so every update reaches both.

Self-healing: a version that crashes within a minute of being installed is rolled back to the one before, and
that zip is skipped from then on. Only zips shaped like ours are installed (a MudPilot/ folder with mudpilot/
inside, version matching the file name, nothing outside the folder); data\\ and .venv\\ are never touched.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # ...\MudPilot (has mudpilot\ and data\)
# The compiled build (Nuitka): each version is a folder of its own, ...\MudPilot\app\0.8.160\MudPilot.exe, and an
# update unpacks a new one beside it — a running character's compiled files can't be written over (three share an
# install on the mini PC). MudPilot.exe at the top opens the newest.
FROZEN = "__compiled__" in globals()
LINUX = sys.platform.startswith("linux")
EXE_NAME = "MudPilot.exe" if os.name == "nt" else "MudPilot"      # (the Linux build has no .exe)
EXE = sys.executable
if FROZEN:
    from mudpilot.config import long_path
    ROOT = long_path(ROOT)                               # (handed to us as 8.3 short names: '08E0B8~1.159')
    EXE = os.path.join(ROOT, EXE_NAME)                  # (ROOT so far is app\<version>\; sys.executable isn't the exe)
    ROOT = os.path.dirname(os.path.dirname(ROOT))
APPS = os.path.join(ROOT, "app")
VER_RE = re.compile(r"^\d+(?:\.\d+)+$")
DATA = os.path.join(ROOT, "data")
CONTROL = os.path.join(DATA, "control")
PREV = os.path.join(ROOT, ".mp-prev")
RESTART_EXIT = 3
HOLD_MAX = 60 * 60                  # a forgotten 'hold' can't keep MudPilot closed for more than an hour
CRASH_SECS = 60
# the Linux build is MudPilot-x.y.z-linux.zip; each system only ever takes its own (the Windows one never matched it)
ZIP_RE = re.compile(r"^MudPilot-(\d+(?:\.\d+)+)-linux\.zip$" if FROZEN and LINUX else r"^MudPilot-(\d+(?:\.\d+)+)\.zip$",
                    re.I)
NEVER = ("data/", "data-", ".venv/", ".mp-prev/")
DATA_NAME = ""


def use_data(name):
    """--data PVE: this launcher, and the MudPilot it opens, use data-PVE\\ instead of data\\."""
    global DATA, CONTROL, DATA_NAME
    DATA_NAME = "".join(c for c in (name or "") if c.isalnum())[:20]
    DATA = os.path.join(ROOT, f"data-{DATA_NAME}" if DATA_NAME else "data")
    CONTROL = os.path.join(DATA, "control")
    return DATA_NAME


# ------------------------------------------------------------ one MudPilot per data folder
# Dan, 2026-10-28: a third character opened on data\ (the party's folder) — two MudPilots sharing one log, one
# status file and one control folder, and data\app.json now opening to the wrong character. Each launcher marks
# its folder in use; opening MudPilot on a folder that's taken asks for another character's folder, or makes one.
IN_USE = "in-use.json"


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def folder_in_use(data_dir) -> bool:
    import json
    try:
        with open(os.path.join(data_dir, "control", IN_USE), encoding="utf-8") as f:
            pid = json.load(f).get("pid")
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def mark_in_use():
    import json
    try:
        os.makedirs(CONTROL, exist_ok=True)
        with open(os.path.join(CONTROL, IN_USE), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "t": time.time()}, f)
    except OSError:
        pass


def unmark_in_use():
    import json
    p = os.path.join(CONTROL, IN_USE)
    try:
        with open(p, encoding="utf-8") as f:
            mine = json.load(f).get("pid") == os.getpid()
        if mine:
            os.remove(p)
    except (OSError, ValueError):
        pass


def character_folders(root=None) -> list:
    """[(name for --data, folder, character in it)] — data\\ is name ''."""
    import json
    root = root or ROOT
    out = []
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if not os.path.isdir(full) or not (d == "data" or d.startswith("data-")):
            continue
        try:
            with open(os.path.join(full, "app.json"), encoding="utf-8") as f:
                who = json.load(f).get("profile") or ""
        except (OSError, ValueError):
            who = ""
        out.append(("" if d == "data" else d[len("data-"):], full, who))
    return out


def new_character_folder(name, root=None, copy_from=None) -> str:
    """data-<Name>\\ for a new character: its own settings, logs and control folder, the board data copied in
    (MME map, paths, lairs) so it walks like the others from the start."""
    import json
    root = root or ROOT
    safe = "".join(c for c in (name or "") if c.isalnum())[:20]
    if not safe:
        raise ValueError("a name with letters or numbers")
    full = os.path.join(root, f"data-{safe}")
    os.makedirs(os.path.join(full, "profiles"), exist_ok=True)
    src = os.path.join(copy_from or os.path.join(root, "data"), "boards")
    if os.path.isdir(src) and not os.path.isdir(os.path.join(full, "boards")):
        shutil.copytree(src, os.path.join(full, "boards"))
    if not os.path.exists(os.path.join(full, "app.json")):
        with open(os.path.join(full, "app.json"), "w", encoding="utf-8") as f:
            json.dump({"profile": name.strip()}, f)
    prof = os.path.join(full, "profiles", name.strip() + ".json")
    if not os.path.exists(prof):
        # the board you play on comes along (address, board, log-in triggers); the character's own settings
        # start fresh, and you type its user name and password once
        base = {}
        src_dir = copy_from or os.path.join(root, "data")
        try:
            with open(os.path.join(src_dir, "app.json"), encoding="utf-8") as f:
                was = json.load(f).get("profile") or "Default"
            with open(os.path.join(src_dir, "profiles", was + ".json"), encoding="utf-8") as f:
                base = json.load(f)
        except (OSError, ValueError):
            pass
        keep = {k: base[k] for k in ("host", "port", "board", "triggers", "settings_version") if k in base}
        with open(prof, "w", encoding="utf-8") as f:
            json.dump({**keep, "profile": name.strip(), "username": "", "my_name": name.strip()}, f, indent=1)
    return safe


def pick_folder(root=None):
    """Which character? (Dan: open to a choice, not straight into the last one — that logged in over the one
    already running.) Open ones are shown but can't be picked. A free one, or a new one; None = don't open."""
    import tkinter as tk
    from tkinter import ttk, simpledialog, messagebox
    root = root or ROOT
    win = tk.Tk()
    win.title("MudPilot — which character?")
    win.resizable(False, False)
    choice = {"v": None}
    fr = ttk.Frame(win, padding=14)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Which character?").pack(anchor="w", pady=(0, 8))
    for n, f, who in character_folders(root):
        label = f"{who or 'character'}   ({os.path.basename(f)})"
        if folder_in_use(f):
            ttk.Button(fr, text=label + " — already open", state="disabled").pack(fill="x", pady=2)
            continue
        ttk.Button(fr, text=label, command=lambda n=n: (choice.update(v=("open", n)), win.destroy())).pack(fill="x",
                                                                                                          pady=2)

    def new():
        nm = simpledialog.askstring("New character", "Character name (as you log in with it):", parent=win)
        if nm and nm.strip():
            choice["v"] = ("new", nm.strip())
            win.destroy()
    ttk.Button(fr, text="New character…", command=new).pack(fill="x", pady=(8, 2))
    ttk.Button(fr, text="Cancel", command=win.destroy).pack(fill="x", pady=2)
    # Dan, 2026-10-28: on the headless mini PC nobody is there to click this, so a reopen froze the party
    # character for an hour. If nothing's chosen in 20 s, open this launcher's own folder (data) and carry on.
    def _auto():
        if choice["v"] is None:
            if folder_in_use(os.path.join(root, "data")):
                return       # 0.8.180: data\ is already open — never open it a second time on its own (Dan,
                             # 2026-11-12: reopening Miserable PVE gave a second PvP Miserable, kicking each other)
            choice["v"] = ("open", "")
        try:
            win.destroy()
        except tk.TclError:
            pass
    try:
        win.after(20000, _auto)
    except tk.TclError:
        pass
    win.mainloop()
    v = choice["v"]
    if not v:
        return None
    if v[0] == "open":
        return v[1]
    try:
        return new_character_folder(v[1], root)
    except (OSError, ValueError) as ex:
        try:
            messagebox.showerror("MudPilot", f"Couldn't make a folder for {v[1]}: {ex}")
        except Exception:
            pass
        return None


def log(msg):
    try:
        os.makedirs(CONTROL, exist_ok=True)
        with open(os.path.join(CONTROL, "launcher.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def running_version() -> str:
    if FROZEN:
        return os.path.basename(os.path.dirname(EXE))   # its app\<version>\ folder (what the newest is judged by)
    from mudpilot import __version__
    return __version__


def app_versions(root=None) -> list:
    """Compiled versions installed in app\\, oldest first."""
    d = os.path.join(root or ROOT, "app")
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted((n for n in names if VER_RE.match(n) and os.path.exists(os.path.join(d, n, EXE_NAME))),
                  key=vtuple)


def newest_app(root=None):
    vs = [v for v in app_versions(root) if v not in _skipped()]
    return vs[-1] if vs else None


def installed_version(root=None) -> str:
    root = root or ROOT
    if FROZEN:
        return max([running_version()] + app_versions(root), key=vtuple)
    try:
        with open(os.path.join(root, "mudpilot", "__init__.py"), encoding="utf-8") as f:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
            return m.group(1) if m else "0"
    except OSError:
        return "0"


def _skipped() -> set:
    try:
        with open(os.path.join(CONTROL, "skip-versions.txt"), encoding="utf-8") as f:
            return {ln.strip() for ln in f if ln.strip()}
    except OSError:
        return set()


def _skip(v):
    os.makedirs(CONTROL, exist_ok=True)
    with open(os.path.join(CONTROL, "skip-versions.txt"), "a", encoding="utf-8") as f:
        f.write(v + "\n")


def find_newer(root=None):
    """The newest MudPilot-x.y.z.zip next to the install (Downloads\\ or Downloads\\MudPilot\\) above what's in."""
    root = root or ROOT
    have, skip = vtuple(installed_version(root)), _skipped()
    best = None
    for d in {os.path.dirname(os.path.dirname(root)), os.path.dirname(root)}:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            m = ZIP_RE.match(n)
            if m and m.group(1) not in skip and vtuple(m.group(1)) > have and \
                    (best is None or vtuple(m.group(1)) > vtuple(best[0])):
                best = (m.group(1), os.path.join(d, n))
    return best


def check_zip(zf: zipfile.ZipFile, version: str) -> list:
    """The members to install (name inside MudPilot/, ZipInfo) — or ValueError if it isn't one of ours."""
    out = []
    for zi in zf.infolist():
        n = zi.filename.replace("\\", "/")
        if not n.startswith("MudPilot/") or n.startswith("/") or ".." in n.split("/") or ":" in n:
            raise ValueError(f"unexpected entry {n!r}")
        rel = n[len("MudPilot/"):]
        if not rel or rel.lower().startswith(NEVER):
            continue
        out.append((rel, zi))
    if FROZEN:
        # the compiled zip: everything in app/<version>/, plus the top-level MudPilot.exe and the guides
        for rel, _zi in out:
            if not rel.startswith(f"app/{version}/") and "/" in rel.rstrip("/") and rel.rstrip("/") != "app":
                raise ValueError(f"unexpected entry {rel!r}")
        try:
            v = zf.read(f"MudPilot/app/{version}/version.txt").decode("utf-8").strip()
        except KeyError:
            raise ValueError("not a compiled MudPilot (no app/<version>/version.txt)")
        if v != version:
            raise ValueError(f"says version {v}, file name says {version}")
        return out
    try:
        init = zf.read("MudPilot/mudpilot/__init__.py").decode("utf-8")
    except KeyError:
        raise ValueError("no mudpilot/__init__.py")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    if not m or m.group(1) != version:
        raise ValueError(f"says version {m.group(1) if m else '?'}, file name says {version}")
    return out


def install(version, zpath, root=None) -> bool:
    """Copy the zip's files over the install. The current mudpilot\\ is kept in .mp-prev\\ for a roll-back."""
    root = root or ROOT
    if FROZEN:
        return _install_frozen(version, zpath, root)
    backed_up = False
    try:
        with zipfile.ZipFile(zpath) as zf:
            members = check_zip(zf, version)
            req_before = _read(os.path.join(root, "requirements.txt"))
            prev = os.path.join(root, ".mp-prev")
            shutil.rmtree(prev, ignore_errors=True)
            shutil.copytree(os.path.join(root, "mudpilot"), os.path.join(prev, "mudpilot"),
                            ignore=shutil.ignore_patterns("__pycache__"))
            backed_up = True
            for rel, zi in members:
                dest = os.path.join(root, *rel.split("/"))
                if zi.is_dir():
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(zi) as src, open(dest + ".new", "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.replace(dest + ".new", dest)
    except ValueError as ex:
        log(f"Not installing {os.path.basename(zpath)}: {ex}")
        _skip(version)                               # not one of ours: never again
        return False
    except (OSError, zipfile.BadZipFile) as ex:
        # still being copied in, or a file held open: try again next start — never skip a good version for good
        log(f"Not installing {os.path.basename(zpath)} this time: {ex} — will try again at the next start")
        if backed_up:
            _roll_back(root)                         # half the files new, half old: put the old mudpilot folder back
        return False
    log(f"Installed {version} from {zpath}")
    if _read(os.path.join(root, "requirements.txt")) != req_before:
        py = os.path.join(os.path.dirname(sys.executable), "python.exe")
        r = subprocess.run([py if os.path.exists(py) else sys.executable, "-m", "pip", "install", "--quiet", "-r",
                            os.path.join(root, "requirements.txt")], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log("Packages updated" if r.returncode == 0 else f"Package update failed: {r.stderr[-300:]}")
    return True


def _roll_back(root):
    """An install that failed part way: copy the kept mudpilot folder back, so we never start on a mix of versions."""
    prev = os.path.join(root, ".mp-prev", "mudpilot")
    try:
        shutil.copytree(prev, os.path.join(root, "mudpilot"), dirs_exist_ok=True)
        log("Put the previous version back")
    except OSError as ex:
        log(f"Couldn't put the previous version back: {ex}")


def _keep_mode(zi, path):
    """Linux: Python's zip reading drops the 'can run' bit — put back the one stored in the zip (the programs,
    the starter script, the libraries)."""
    if os.name == "nt":
        return
    mode = (zi.external_attr >> 16) & 0o777
    if mode:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _install_frozen(version, zpath, root) -> bool:
    """Unpack app/<version>/ beside the versions there (into a .part folder, renamed when complete); the top-level
    MudPilot.exe and guides are replaced if they can be (they're not in use: the starter exits straight away)."""
    dest = os.path.join(root, "app", version)
    part = dest + ".part"
    pre = f"app/{version}/"
    try:
        with zipfile.ZipFile(zpath) as zf:
            members = check_zip(zf, version)
            shutil.rmtree(part, ignore_errors=True)
            tops = []
            for rel, zi in members:
                if not rel.startswith(pre):
                    tops.append((rel, zi))
                    continue
                out = os.path.join(part, *rel[len(pre):].split("/"))
                if zi.is_dir():
                    os.makedirs(out, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with zf.open(zi) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                _keep_mode(zi, out)
            if os.path.isdir(dest):
                shutil.rmtree(dest)                  # (a half-installed copy from before; in use → OSError)
            os.replace(part, dest)
            for rel, zi in tops:
                if zi.is_dir():
                    continue
                out = os.path.join(root, *rel.split("/"))
                try:
                    with zf.open(zi) as src, open(out + ".new", "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    _keep_mode(zi, out + ".new")
                    os.replace(out + ".new", out)
                except OSError as ex:
                    log(f"Kept the old {rel} ({ex})")
    except (OSError, ValueError, zipfile.BadZipFile) as ex:
        shutil.rmtree(part, ignore_errors=True)
        log(f"Not installing {os.path.basename(zpath)}: {ex}")
        if isinstance(ex, ValueError):
            _skip(version)                           # not one of ours; a copy in progress gets another go next start
        return False
    log(f"Installed {version} from {zpath}")
    return True


def prune_apps(root=None):
    """Old compiled versions: keep the newest two and the one running; the rest go (one still open in another
    character stays till next time)."""
    keep = set(app_versions(root)[-2:]) | {running_version()}
    for v in app_versions(root):
        if v not in keep:
            shutil.rmtree(os.path.join(root or ROOT, "app", v), ignore_errors=True)


def roll_back(root=None) -> bool:
    root = root or ROOT
    if FROZEN:
        return len(app_versions(root)) > 1          # the crashed one is skipped from now on: the one before opens
    prev = os.path.join(root, ".mp-prev", "mudpilot")
    if not os.path.isdir(prev):
        return False
    shutil.copytree(prev, os.path.join(root, "mudpilot"), dirs_exist_ok=True)
    return True


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def wait_hold():
    h = os.path.join(CONTROL, "hold")
    t0 = time.time()
    if os.path.exists(h):
        log("Holding (settings being edited)")
    while os.path.exists(h):
        if time.time() - t0 > HOLD_MAX:
            log("Hold left on for an hour — opening MudPilot anyway")
            try:
                os.remove(h)
            except OSError:
                pass
            break
        time.sleep(2)


def run_mudpilot() -> int:
    for stale in ("restart.request",):
        try:
            os.remove(os.path.join(CONTROL, stale))
        except OSError:
            pass
    env = {**os.environ, "MUDPILOT_LAUNCHER": "1"}
    if DATA_NAME:
        env["MUDPILOT_DATA_DIR"] = DATA
    return subprocess.call([EXE, "-m", "mudpilot"], cwd=ROOT, env=env)


def _relaunch(*args):
    """Start a fresh launcher (on the code just installed) and let this one end."""
    extra = ["--data", DATA_NAME] if DATA_NAME else []
    exe = EXE
    if FROZEN and newest_app():
        exe = os.path.join(APPS, newest_app(), EXE_NAME)
    subprocess.Popen([exe, "-m", "mudpilot.launcher", *extra, "--relaunched", *args], cwd=ROOT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main(argv=()):
    os.chdir(ROOT)
    argv = list(argv)
    just = tuple(argv[argv.index("--installed") + 1:][:2]) if "--installed" in argv else None
    if "--data" in argv:
        use_data((argv[argv.index("--data") + 1:] or [""])[0])
    opened_by_hand = "--relaunched" not in argv
    if opened_by_hand and "--data" not in argv and len(character_folders()) > 1:
        # more than one character on this PC: ask which, every time you open it (one character: straight in)
        name = pick_folder()
        if name is None:
            return
        use_data(name)
    elif opened_by_hand and folder_in_use(DATA):
        if "--data" in argv:
            # that character's MudPilot is open already: a second one on the same folder is what went wrong
            log("Not opening a second MudPilot on this folder — it's already open")
            try:
                from tkinter import messagebox
                messagebox.showinfo("MudPilot", f"{os.path.basename(DATA)} is already open in another MudPilot.")
            except Exception:
                pass
            return
        name = pick_folder()
        if name is None:
            return
        use_data(name)
    try:
        _run(just)
    finally:
        unmark_in_use()


def _run(just):
    if folder_in_use(DATA) and "--relaunched" not in sys.argv:
        # last guard: two MudPilots on one folder log in as the same character and knock each other off
        log("Not opening a second MudPilot on this folder — it's already open")
        return
    mark_in_use()
    log(f"Launcher started ({installed_version()}{', data-' + DATA_NAME if DATA_NAME else ''})" + (f" after installing {just[0]}" if just else ""))
    if FROZEN:
        prune_apps()
    while True:
        if not just:
            new = find_newer()
            if new:
                old = running_version() if FROZEN else installed_version()
                if install(*new):
                    log("Reopening the launcher on the new version")
                    _relaunch("--installed", new[0], old)
                    return
            if FROZEN and newest_app() and vtuple(newest_app()) > vtuple(running_version()):
                # another character on this install unpacked a newer one: open that
                log(f"Reopening the launcher on {newest_app()} (installed by another character)")
                _relaunch("--installed", newest_app(), running_version())
                return
        wait_hold()
        t0 = time.time()
        rc = run_mudpilot()
        ran = time.time() - t0
        if rc == RESTART_EXIT:
            log(f"MudPilot closed for a restart (ran {ran / 60:.0f} min)")
            just = None
            continue
        if rc != 0 and just and len(just) == 2 and ran < CRASH_SECS and roll_back():
            _skip(just[0])
            log(f"{just[0]} crashed within {ran:.0f} s (exit {rc}) — rolled back to {just[1]}, skipping {just[0]}")
            _relaunch()
            return
        log(f"MudPilot closed (exit {rc}, ran {ran / 60:.0f} min) — launcher done")
        return


if __name__ == "__main__":
    main(sys.argv[1:])
