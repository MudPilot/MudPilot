"""Dan, 2026-11-13: Miserable PVE's window stopped at 07:59 (Tk itself waiting, none of MudPilot's code running) and the
character stood in a crab fight until it died; nothing came back until he clicked the window 2 h 45 min later. Now the
freeze watcher gets a stuck window going again: in the game, after 15 s it cancels any menu / move on the window's
windows; still stuck, it writes the resume note and closes with the launcher's restart code, so MudPilot reopens,
logs back in and carries on."""
import os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "mudpilot_test_hang")
os.environ["MUDPILOT_LAUNCHER"] = "1"
import tkinter as tk
from mudpilot import hangwatch, control
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

exits, resumes = [], []
class Tel: connected = True
class Ctl:
    def write_resume(self): resumes.append(time.time())
class S: telnet = Tel(); control = Ctl()

def fake_exit(code):
    exits.append(code)
    raise SystemExit                       # (ends the watcher thread instead of the test)
hangwatch.os._exit = fake_exit
hangwatch.STALL, hangwatch.CANCEL_AFTER, hangwatch.RECOVER_AFTER, hangwatch.RECOVER_BUSY = 1.0, 1.5, 3.0, 3.0

root = tk.Tk(); root.geometry("200x100+40+40")
hw = hangwatch.HangWatch(root, lambda m: None, session=S())
cancels = []
real_cancel = hw._cancel_modes
hw._cancel_modes = lambda: (cancels.append(time.time()), real_cancel())[1]

def freeze():
    time.sleep(6)                          # the window's thread stuck (MudPilot code on its stack: the 'busy' limit)
    root.after(0, root.destroy)
root.after(1200, freeze)
root.mainloop()
check(f"stuck in the game: modes cancelled first ({len(cancels)})", len(cancels) >= 1)
check(f"still stuck: resume note written ({len(resumes)})", len(resumes) == 1)
check(f"…and closed for the launcher with the restart code ({exits})", exits == [control.RESTART_EXIT])
check("the cancel came before the restart", cancels and resumes and cancels[0] < resumes[0])

# not in the game: nothing drastic
exits.clear(); resumes.clear()
S.telnet.connected = False
root = tk.Tk(); root.geometry("200x100+40+40")
hw = hangwatch.HangWatch(root, lambda m: None, session=S())
root.after(1200, freeze)
root.mainloop()
check(f"offline: no restart ({exits})", not exits and not resumes)

# not opened by the launcher: nobody would reopen it, so no restart
S.telnet.connected = True
os.environ["MUDPILOT_LAUNCHER"] = "0"
root = tk.Tk(); root.geometry("200x100+40+40")
hw = hangwatch.HangWatch(root, lambda m: None, session=S())
root.after(1200, freeze)
root.mainloop()
check(f"no launcher: no restart ({exits})", not exits)

# the 'Tk waiting' test reads the window thread's stack
root = tk.Tk()
hw = hangwatch.HangWatch(root, lambda m: None, session=S())
seen = []
threading.Thread(target=lambda: (time.sleep(0.8), seen.append(hw._tk_waiting()), root.after(0, root.destroy)),
                 daemon=True).start()
root.mainloop()
check(f"idle in Tk's loop counts as 'Tk waiting' ({seen})", seen == [True])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
