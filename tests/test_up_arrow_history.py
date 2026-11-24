"""0.8.226 (Dan: "the up arrow just makes me run north"): with the command line empty, the Up arrow should bring back
the last command typed (a spell in a boss fight: Up, Enter to retry), as in MegaMUD. The macro keys took it as the
number pad's 8 — Windows Tk flags the arrow block with state 0x40000, and MudPilot looked at 0x20000 (Alt).
Real keypresses (Windows only): the arrow Up recalls; the number pad's 8 with NumLock off still walks north."""
import os, sys, types, ctypes
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
if not sys.platform.startswith("win"):
    print("ALL PASS (Windows only)"); sys.exit(0)
import tkinter as tk
from mudpilot.app import App
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

root = tk.Tk()
ran = []
a = object.__new__(App)
a.root = root
a.entry = tk.Entry(root)
a.entry.pack()
a.s = types.SimpleNamespace(settings=types.SimpleNamespace(keypad_macros=True), macros={"Keypad 8": "n^M"})
a.run_macro = lambda t: ran.append(t)
a.history, a.hist_i = ["cast mana flux", "c blaze"], 2
a.entry.bindtags(("MPMacro",) + a.entry.bindtags())
a.entry.bind_class("MPMacro", "<KeyPress>", a._macro_key)
a.entry.bind("<Up>", lambda e: a.hist(-1))
a.entry.bind("<Down>", lambda e: a.hist(1))
root.lift(); root.attributes("-topmost", True); root.update()
a.entry.focus_force(); root.update()
u = ctypes.windll.user32


def press(vk, ext):
    f = 1 if ext else 0
    u.keybd_event(vk, 0, f, 0)
    u.keybd_event(vk, 0, f | 2, 0)
    for _ in range(20):
        root.update()
        root.after(10); root.update_idletasks()


press(0x26, True)                    # the arrow Up
check(f"Up arrow brings back the last command ({a.entry.get()!r}, macros {ran})", a.entry.get() == "c blaze" and not ran)
press(0x26, True)
check(f"…and the one before ({a.entry.get()!r})", a.entry.get() == "cast mana flux")
press(0x28, True)                    # the arrow Down
check(f"Down goes forward again ({a.entry.get()!r})", a.entry.get() == "c blaze")
a.entry.delete(0, "end"); a._held_keys = {}
press(0x26, False)                   # the number pad's 8, NumLock off (no extended flag)
check(f"the number pad's 8 still walks north ({ran})", ran == ["n^M"])
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
