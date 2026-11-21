"""Loading screen: the moonlit keep, a gold progress bar and what's loading, while the main window builds
behind it — then the window opens fully drawn (maximised the first time)."""
from __future__ import annotations

import os
import tkinter as tk

from . import config

BAR_BG, BAR_FG, BAR_EDGE = "#1a1410", "#e8c470", "#6b5530"
ART_SIZE = (960, 541)                 # assets/splash.png (0.8.190: the MudPilot keep and the miserable book)
BAR_IN_ART = (277, 472, 674, 495)     # the gold trough painted into it (x0, y0, x1, y1)
TROUGH = "#070504"


class Splash:
    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(background="#05060a")
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "splash.png")
        try:
            self.img = tk.PhotoImage(file=here)
            w, h = self.img.width(), self.img.height()
        except tk.TclError:
            self.img, w, h = None, 640, 360
        # the art has its own progress bar painted in (the gold trough): MudPilot uncovers it as things load
        self.painted = BAR_IN_ART if (self.img and (w, h) == ART_SIZE) else None
        extra = 0 if self.painted else 46
        self.c = tk.Canvas(self.win, width=w, height=h + extra, highlightthickness=0, background="#05060a")
        self.c.pack()
        if self.img:
            self.c.create_image(0, 0, image=self.img, anchor="nw")
        if self.painted:
            x0, y0, x1, y1 = self.painted
            self.bar = (x0, x1, y0)
            self.cover = self.c.create_rectangle(x0, y0, x1, y1, fill=TROUGH, outline="")
            self.fill = None
            self.text = self.c.create_text((x0 + x1) // 2, y1 + 18, anchor="n", text="Starting…", fill="#c8b896",
                                           font=("Georgia", 10, "italic"))
        else:
            x0, x1, y = 40, w - 40, h + 16
            self.bar = (x0, x1, y)
            self.c.create_rectangle(x0, y, x1, y + 12, fill=BAR_BG, outline=BAR_EDGE)
            self.fill = self.c.create_rectangle(x0 + 1, y + 1, x0 + 1, y + 11, fill=BAR_FG, outline="")
            self.text = self.c.create_text(x0, y - 4, anchor="sw", text="Starting…", fill="#c8b896",
                                           font=("Georgia", 10, "italic"))
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h + extra}+{max(0, (sw - w) // 2)}+{max(0, (sh - h - extra) // 3)}")
        self.win.lift()
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.win.update()

    def step(self, pct: float, msg: str = ""):
        try:
            x0, x1, y = self.bar
            pct = max(0.0, min(100.0, pct))
            if self.painted:
                _x0, y0, _x1, y1 = self.painted
                self.c.coords(self.cover, x0 + (x1 - x0) * pct / 100, y0, x1, y1)
            else:
                self.c.coords(self.fill, x0 + 1, y + 1, x0 + 1 + (x1 - x0 - 2) * pct / 100, y + 11)
            if msg:
                self.c.itemconfigure(self.text, text=msg)
            self.win.update()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def progress(pct, msg=""):
    """Anything starting up can report here; nothing happens when there's no loading screen."""
    sp = getattr(config, "_splash", None)
    if sp is not None:
        sp.step(pct, msg)
