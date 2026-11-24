# Mac diagnosis (macos-diagnose.yml, "dialog" job): does a name box take real typing and an OK click on a Mac?
#   python -I .github/mac_dialog_probe.py bare    -> tkinter's simpledialog.askstring (what MudPilot uses)
#   python -I .github/mac_dialog_probe.py custom  -> a plain Toplevel box (no Mac "moveableModal" style)
#   ... menu / menudefer -> the bare box from a menu-bar item, run straight away / once the menu has closed
# Writes out/coords.txt (entry x y, OK x y in screen points) once the box is up; the workflow clicks and types there.
import os, sys, time
import tkinter as tk
from tkinter import simpledialog, ttk

OUT = os.path.join(os.getcwd(), "out")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()


def log(msg):
    with open(os.path.join(OUT, "probe.log"), "a") as fh:
        fh.write(f"{time.time() - T0:7.2f} {msg}" + chr(10))


def centre(w):
    return w.winfo_rootx() + w.winfo_width() // 2, w.winfo_rooty() + w.winfo_height() // 2


def custom_ask(parent, title, prompt):
    d = tk.Toplevel(parent)
    d.title(title)
    d.transient(parent)
    d.resizable(False, False)
    fr = ttk.Frame(d, padding=12)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text=prompt).pack(anchor="w")
    var = tk.StringVar()
    ent = ttk.Entry(fr, textvariable=var, width=30)
    ent.pack(fill="x", pady=8)
    out = {"v": None}

    def ok(_e=None):
        out["v"] = var.get()
        d.destroy()
    row = ttk.Frame(fr)
    row.pack(fill="x")
    okb = ttk.Button(row, text="OK", command=ok)
    okb.pack(side="left")
    ttk.Button(row, text="Cancel", command=d.destroy).pack(side="left", padx=8)
    d.bind("<Return>", ok)
    d.bind("<Escape>", lambda e: d.destroy())
    d.geometry(f"+{parent.winfo_rootx() + 80}+{parent.winfo_rooty() + 80}")
    d.lift()
    ent.focus_force()
    d.after(1500, lambda: report(ent, okb))
    try:
        d.grab_set()
    except tk.TclError:
        pass
    d.wait_window()
    return out["v"]


def report(ent, okb):
    ex, ey = centre(ent)
    ox, oy = centre(okb)
    with open(os.path.join(OUT, "coords.txt"), "w") as fh:
        fh.write(f"{ex} {ey} {ox} {oy}")
    log(f"box up: entry at {ex},{ey}  OK at {ox},{oy}")


def find_bare():
    for w in root.winfo_children():
        if isinstance(w, simpledialog._QueryString):
            okb = None
            stack = list(w.winfo_children())
            while stack:
                c = stack.pop()
                stack.extend(c.winfo_children())
                try:
                    if c.cget("text") == "OK":
                        okb = c
                except tk.TclError:
                    pass
            if okb is not None:
                report(w.entry, okb)
                return
    root.after(500, find_bare)


mode = sys.argv[1] if len(sys.argv) > 1 else "bare"
root = tk.Tk()
root.title(f"probe {mode}")
root.geometry("700x450+150+150")
tk.Entry(root, width=40).pack(pady=20)


def go():
    log(f"opening the {mode} box (tk {root.tk.call('info', 'patchlevel')})")
    if mode != "custom":
        root.after(1500, find_bare)
        v = simpledialog.askstring("New profile", "Character name:", parent=root)
    else:
        v = custom_ask(root, "New profile", "Character name:")
    log(f"RESULT {v!r}")
    root.after(1000, root.destroy)


if mode.startswith("menu"):
    # opened from the Mac menu bar, as Character -> New character... is ("menudefer": run once the menu has closed)
    bar = tk.Menu(root)
    cm = tk.Menu(bar, tearoff=0)
    cm.add_command(label="New character…",
                   command=(lambda: root.after(1, go)) if mode == "menudefer" else go)
    bar.add_cascade(label="Character", menu=cm)
    root.config(menu=bar)
    log("menu ready")
else:
    root.after(2000, go)
root.mainloop()
