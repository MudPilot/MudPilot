# Mac diagnosis (used by macos-diagnose.yml, "newchar" job): opens MudPilot from source and does what a player does
# to make a new character, logging each step and where the main thread is every few seconds, so a hang shows where.
#   python -I .github/mac_newchar_probe.py app      -> Character -> New character... inside MudPilot
#   python -I .github/mac_newchar_probe.py picker   -> the launcher's "Which character?" -> New character...
import os, sys, threading, time, traceback

sys.path.insert(0, os.getcwd())
OUT = os.path.join(os.getcwd(), "out")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()
NL = chr(10)


def log(msg):
    with open(os.path.join(OUT, "probe.log"), "a") as fh:
        fh.write(f"{time.time() - T0:7.2f} {msg}" + NL)


def watch():
    while True:
        time.sleep(5)
        fr = sys._current_frames().get(threading.main_thread().ident)
        if fr is not None:
            with open(os.path.join(OUT, "stacks.txt"), "a") as fh:
                fh.write(f"=== {time.time() - T0:.0f}s" + NL + "".join(traceback.format_stack(fr)[-14:]) + NL)


threading.Thread(target=watch, daemon=True).start()

import tkinter as tk
from tkinter import simpledialog

_orig_ask = simpledialog.askstring


def ask(title, prompt, **kw):
    """The real question box, typed into and OK'd 3 s after it opens (as a player would)."""
    parent = kw.get("parent") or tk._default_root
    log(f"askstring({title!r}) called")

    def fill():
        for w in parent.winfo_children():
            if isinstance(w, simpledialog._QueryString):
                log("question box found: typing Testchar, pressing OK")
                w.entry.delete(0, "end")
                w.entry.insert(0, "Testchar")
                w.ok()
                log("OK pressed")
                return
        log("question box not found yet; trying again")
        parent.after(2000, fill)

    parent.after(3000, fill)
    v = _orig_ask(title, prompt, **kw)
    log(f"askstring returned {v!r}")
    return v


simpledialog.askstring = ask

mode = sys.argv[1] if len(sys.argv) > 1 else "app"
log(f"mode {mode}, python {sys.version.split()[0]}, tk {tk.TkVersion}")

if mode == "picker":
    from mudpilot import launcher
    root = os.path.join(os.getcwd(), "probe-root")
    for d in ("data", "data-Other"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    orig_tk = tk.Tk

    class Tk(orig_tk):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            log("picker window made; pressing New character... in 3 s")

            def press():
                for w in self.winfo_children():
                    for b in w.winfo_children():
                        try:
                            if b.cget("text") == "New character…":
                                log("pressing New character…")
                                b.invoke()
                                log("New character… returned")
                                return
                        except tk.TclError:
                            pass
                log("button not found")
            self.after(3000, press)

    tk.Tk = Tk
    got = launcher.pick_folder(root)
    log(f"pick_folder returned {got!r}")
    log("DONE")
else:
    from mudpilot import app as A
    A.App.ask_board_first_run = lambda self: log("(board question skipped)")
    orig_init = A.App.__init__

    def init(self, root):
        orig_init(self, root)
        log("App made; New character... in 20 s")

        def go():
            log("calling new_profile()")
            try:
                self.new_profile()
                log("new_profile() returned")
            except Exception:
                log("new_profile() raised" + NL + traceback.format_exc())
            root.after(5000, lambda: log("main loop still running 5 s after (DONE)"))
        root.after(20000, go)

    A.App.__init__ = init
    sys.argv = ["mudpilot"]
    A.main()
