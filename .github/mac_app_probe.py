# Mac diagnosis (macos-diagnose.yml, "appbox" job): MudPilot from source, New character... opened, every key and
# click Tk gets is logged with the widget it went to, and the box's entry / OK positions are written to
# out/coords.txt for the workflow to click and type at. MP_OFF (comma list) switches pieces of MudPilot off to
# find which one keeps the box from taking input: uilog, keys, loop, hangwatch, board.
import os, sys, time, traceback

sys.path.insert(0, os.getcwd())
OUT = os.path.join(os.getcwd(), "out")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()
OFF = {x for x in os.environ.get("MP_OFF", "").split(",") if x}


def log(msg):
    with open(os.path.join(OUT, "probe.log"), "a") as fh:
        fh.write(f"{time.time() - T0:7.2f} {msg}" + chr(10))


import tkinter as tk
from tkinter import simpledialog
from mudpilot import app as A
from mudpilot import uilog

log(f"MP_OFF={sorted(OFF)}")
if "uilog" in OFF:
    uilog.install = lambda app: None
if "keys" in OFF:
    A.App._stray_key = lambda self, e: None
    A.App._macro_key = lambda self, e: None
    A.App._key_up = lambda self, e: None
if "loop" in OFF:
    A.App._loop = lambda self: None
if "hangwatch" in OFF:
    import mudpilot.hangwatch as H
    H.HangWatch.__init__ = lambda self, *a, **k: None
STEPS = {x for x in os.environ.get("MP_STEPS", "").split(",") if x}   # board, menu, main
if "board" not in STEPS:
    A.App.ask_board_first_run = lambda self: log("(board question skipped)")
else:
    _orig_board = A.App.ask_board_first_run

    def board(self):
        _orig_board(self)

        def where():
            for w in self.root.winfo_children():
                if isinstance(w, tk.Toplevel) and "board" in w.title().lower():
                    stack = list(w.winfo_children())
                    while stack:
                        c = stack.pop()
                        stack.extend(c.winfo_children())
                        try:
                            if c.cget("text") == "Paradigm":
                                x, y = centre(c)
                                log(f"board question up: Paradigm at {x},{y}")
                                with open(os.path.join(OUT, "board.txt"), "w") as fh:
                                    fh.write(f"{x} {y}" + chr(10))
                                return
                        except tk.TclError:
                            pass
            self.root.after(500, where)
        self.root.after(1000, where)
    A.App.ask_board_first_run = board


def centre(w):
    return w.winfo_rootx() + w.winfo_width() // 2, w.winfo_rooty() + w.winfo_height() // 2


orig_init = A.App.__init__


def init(self, root):
    orig_init(self, root)

    def ev(kind):
        def f(e):
            try:
                log(f"{kind} {getattr(e, 'keysym', '') or getattr(e, 'num', '')} -> {e.widget}")
            except Exception:
                pass
        return f
    for seq, kind in (("<KeyPress>", "key"), ("<ButtonPress>", "press"), ("<ButtonRelease>", "release")):
        root.bind_all(seq, ev(kind), add="+")

    def find():
        for w in root.winfo_children():
            if isinstance(w, simpledialog._QueryString):
                okb, stack = None, list(w.winfo_children())
                while stack:
                    c = stack.pop()
                    stack.extend(c.winfo_children())
                    try:
                        if c.cget("text") == "OK":
                            okb = c
                    except tk.TclError:
                        pass
                if okb is not None:
                    ex, ey = centre(w.entry)
                    ox, oy = centre(okb)
                    log(f"box up: entry {ex},{ey} OK {ox},{oy}; grab={root.grab_current()} focus={root.focus_get()}")
                    with open(os.path.join(OUT, "coords.txt"), "w") as fh:
                        fh.write(f"{ex} {ey} {ox} {oy}" + chr(10))
                    return
        root.after(500, find)

    def go():
        log("new_profile()")
        root.after(1500, find)
        try:
            self.new_profile()
            log("new_profile() returned; profile now " + str(self.s.settings.profile))
        except Exception:
            log("raised " + traceback.format_exc())
        log("DONE")
    mx, my = (0, 0)
    try:
        root.update_idletasks()
        mx, my = centre(self.entry)
    except Exception:
        pass
    with open(os.path.join(OUT, "ready.txt"), "w") as fh:
        fh.write(f"{mx} {my}" + chr(10))
    log(f"App made; command line at {mx},{my}; steps {sorted(STEPS)}")
    if "menu" in STEPS:
        orig_np = self.new_profile

        def np_(*a, **k):
            log("new_profile() from the menu")
            root.after(1500, find)
            v = orig_np(*a, **k)
            log("new_profile() returned; profile now " + str(self.s.settings.profile))
            log("DONE")
            return v
        self.new_profile = np_
        # the menu item was made with the old bound method: re-point it
        for m in (root.nametowidget(root["menu"]),):
            for i in range(m.index("end") + 1):
                try:
                    sub = root.nametowidget(m.entrycget(i, "menu"))
                except Exception:
                    continue
                for j in range((sub.index("end") or 0) + 1):
                    try:
                        if sub.entrycget(j, "label") == "New character…":
                            sub.entryconfigure(j, command=np_)
                            log("menu item re-pointed")
                    except tk.TclError:
                        pass
    else:
        root.after(15000, go)


A.App.__init__ = init
sys.argv = ["mudpilot"]
A.main()
