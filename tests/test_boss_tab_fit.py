"""Revolution's screen (Dan, 2026-11-03): the Bosses tab showed the list and one row of buttons — the rest of the
buttons and the 'Track a boss' box were pushed off the bottom/side. Built small, everything still has to be on show."""
import os, sys, tkinter as tk
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, app as A
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
root = tk.Tk()
o = A.App.__new__(A.App)
o.root, o.s = root, s
o._vars = {}
for size in ((540, 430), (430, 380), (900, 700)):
    host = ttk.Frame(root, width=size[0], height=size[1])
    host.pack_propagate(False)
    host.place(x=0, y=0, width=size[0], height=size[1])
    root.geometry(f"{size[0]}x{size[1]}")
    tab = o._boss_tab(host)
    tab.pack(fill="both", expand=True)
    root.update()
    def visible(w):
        x, y = w.winfo_rootx() - host.winfo_rootx(), w.winfo_rooty() - host.winfo_rooty()
        return w.winfo_ismapped() and x >= 0 and y >= 0 and x + w.winfo_width() <= size[0] + 1 \
            and y + w.winfo_height() <= size[1] + 1
    btns = []
    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, (ttk.Button, ttk.Entry, ttk.Checkbutton)):
                btns.append(c)
            walk(c)
    walk(tab)
    names = {(b.cget("text") if isinstance(b, (ttk.Button, ttk.Checkbutton)) else "entry") for b in btns}
    hidden = [(b.cget("text") if isinstance(b, (ttk.Button, ttk.Checkbutton)) else "entry") for b in btns if not visible(b)]
    check(f"{size[0]}x{size[1]}: every button and the Track box on show ({len(btns)}; hidden: {hidden})",
          not hidden and {"Hunt now", "Add", "entry", "Remove"} <= names)
    host.destroy()
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
