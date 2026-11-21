"""Dan, 2026-11-01: walk with the number pad from the Map window (to record a loop there) — it only worked with the
main window in front. The number pad walks from any MudPilot window, but never while you type in a box."""
import os, sys, types
import tkinter as tk
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot.app import App
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


root = tk.Tk(); root.withdraw()
ran = []
stub = types.SimpleNamespace(root=root, entry=ttk.Entry(root),
                             s=types.SimpleNamespace(settings=types.SimpleNamespace(keypad_macros=True),
                                                     macros={"Keypad 8": "n^M", "F2": "rest^M"}),
                             run_macro=lambda t: ran.append(t))
mapwin = tk.Toplevel(root); canvas = tk.Canvas(mapwin); box = ttk.Entry(mapwin)


def press(widget, keysym, keycode):
    e = types.SimpleNamespace(widget=widget, keysym=keysym, keycode=keycode, state=0x20000 if keysym == "F2" else 0)
    return App._macro_key(stub, e)


ran.clear(); press(canvas, "KP_8", 104)
check(f"number pad 8 on the Map window walks north ({ran})", ran == ["n^M"])
ran.clear(); stub._held_keys = {}; press(box, "KP_8", 104)
check("…but not while typing in its search box", not ran)
ran.clear(); press(canvas, "F2", 113)
check("F-key macros stay with the main window", not ran)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
