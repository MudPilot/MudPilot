"""Step-by-step guides with on-screen highlights (Help → Step-by-step guides, 0.8.201).

Dan: "I do like the step by step guides with highlights on screen also" (MudPlay has them). A guide is a list of
steps; each step shows a small floating panel ("Step 2 of 5") with Back / Next / Close and draws a flashing border
around the real widget to click, opening the right Settings / Game Data tab first when needed.

Everything here is data-driven — add a guide by adding a dict to GUIDES. A step:
  text    what to do (plain text)
  open    optional, done when the step is shown:
            {"settings": "Loot"}       Settings window on that tab
            {"game_data": "Items"}     Game Data window on that tab
            {"main_tab": "Paths"}      the main window's right-hand tab
  target  optional, the widget to highlight:
            {"attr": "btn_connect"}             an App attribute (dotted path ok); "key" picks from a dict
            {"text": "Send test"}               a widget whose text contains this ("exact": True = whole text)
            {"tab": "Loot"}                     a notebook tab by its name
          plus "window": "main" (default) | "settings" | a pop-out window's name ("Game Data").
Lookups fail soft: a widget that can't be found just means no highlight — the step text still shows.
Nothing here grabs the mouse or waits: the game and the bot carry on underneath."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

GUIDES = [
    {"id": "first_run", "title": "First run: board, connect and log on", "steps": [
        {"text": "Each BBS has its own board (its MME map data, paths and boss timers). Pick yours here — "
                 "\"Main\" is the first one. A new BBS? Import its MME data under a new board name.",
         "target": {"attr": "board_box"}},
        {"text": "Load the map: File menu → Import MME database (.mdb)… and pick your board's MME data file "
                 "(e.g. data-v1.11p.mdb). Takes a few seconds; do it again whenever the board's data changes."},
        {"text": "Settings → BBS: the BBS host (no telnet://), port (usually 23) and your User-ID. "
                 "The password is asked for when you connect and kept in Windows Credential Manager.",
         "open": {"settings": "BBS"}, "target": {"tab": "BBS", "window": "settings"}},
        {"text": "Logon steps: what to type when the BBS shows a menu. On Paradigm click \"Paradigm: pick P at "
                 "the menu\"; tick \"Enter the realm at\" to go straight into the game.",
         "open": {"settings": "BBS"}, "target": {"text": "Logon steps", "window": "settings"}},
        {"text": "Click Connect. Fill in the box that opens (tick Save password) and press its Connect button — "
                 "this guide waits until that box is closed. Login prompts are answered for you from then on.",
         "target": {"attr": "btn_connect"}},
    ]},
    {"id": "loop", "title": "Set up and run a loop", "steps": [
        {"text": "Loops live on the Paths tab, on the right of the main window.",
         "open": {"main_tab": "Paths"}, "target": {"tab": "Paths"}},
        {"text": "Click Loops to list your loops (Paths = one-way paths, Go to room = walk anywhere).",
         "open": {"main_tab": "Paths"}, "target": {"text": "Loops", "exact": True}},
        {"text": "No loops yet? More ▾ → Import MegaMUD paths folder (your MegaMUD Chars folder), Path builder "
                 "(draw one from the map), or Record a loop by walking it once.",
         "open": {"main_tab": "Paths"}, "target": {"text": "More ▾", "exact": True}},
        {"text": "Pick a loop in the list. Exp/hr fills in once you've run it; Starts at is where it begins.",
         "open": {"main_tab": "Paths"}, "target": {"attr": "tree"}},
        {"text": "Click Run loop (or double-click the loop). MudPilot walks to the start if you're elsewhere, "
                 "then loops: fighting, resting and looting as your Settings say.",
         "open": {"main_tab": "Paths"}, "target": {"attr": "paths_btn"}},
        {"text": "Stop (or Esc) stops it any time. Rego carries on from where it stopped.",
         "target": {"attr": "btn_stop"}},
    ]},
    {"id": "party", "title": "Party play and remote @commands", "steps": [
        {"text": "In the game, the leader types 'invite <name>' and the follower 'join <leader>'. "
                 "Settings → Party sets how MudPilot behaves in a party.",
         "open": {"settings": "Party"}, "target": {"tab": "Party", "window": "settings"}},
        {"text": "Party rank: front, mid or back, set whenever you're in a party (casters usually back).",
         "open": {"settings": "Party"}, "target": {"text": "Party rank", "window": "settings"}},
        {"text": "Party heal: heal the others below a % (Heal button on), and ask for healing yourself.",
         "open": {"settings": "Party"}, "target": {"text": "Party heal", "exact": True, "window": "settings"}},
        {"text": "Settings → Talk: remote @commands. Tick Allow remote @commands so friends can control you "
                 "by telepath ('/You @health'). Party members can always use @wait / @ok / @comeback.",
         "open": {"settings": "Talk"}, "target": {"text": "Allow remote @commands", "window": "settings"}},
        {"text": "Nobody else can use them until you add them here. Add as trusted (all) for your own second "
                 "character; Add player, then click a cell to allow just some kinds of command.",
         "open": {"settings": "Talk"}, "target": {"text": "Add as trusted (all)", "window": "settings"}},
        {"text": "The Party tab shows everyone's HP and mana. Help → Remote @ commands lists every @command.",
         "open": {"main_tab": "Party"}, "target": {"tab": "Party"}},
    ]},
    {"id": "items", "title": "Auto-get and auto-stash items", "steps": [
        {"text": "The Get button picks up items you've marked. Click it so it shows green.",
         "target": {"attr": "quick", "key": "auto_loot"}},
        {"text": "Game Data → Items lists every item. Type part of a name in the search box to find it.",
         "open": {"game_data": "Items"}, "target": {"tab": "Items", "window": "Game Data"}},
        {"text": "Select items (Ctrl/Shift for several) and click Auto-get. Auto-get up to… stops at a count; "
                 "Never get skips one.",
         "open": {"game_data": "Items"}, "target": {"text": "Auto-get", "exact": True, "window": "Game Data"}},
        {"text": "Auto-stash = pick it up and hide it in your stash room each lap.",
         "open": {"game_data": "Items"}, "target": {"text": "Auto-stash", "exact": True, "window": "Game Data"}},
        {"text": "Set the stash room: stand in it and click \"Use the room I'm in\" (Settings → Loot). "
                 "A loop can have its own: Paths → More ▾ → Stash room for this loop.",
         "open": {"settings": "Loot"}, "target": {"text": "Use the room I'm in", "window": "settings"}},
    ]},
    {"id": "alerts", "title": "Phone alerts (ntfy)", "steps": [
        {"text": "Install the free ntfy app on your phone. Phone alerts are on Settings → Phone alerts.",
         "open": {"settings": "Phone alerts"}, "target": {"tab": "Phone alerts", "window": "settings"}},
        {"text": "Tick Send alerts to my phone.",
         "open": {"settings": "Phone alerts"}, "target": {"text": "Send alerts to my phone", "window": "settings"}},
        {"text": "Type a topic nobody would guess (anyone with it can read your alerts), then subscribe to the same "
                 "topic in the ntfy app. It's kept in Windows Credential Manager.",
         "open": {"settings": "Phone alerts"}, "target": {"text": "Topic", "exact": True, "window": "settings"}},
        {"text": "Send test: your phone should buzz within a few seconds.",
         "open": {"settings": "Phone alerts"}, "target": {"text": "Send test", "exact": True, "window": "settings"}},
        {"text": "Tick what to be told about: deaths, hang-ups, getting stuck, boss timers and more.",
         "open": {"settings": "Phone alerts"}, "target": {"text": "Alert me about:", "window": "settings"}},
    ]},
]

HIGHLIGHT = ("#ffcc00", "#ff5a1f")      # flashing border colours
BORDER = 3                               # border thickness (px)
PAD = 3                                  # gap between the widget and the border


def guide(gid):
    return next((g for g in GUIDES if g["id"] == gid), None)


# ------------------------------------------------------------------ finding widgets (all fail soft)
def _text_of(w):
    try:
        return str(w.cget("text"))
    except (tk.TclError, AttributeError, ValueError):
        return ""


def _window(app, name):
    """The top-level window to search: the main window, Settings, or a pop-out by its name."""
    try:
        if not name or name == "main":
            return app.root
        if name == "settings":
            return getattr(app, "settings_win", None)
        w = (getattr(app, "windows", None) or {}).get(name)
        return w if w is not None and w.winfo_exists() else None
    except (tk.TclError, AttributeError):
        return None


def _walk(top, main=False):
    """Every widget under top, in tree order. The main window skips the Toplevels that hang off it."""
    out, todo = [], [top]
    while todo:
        w = todo.pop(0)
        try:
            kids = w.winfo_children()
        except tk.TclError:
            continue
        for c in kids:
            if main and isinstance(c, tk.Toplevel):
                continue
            out.append(c)
            todo.append(c)
    return out


def _viewable(w):
    try:
        return bool(w.winfo_exists() and w.winfo_viewable())
    except tk.TclError:
        return False


_TAB_CACHE: dict = {}


def _tab_rect(nb, name):
    """(x, y, w, h) on screen of a notebook tab — ttk tabs aren't widgets, so scan for where it sits
    (once per notebook width; the highlight's flash only re-adds the window position)."""
    try:
        key = (str(nb), name, nb.winfo_width())
        if key in _TAB_CACHE:
            dx, dy, w, h = _TAB_CACHE[key]
            return (nb.winfo_rootx() + dx, nb.winfo_rooty() + dy, w, h)
        r = _scan_tab(nb, name)
        if r:
            _TAB_CACHE[key] = (r[0] - nb.winfo_rootx(), r[1] - nb.winfo_rooty(), r[2], r[3])
        return r
    except tk.TclError:
        return None


def _scan_tab(nb, name):
    try:
        idx = next(i for i, t in enumerate(nb.tabs()) if str(nb.tab(t, "text")).strip() == name)
    except (StopIteration, tk.TclError):
        return None
    try:
        width = nb.winfo_width()
        xs = []
        y = 0
        for y in range(2, 40, 3):
            for x in range(0, max(width, 1), 2):
                try:
                    if str(nb.index(f"@{x},{y}")) == str(idx):
                        xs.append(x)
                except tk.TclError:
                    pass
            if xs:
                break
        if not xs:
            return None
        ys = [yy for yy in range(0, 50) if _at(nb, xs[len(xs) // 2], yy) == str(idx)]
        top, bot = (min(ys), max(ys)) if ys else (y, y + 20)
        return (nb.winfo_rootx() + min(xs), nb.winfo_rooty() + top, max(xs) - min(xs) + 2, bot - top + 1)
    except tk.TclError:
        return None


def _at(nb, x, y):
    try:
        return str(nb.index(f"@{x},{y}"))
    except tk.TclError:
        return ""


def find_target(app, spec):
    """The widget (or a ("rect", nb, name) for a notebook tab) a step points at, or None."""
    if not spec:
        return None
    try:
        if "attr" in spec:
            obj = app
            for part in str(spec["attr"]).split("."):
                obj = getattr(obj, part, None)
                if obj is None:
                    return None
            if "key" in spec:
                obj = (obj or {}).get(spec["key"]) if isinstance(obj, dict) else None
            return obj if isinstance(obj, tk.Misc) and obj.winfo_exists() else None
        top = _window(app, spec.get("window"))
        if top is None:
            return None
        main = spec.get("window", "main") == "main"
        widgets = _walk(top, main=main)
        if "tab" in spec:
            nbs = [w for w in widgets if isinstance(w, ttk.Notebook)]
            for nb in sorted(nbs, key=lambda n: not _viewable(n)):
                try:
                    if any(str(nb.tab(t, "text")).strip() == spec["tab"] for t in nb.tabs()):
                        return ("tab", nb, spec["tab"])
                except tk.TclError:
                    continue
            return None
        want = str(spec.get("text", "")).strip().lower()
        if not want:
            return None
        hits = []
        for w in widgets:
            t = _text_of(w).strip().lower()
            if t and (t == want if spec.get("exact") else want in t):
                hits.append(w)
        hits.sort(key=lambda w: not _viewable(w))     # one on screen first
        return hits[0] if hits else None
    except Exception:
        return None


def target_rect(target):
    """(x, y, w, h) on screen, or None when it isn't showing."""
    try:
        if isinstance(target, tuple) and target and target[0] == "tab":
            _k, nb, name = target
            return _tab_rect(nb, name) if _viewable(nb) else None
        if target is None or not _viewable(target):
            return None
        w, h = target.winfo_width(), target.winfo_height()
        if w <= 1 or h <= 1:
            return None
        return (target.winfo_rootx(), target.winfo_rooty(), w, h)
    except (tk.TclError, AttributeError, ValueError):
        return None


def bring_into_view(target):
    """A widget inside a scrolled settings page: scroll the page so it's on screen."""
    try:
        w = target[1] if isinstance(target, tuple) else target
        child = w
        while child is not None and child.master is not None:
            cv = child.master
            if isinstance(cv, tk.Canvas):
                cv.update_idletasks()
                h = child.winfo_reqheight()
                if h > cv.winfo_height() > 1:
                    y = w.winfo_rooty() - child.winfo_rooty()
                    cv.yview_moveto(max(0.0, (y - 40) / h))
                return
            child = cv
    except (tk.TclError, AttributeError):
        pass


# ------------------------------------------------------------------ the highlight
class Highlight:
    """Four thin always-on-top strips round a widget, flashing. Follows it if the window moves; hides itself
    when the widget isn't on screen. Click-through doesn't matter: the strips sit just outside the widget."""
    def __init__(self, root):
        self.root = root
        self.strips = []
        self.target = None
        self._job = None
        self._phase = 0
        for _ in range(4):
            s = tk.Toplevel(root)
            s.withdraw()
            try:
                s.overrideredirect(True)
                s.attributes("-topmost", True)
            except tk.TclError:
                pass
            s.configure(background=HIGHLIGHT[0], highlightthickness=0, borderwidth=0)
            self.strips.append(s)
        self.shown = False

    def show(self, target):
        self.target = target
        self._tick()

    def hide(self):
        for s in self.strips:
            try:
                s.withdraw()
            except tk.TclError:
                pass
        self.shown = False

    def _tick(self):
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        r = target_rect(self.target) if self.target is not None else None
        if r is None:
            self.hide()
        else:
            x, y, w, h = r
            x0, y0, x1, y1 = x - PAD - BORDER, y - PAD - BORDER, x + w + PAD, y + h + PAD
            col = HIGHLIGHT[self._phase % 2]
            geo = ((x0, y0, x1 - x0 + BORDER, BORDER), (x0, y1, x1 - x0 + BORDER, BORDER),
                   (x0, y0, BORDER, y1 - y0 + BORDER), (x1, y0, BORDER, y1 - y0 + BORDER))
            try:
                for s, (gx, gy, gw, gh) in zip(self.strips, geo):
                    s.configure(background=col)
                    s.geometry(f"{max(gw, 1)}x{max(gh, 1)}+{gx}+{gy}")
                    s.deiconify()
                    s.lift()
                self.shown = True
            except tk.TclError:
                self.hide()
        self._phase += 1
        if self.target is not None:
            try:
                # (quick re-tries while the window it's in is still opening)
                self._job = self.root.after(450 if self.shown else 120, self._tick)
            except tk.TclError:
                self._job = None

    def destroy(self):
        self.target = None
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        for s in self.strips:
            try:
                s.destroy()
            except tk.TclError:
                pass
        self.strips = []


# ------------------------------------------------------------------ the floating step panel
class GuideRunner:
    """One guide on screen: a small panel (Back / Next / Close, Esc closes) and the highlight."""
    current = None

    def __init__(self, app, g):
        if GuideRunner.current is not None:
            GuideRunner.current.close()
        GuideRunner.current = self
        self.app, self.guide, self.i = app, g, 0
        self.target = None
        root = app.root
        try:
            from .app import PANEL, TEXT
        except Exception:
            PANEL, TEXT = "#1a212b", "#e6e6e6"
        self.win = w = tk.Toplevel(root)
        w.title("MudPilot — Guide")
        w.configure(background=PANEL)
        w.resizable(False, False)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        f = tk.Frame(w, background=PANEL, padx=12, pady=10, highlightthickness=2, highlightbackground=HIGHLIGHT[0])
        f.pack(fill="both", expand=True)
        self.lbl_title = tk.Label(f, text=g["title"], background=PANEL, foreground=TEXT, anchor="w",
                                  font=("Segoe UI", 10, "bold"), wraplength=320, justify="left")
        self.lbl_title.pack(fill="x")
        self.lbl_step = tk.Label(f, text="", background=PANEL, foreground=HIGHLIGHT[0], anchor="w",
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_step.pack(fill="x", pady=(2, 4))
        self.lbl_text = tk.Label(f, text="", background=PANEL, foreground=TEXT, anchor="w", justify="left",
                                 font=("Segoe UI", 9), wraplength=320)
        self.lbl_text.pack(fill="x")
        self.lbl_note = tk.Label(f, text="", background=PANEL, foreground="#8a96a8", anchor="w", justify="left",
                                 font=("Segoe UI", 8), wraplength=320)
        self.lbl_note.pack(fill="x", pady=(4, 0))
        b = tk.Frame(f, background=PANEL)
        b.pack(fill="x", pady=(8, 0))
        self.btn_back = ttk.Button(b, text="◀ Back", width=8, command=self.back)
        self.btn_back.pack(side="left")
        self.btn_next = ttk.Button(b, text="Next ▶", width=8, command=self.next)
        self.btn_next.pack(side="left", padx=6)
        ttk.Button(b, text="Close", width=7, command=self.close).pack(side="right")
        self.hl = Highlight(root)
        self.show()

    @property
    def steps(self):
        return self.guide["steps"]

    def _open(self, how):
        """Open the window/tab a step needs. Never fatal."""
        if not how:
            return
        a = self.app
        try:
            if "settings" in how:
                a.open_settings(how["settings"])
            elif "game_data" in how:
                a.open_game_data(how["game_data"])
            elif "main_tab" in how:
                a.show_tab(how["main_tab"])
        except Exception:
            pass

    def show(self):
        st = self.steps[self.i]
        self._open(st.get("open"))
        try:
            self.app.root.update_idletasks()
        except tk.TclError:
            pass
        self.target = find_target(self.app, st.get("target"))
        if self.target is not None:
            bring_into_view(self.target)
        self.lbl_step.configure(text=f"Step {self.i + 1} of {len(self.steps)}")
        self.lbl_text.configure(text=st["text"])
        self.lbl_note.configure(text=("" if not st.get("target") or self.target is not None
                                      else "(couldn't point at it on screen — the text above says where)"))
        self.btn_back.state(["disabled"] if self.i == 0 else ["!disabled"])
        self.btn_next.configure(text="Finish ✓" if self.i == len(self.steps) - 1 else "Next ▶")
        self.hl.show(self.target)
        self._place()
        try:
            self.win.lift()
        except tk.TclError:
            pass

    def _place(self):
        """Bottom-right of the main window, kept on screen; moved to the left when it would cover the target."""
        try:
            w, root = self.win, self.app.root
            w.update_idletasks()
            pw, ph = w.winfo_reqwidth(), w.winfo_reqheight()
            sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
            rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
            x, y = rx + rw - pw - 24, ry + rh - ph - 40
            r = target_rect(self.target)
            if r and x < r[0] + r[2] and r[0] < x + pw and y < r[1] + r[3] and r[1] < y + ph:
                x = rx + 24
            x = max(0, min(x, sw - pw))
            y = max(0, min(y, sh - ph - 40))
            w.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def next(self):
        if self.i >= len(self.steps) - 1:
            self.close()
            return
        self.i += 1
        self.show()

    def back(self):
        if self.i > 0:
            self.i -= 1
            self.show()

    def close(self):
        if GuideRunner.current is self:
            GuideRunner.current = None
        try:
            self.hl.destroy()
        except Exception:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    @property
    def open(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False


def start(app, gid):
    g = guide(gid)
    return GuideRunner(app, g) if g else None


def chooser(app):
    """Help → Step-by-step guides: pick one. A plain small window, no grab."""
    try:
        from .app import PANEL
    except Exception:
        PANEL = "#1a212b"
    old = getattr(app, "_guide_chooser", None)
    try:
        if old is not None and old.winfo_exists():
            old.deiconify()
            old.lift()
            return old
    except tk.TclError:
        pass
    w = tk.Toplevel(app.root)
    w.title("MudPilot — Step-by-step guides")
    w.configure(background=PANEL)
    w.resizable(False, False)
    w.bind("<Escape>", lambda e: w.destroy())
    f = ttk.Frame(w, padding=12)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="Pick a guide. It points at each thing to click; Close or Esc stops it any time.",
              style="Muted.TLabel", wraplength=340).pack(anchor="w", pady=(0, 8))

    def go(gid):
        w.destroy()
        start(app, gid)
    for g in GUIDES:
        ttk.Button(f, text=f"{g['title']}  ({len(g['steps'])} steps)",
                   command=lambda gid=g["id"]: go(gid)).pack(fill="x", pady=2)
    ttk.Button(f, text="Close", command=w.destroy).pack(anchor="e", pady=(8, 0))
    try:
        w.transient(app.root)
    except tk.TclError:
        pass
    app._guide_chooser = w
    return w
