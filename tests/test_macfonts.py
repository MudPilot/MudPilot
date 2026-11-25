"""0.8.227.1: on a Mac, Consolas & co. (not installed there) are drawn in Menlo so the game's columns line up
(Spuzzy, 2026-11-25: character creation and 'who' misaligned in the system font). Simulated: platform = darwin,
and this machine's font list without Consolas."""
import os, sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import macfonts as m
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

check("string forms", m.swap_font("x") == "x")              # nothing swapped before install
real_platform, sys.platform = sys.platform, "darwin"
root = tk.Tk(); root.withdraw()
real = tkfont.families
tkfont.families = lambda r=None: [f for f in real(root) if f not in ("Consolas", "Lucida Console")] + ["Menlo"]
m.install(root)
sys.platform = real_platform
check("Consolas missing → Menlo", m._swap.get("consolas") == "Menlo")
check("an installed font is never swapped", "courier new" not in m._swap)
t = tk.Text(root, font=("Consolas", 12))
check("widget created with Consolas", t.cget("font").startswith("Menlo"))
t.configure(font=("Consolas", 10, "bold"))
check("configure keeps size and style", t.cget("font") == "Menlo 10 bold")
t.tag_configure("x", font="Consolas 9")
check("text tag, font as a string", "Menlo" in t.tag_cget("x", "font"))
t.tag_configure("y", font="Lucida Console 9")
check("two-word name without braces", "Menlo" in t.tag_cget("y", "font"))
check("sans fonts left alone", "Segoe UI" in tk.Label(root, font=("Segoe UI", 10)).cget("font"))
check("tkinter.font.Font", tkfont.Font(root=root, family="Consolas", size=11).cget("family") == "Menlo")
c = tk.Canvas(root)
check("canvas text", c.itemcget(c.create_text(1, 1, text="x", font=("Consolas", 9)), "font").startswith("Menlo"))
check("ttk widget", str(ttk.Entry(root, font=("Consolas", 11)).cget("font")).startswith("Menlo"))
root.destroy()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
