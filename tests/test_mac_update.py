"""0.8.224.2: a Mac install looks for the Mac zip, not the Windows one."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mudpilot.updater as u
import mudpilot.launcher as l
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
u.LINUX, u.MAC = False, True
u.mac_arch = lambda: "arm64"
check("Apple Silicon: -mac-arm64.zip first, then -mac.zip", u._asset_names("0.8.225") == ["MudPilot-0.8.225-mac-arm64.zip", "MudPilot-0.8.225-mac.zip"])
u.MAC = False
check("Windows unchanged", u._asset_names("0.8.225") == ["MudPilot-0.8.225.zip"])
u.LINUX = True
check("Linux unchanged", u._asset_names("0.8.225") == ["MudPilot-0.8.225-linux.zip"])
rx = l._mac_zip_re()
check("launcher (Mac): its own zip and the both-kinds one", re.match(rx, "MudPilot-0.8.225-mac.zip") and
      sum(bool(re.match(rx, f"MudPilot-0.8.225-mac-{a}.zip")) for a in ("arm64", "x64")) == 1)
check("…never the Windows zip", not re.match(rx, "MudPilot-0.8.225.zip"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
