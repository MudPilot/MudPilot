"""Windows taskbar identity: so the taskbar shows the MudPilot guy, not Python's icon.

Windows 11 groups taskbar buttons by "AppUserModelID" and takes the icon from a Start-menu
shortcut carrying the same ID — the window's own icon isn't enough. So MudPilot:
  1. sets its process ID (before the first window, in app.main),
  2. makes sure a Start-menu shortcut "MudPilot" exists (target pythonw -m mudpilot, our icon),
  3. stamps the ID on that shortcut and on the desktop / pinned-taskbar MudPilot shortcuts.
Pure ctypes (no extra packages). Runs once per ID in the background; any failure is ignored —
it only ever touches shortcuts named MudPilot.lnk.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

APP_ID = "MudPilot.Client.2"      # new ID: Windows cached the old "MudPilot.App" with Python's icon


def set_process_id():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _stamp(lnk: str) -> bool:
    """Write System.AppUserModel.ID = APP_ID into a .lnk (IPropertyStore via raw COM)."""
    import ctypes
    from ctypes import POINTER, Structure, WINFUNCTYPE, byref, c_ubyte, c_ulong, c_ushort, c_void_p, c_wchar_p

    class GUID(Structure):
        _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8)]

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PROPVARIANT(Structure):          # 24 bytes on x64: vt + 3 reserved words + 16-byte union
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                    ("pwsz", c_wchar_p), ("pad", c_void_p)]

    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32

    def guid(s):
        g = GUID()
        ole32.CLSIDFromString(c_wchar_p(s), byref(g))
        return g
    iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")                 # IID_IPropertyStore
    key = PROPERTYKEY(guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)  # PKEY_AppUserModel_ID
    ps = c_void_p()
    hr = shell32.SHGetPropertyStoreFromParsingName(c_wchar_p(lnk), None, 2, byref(iid), byref(ps))  # GPS_READWRITE
    if hr != 0 or not ps:
        return False
    vt = ctypes.cast(ps, POINTER(POINTER(c_void_p)))[0]
    release = WINFUNCTYPE(c_ulong, c_void_p)(vt[2])
    set_value = WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(vt[6])
    commit = WINFUNCTYPE(ctypes.c_long, c_void_p)(vt[7])
    try:
        pv = PROPVARIANT(31, 0, 0, 0, APP_ID, None)                     # VT_LPWSTR
        if set_value(ps, byref(key), byref(pv)) != 0:
            return False
        return commit(ps) == 0
    finally:
        release(ps)


def _target():
    """(exe, arguments, install folder, icon) a MudPilot shortcut opens: pythonw -m mudpilot.launcher, or in the
    compiled build the MudPilot.exe at the top of the install (it opens the newest version in app\\)."""
    from .config import APP_DIR, FROZEN
    if FROZEN:
        exe = os.path.join(APP_DIR, "MudPilot.exe")
        return exe, "", APP_DIR, exe + ",0"
    here = os.path.dirname(os.path.abspath(__file__))
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return exe, "-m mudpilot.launcher", os.path.dirname(here), os.path.join(here, "assets", "mudpilot.ico")


def _make_shortcut(lnk, target, args, workdir, icon):
    """Create a .lnk with Windows' own scripting host (hidden PowerShell, no window flashes)."""
    q = lambda s: s.replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
          f"$s.TargetPath='{q(target)}';$s.Arguments='{q(args)}';$s.WorkingDirectory='{q(workdir)}';"
          f"$s.IconLocation='{q(icon)}';$s.Description='MudPilot';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=0x08000000, timeout=30, capture_output=True)   # CREATE_NO_WINDOW


def ensure_launcher_shortcuts(data_dir: str, log=lambda m: None):
    """Point the MudPilot.lnk shortcuts at the launcher (-m mudpilot.launcher), once, so the control folder can
    restart and update MudPilot. Only shortcuts named MudPilot.lnk that already exist are touched."""
    if os.name != "nt":
        return
    if os.environ.get("MUDPILOT_DATA_DIR"):
        return          # a second character set (--data PVE): your MudPilot shortcuts stay as they are
    marker = os.path.join(data_dir, ".launcher_shortcuts")
    if os.path.exists(marker):
        return

    def work():
        try:
            ole32 = __import__("ctypes").windll.ole32
            ole32.CoInitializeEx(None, 2)
            exe, args, root, icon = _target()
            appdata, home = os.environ.get("APPDATA", ""), os.path.expanduser("~")
            cands = [os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "MudPilot.lnk"),
                     os.path.join(home, "Desktop", "MudPilot.lnk"),
                     os.path.join(home, "OneDrive", "Desktop", "MudPilot.lnk"),
                     os.path.join(appdata, "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned",
                                  "TaskBar", "MudPilot.lnk")]
            done = []
            for p in cands:
                if os.path.exists(p):
                    _make_shortcut(p, exe, args, root, icon)
                    _stamp(p)
                    done.append(p)
            os.makedirs(data_dir, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("\n".join(done))
            if done:
                log(f"MudPilot shortcuts now open it through the launcher ({len(done)} updated)")
        except Exception as ex:                     # never matters enough to bother you
            log(f"Launcher shortcut setup skipped: {ex}")
    threading.Thread(target=work, daemon=True).start()


def ensure_shortcuts(data_dir: str, log=lambda m: None):
    """Start-menu shortcut + ID stamps, once per APP_ID (marker in data\\)."""
    if os.name != "nt":
        return
    if os.environ.get("MUDPILOT_DATA_DIR"):
        return          # a second character set (--data PVE): your MudPilot shortcuts stay as they are
    marker = os.path.join(data_dir, ".taskbar_id")
    try:
        with open(marker, encoding="utf-8") as f:
            if f.read().strip() == APP_ID:
                return
    except OSError:
        pass

    def work():
        try:
            ole32 = __import__("ctypes").windll.ole32
            ole32.CoInitializeEx(None, 2)
            exe, args, root, icon = _target()
            appdata = os.environ.get("APPDATA", "")
            start = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "MudPilot.lnk")
            if appdata and not os.path.exists(start):
                _make_shortcut(start, exe, args, root, icon)
            home = os.path.expanduser("~")
            cands = [start,
                     os.path.join(home, "Desktop", "MudPilot.lnk"),
                     os.path.join(home, "OneDrive", "Desktop", "MudPilot.lnk"),
                     os.path.join(appdata, "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned",
                                  "TaskBar", "MudPilot.lnk")]
            done = [p for p in cands if os.path.exists(p) and _stamp(p)]
            if done:
                os.makedirs(data_dir, exist_ok=True)
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(APP_ID)
                log("Taskbar icon set up (Start-menu shortcut) — shows the MudPilot guy from the next start")
        except Exception as ex:                     # never matters enough to bother you
            log(f"Taskbar icon setup skipped: {ex}")
    threading.Thread(target=work, daemon=True).start()
