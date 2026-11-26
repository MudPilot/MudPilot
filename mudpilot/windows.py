"""Extra MegaMUD-style windows: conversations, session stats, exp chart, inventory
calculator. Each panel works inside a tab or in its own window."""
from __future__ import annotations

import re
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

from . import gearcalc as G
from .bosses import fmt_dur

BG, PANEL, TEXT, MUTED, ACCENT = "#0b0d10", "#151a21", "#e0e6ef", "#8a94a6", "#2fbf71"
GRID, AMBER = "#232b36", "#e6b450"


def popout(app, title, factory, geometry="760x560", key=None):
    """Open (or raise) a floating window holding a panel."""
    key = key or title
    w = app.windows.get(key)
    if w is not None and w.winfo_exists():
        w.deiconify()
        w.lift()
        return w
    w = tk.Toplevel(app.root)
    w.title(f"MudPilot — {title}")
    tie_to_main(app, w, title)
    w.configure(background=PANEL)
    cfg = app.s.settings
    w.geometry(safe_geometry(w, (cfg.window_geom or {}).get(key)) or geometry)
    pane = factory(w)
    pane.pack(fill="both", expand=True)
    app.windows[key] = w
    remember_window(app, w, key)
    return w


def tie_to_main(app, w, title):
    """Dan, 2026-10-28 (2-3 MudPilots open): a settings or tool window says whose it is in its title bar
    ("Miserable — Settings"), and opening it from the taskbar brings its own main window up right behind it."""
    w._tied_title = title
    tied = app.__dict__.setdefault("_tied_windows", [])
    tied.append(w)
    retitle(app, w)

    def mapped(e):
        if e.widget is not w:
            return
        try:
            if app.root.state() == "iconic":
                app.root.deiconify()
            app.root.lift()
            w.lift()
        except tk.TclError:
            pass
    w.bind("<Map>", mapped, add="+")


def retitle(app, w):
    cfg = app.s.settings
    who = cfg.my_name or cfg.profile
    t = f"{who} — {w._tied_title} - MudPilot" if who else f"MudPilot — {w._tied_title}"
    try:
        if w.winfo_exists() and w.title() != t:
            w.title(t)
    except tk.TclError:
        pass


def safe_geometry(win, geom):
    """A saved 'WxH+X+Y' — only if it's still on a screen (a monitor may have been unplugged)."""
    import re as _re
    m = _re.match(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", geom or "")
    if not m:
        return None
    w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    try:
        vx, vy = win.winfo_vrootx(), win.winfo_vrooty()
        vw, vh = max(win.winfo_vrootwidth(), win.winfo_screenwidth()), max(win.winfo_vrootheight(), win.winfo_screenheight())
    except tk.TclError:
        return geom
    if x > vx + vw - 60 or y > vy + vh - 40 or x + w < vx + 60 or y < vy - 20:
        return f"{w}x{h}"                    # keep the size, let Windows place it
    return geom


def remember_window(app, w, key, reopen=True):
    """Save a window's size/place as it moves, and whether it was open, so it comes back that way."""
    cfg = app.s.settings
    state = {"after": None}

    def save():
        state["after"] = None
        try:
            if not w.winfo_exists():
                return
            g = dict(cfg.window_geom or {})
            if w.state() == "normal":
                g[key] = w.geometry()
                g[key + "_zoomed"] = False
            elif w.state() == "zoomed":
                g[key + "_zoomed"] = True
            else:
                return
            cfg.window_geom = g
            cfg.save()
        except tk.TclError:
            pass

    def moved(e):
        if e.widget is not w:
            return
        if state["after"]:
            w.after_cancel(state["after"])
        state["after"] = w.after(800, save)
    w.bind("<Configure>", moved, add="+")
    if reopen:
        if key not in (cfg.open_windows or []):
            cfg.open_windows = list(cfg.open_windows or []) + [key]
            cfg.save()

        def gone(e):
            if e.widget is w and not getattr(app, "_quitting", False):
                cfg.open_windows = [k for k in (cfg.open_windows or []) if k != key]
                cfg.save()
        w.bind("<Destroy>", gone, add="+")


# ----------------------------------------------------------------- conversations
import weakref

CHAT_PANES = weakref.WeakSet()


class ChatPane(ttk.Frame):
    """Conversations, laid out like pMUD's Chatter: View / Filters / Actions / Font / Colors menus,
    a search bar with Find Next, the talk itself, and a line to type into (Split ; = several commands)."""
    # MegaMUD's default conversation colours
    COLORS = {"gossip": "#ff00ff", "auction": "#c0c000", "telepath": "#ffffff", "say": "#008000",
              "gangpath": "#808000", "broadcast": "#00ff00", "yell": "#ff5050", "realm": "#c0c0c0",
              "location": "#ffff00", "action": "#ffaa55"}
    LABELS = {"realm": "Enter/Exit", "location": "Location (pro)", "action": "Actions"}
    CHANNELS = ("gossip", "telepath", "say", "gangpath", "broadcast", "auction", "yell", "realm", "location",
                "action")

    def __init__(self, master, app):
        super().__init__(master, padding=4)
        self.app = app
        st = app.s.settings
        flt = dict(getattr(st, "chat_filters", None) or {})
        self.show = {}
        for ch in self.CHANNELS:
            v = tk.BooleanVar(value=flt.get(ch, True))
            v.trace_add("write", lambda *a: self._filters_changed())
            self.show[ch] = v
        # MegaMUD/MudPilot remote traffic (@health, @wait, {HP=…}, {ok}) — off by default so real talk stands out
        self.show_bot = tk.BooleanVar(value=bool(getattr(st, "chat_show_bot", False)))
        self.show_bot.trace_add("write", lambda *a: self._filters_changed())
        self.stamps = tk.BooleanVar(value=bool(getattr(st, "chat_timestamps", True)))
        self.stamps.trace_add("write", lambda *a: self._filters_changed())
        self.wrap = tk.BooleanVar(value=True)
        self.split = tk.BooleanVar(value=bool(getattr(st, "chat_split", True)))
        self.split.trace_add("write", lambda *a: self._save("chat_split", bool(self.split.get())))
        # ---- menus
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        for label, build in (("View", self._view_menu), ("Filters", self._filter_menu), ("Actions", self._action_menu),
                             ("Font", self._font_menu), ("Colors", self._color_menu)):
            mb = ttk.Menubutton(bar, text=label, style="Toolbutton")
            m = tk.Menu(mb, tearoff=False)
            build(m)
            mb["menu"] = m
            mb.pack(side="left")
        # text size at a click, right above Find Next (Dan, 2026-10-30)
        ttk.Button(bar, text="+", width=3, command=lambda: self._font_size(1)).pack(side="right")
        ttk.Button(bar, text="−", width=3, command=lambda: self._font_size(-1)).pack(side="right", padx=(0, 2))
        # ---- search
        sb = ttk.Frame(self)
        sb.pack(fill="x", pady=(2, 2))
        ttk.Label(sb, text="Search:").pack(side="left")
        self.find_var = tk.StringVar()
        fe = ttk.Entry(sb, textvariable=self.find_var)
        fe.pack(side="left", fill="x", expand=True, padx=4)
        fe.bind("<Return>", lambda e: self.find_next())
        self.find_var.trace_add("write", lambda *a: self._mark_all())
        ttk.Button(sb, text="Find Next", command=self.find_next).pack(side="left")
        self._find_at = "end"
        # ---- the talk
        self.box = tk.Text(self, background="#000000", foreground="#ffffff",
                           font=(st.chat_font or "Consolas", int(st.chat_font_size or 10)),
                           borderwidth=0, state="disabled", wrap="word", height=4)
        CHAT_PANES.add(self)
        self._apply_colors()
        self.box.tag_configure("time", foreground="#00ffff")
        self.box.tag_configure("found", background="#5a4a00")
        self.box.tag_configure("found_now", background="#b08800", foreground="#000000")
        self.box.pack(fill="both", expand=True)
        # ---- type here (sent as typed: .hi says, /Name hi telepaths, gos hi gossips)
        ib = ttk.Frame(self)
        ib.pack(fill="x", pady=(3, 0))
        self.entry = ttk.Entry(ib)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send())
        sp = st.command_splitter or ";"
        ttk.Checkbutton(ib, text=f"Split {sp}", variable=self.split).pack(side="left", padx=(6, 0))
        app.s.chat.listeners.append(self._live)
        self.redraw()

    # ------------------------------------------------------------ menus
    def _save(self, key, val):
        try:
            setattr(self.app.s.settings, key, val)
            self.app.s.settings.save()
        except Exception:
            pass

    def _filters_changed(self):
        self._save("chat_filters", {ch: bool(v.get()) for ch, v in self.show.items()})
        self._save("chat_show_bot", bool(self.show_bot.get()))
        self._save("chat_timestamps", bool(self.stamps.get()))
        self.redraw()

    def _view_menu(self, m):
        m.add_checkbutton(label="Timestamps", variable=self.stamps)
        m.add_checkbutton(label="Wrap long lines", variable=self.wrap,
                          command=lambda: self.box.configure(wrap="word" if self.wrap.get() else "none"))
        m.add_checkbutton(label="@ commands / bot answers", variable=self.show_bot)
        m.add_separator()
        m.add_command(label="Jump to the newest", command=lambda: self.box.see("end"))

    def _filter_menu(self, m):
        for ch in self.CHANNELS:
            m.add_checkbutton(label=self.LABELS.get(ch, ch.title()), variable=self.show[ch])
        m.add_separator()
        m.add_command(label="Show everything", command=lambda: [v.set(True) for v in self.show.values()])
        m.add_command(label="Only gossip and telepaths",
                      command=lambda: [v.set(ch in ("gossip", "telepath")) for ch, v in self.show.items()])

    def _action_menu(self, m):
        m.add_command(label="Copy all", command=self.copy_all)
        m.add_command(label="Save to a file…", command=self.save_file)
        m.add_command(label="Clear the window", command=self.clear)

    def _font_menu(self, m):
        m.add_command(label="Bigger", command=lambda: self._font_size(+1))
        m.add_command(label="Smaller", command=lambda: self._font_size(-1))
        m.add_separator()
        for fam in (("Menlo", "Monaco", "Helvetica", "Courier New") if sys.platform == "darwin"
                    else ("Consolas", "Arial", "Segoe UI", "Courier New", "Lucida Console")):
            m.add_command(label=fam, command=lambda f=fam: self._font_family(f))

    def _color_menu(self, m):
        for ch in self.CHANNELS:
            m.add_command(label=self.LABELS.get(ch, ch.title()) + "…", command=lambda c=ch: self._pick_color(c))
        m.add_separator()
        m.add_command(label="MegaMUD defaults", command=self._reset_colors)

    def _colors(self):
        out = dict(self.COLORS)
        out.update(getattr(self.app.s.settings, "chat_colors", None) or {})
        return out

    def _apply_colors(self):
        for ch, col in self._colors().items():
            try:
                self.box.tag_configure(ch, foreground=col)
            except tk.TclError:
                pass

    def _pick_color(self, ch):
        from tkinter import colorchooser
        got = colorchooser.askcolor(color=self._colors().get(ch, "#ffffff"), parent=self,
                                    title=f"{self.LABELS.get(ch, ch.title())} colour")
        if got and got[1]:
            cc = dict(getattr(self.app.s.settings, "chat_colors", None) or {})
            cc[ch] = got[1]
            self._save("chat_colors", cc)
            for cp in list(CHAT_PANES):
                cp._apply_colors()

    def _reset_colors(self):
        self._save("chat_colors", {})
        for cp in list(CHAT_PANES):
            cp._apply_colors()

    def _font_size(self, d):
        st = self.app.s.settings
        st.chat_font_size = max(6, min(40, int(st.chat_font_size or 10) + d))
        st.save()
        self.app.apply_fonts()

    def _font_family(self, fam):
        st = self.app.s.settings
        st.chat_font = fam
        st.save()
        self.app.apply_fonts()

    def copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(self.box.get("1.0", "end-1c"))

    def save_file(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile="conversations.txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.box.get("1.0", "end-1c"))

    def clear(self):
        self._cleared_at = time.time()
        self.redraw()

    # ------------------------------------------------------------ search
    def _mark_all(self):
        self.box.tag_remove("found", "1.0", "end")
        self.box.tag_remove("found_now", "1.0", "end")
        self._find_at = "end"
        q = self.find_var.get()
        if not q:
            return
        start = "1.0"
        while True:
            pos = self.box.search(q, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(q)}c"
            self.box.tag_add("found", pos, end)
            start = end

    def find_next(self):
        """Newest first, then further back each press (wraps round)."""
        q = self.find_var.get()
        if not q:
            return
        pos = self.box.search(q, self._find_at, stopindex="1.0", backwards=True, nocase=True)
        if not pos:
            pos = self.box.search(q, "end", stopindex="1.0", backwards=True, nocase=True)
            if not pos:
                return
        self.box.tag_remove("found_now", "1.0", "end")
        self.box.tag_add("found_now", pos, f"{pos}+{len(q)}c")
        self.box.see(pos)
        self._find_at = pos

    def _live(self, e):
        if not self.winfo_exists():
            raise RuntimeError("closed")
        self.add(e)

    def add(self, e, redraw=False):
        t, ch, who, msg = e
        if ch in self.show and not self.show[ch].get():
            return
        if not self.show_bot.get() and self.is_bot(msg) and not self.app.s.chat.you_asked(e):
            return
        if t < getattr(self, "_cleared_at", 0):
            return
        self.box.configure(state="normal")
        if self.stamps.get():
            stamp = time.strftime("[%I:%M %p] ", time.localtime(t)).replace("[0", "[")
            self.box.insert("end", stamp, ("time",))
        self.box.insert("end", self.megamud_line(ch, who, msg) + "\n", (ch,))
        self.box.configure(state="disabled")
        if not redraw:
            self.box.see("end")

    @staticmethod
    def is_bot(msg) -> bool:
        """@commands and the bots' automatic {answers} (MegaMUD remote control)."""
        m = (msg or "").strip().strip('"').lstrip(".")
        return m.startswith(("@", "{")) or bool(re.match(r"^\(to you\)\s*[\"']?\{", m))

    @staticmethod
    def megamud_line(ch, who, msg):
        """Show each line the way the game (and MegaMUD's conversation window) shows it."""
        if ch == "say":
            return f'You say "{msg}"' if who == "You" else f'{who} says "{msg}"'
        if ch == "telepath":
            if who.startswith("You → "):
                return f"You telepath {who[6:]}: {msg}"
            return f"{who} telepaths: {msg}"
        if ch == "broadcast":
            return f'Broadcast from {who} "{msg}"'
        if ch == "realm":
            return f"{who} just {msg}" + ("!!!" if msg.lower() == "disconnected" else ".")
        if ch == "restart":
            return msg
        if ch == "location":
            return f"You are in {msg}"
        if ch == "action":
            return msg
        if ch == "yell":
            return f'{who} yells "{msg}"'
        verb = {"gossip": "gossips", "auction": "auctions", "gangpath": "gangpaths"}.get(ch)
        return f"{who} {verb}: {msg}" if verb else f"{who}: {msg}"

    def redraw(self):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.configure(state="disabled")
        for e in self.app.s.chat.entries[-800:]:
            self.add(e, redraw=True)
        self.box.see("end")

    def send(self):
        """Typed here = typed in the game: .hi says, /Name hi telepaths, gos hi gossips.
        Split ; on: e;mist;.@do sand goes out as three commands (;; = a real ;)."""
        msg = self.entry.get().strip()
        if not self.app.s.telnet.connected:
            return
        if not msg:
            # 0.8.227.6 (Dan: after killing the Bloody Executioner, Enter here did nothing — he couldn't look at the
            # room for drops): an empty Enter is a look, as in the command line under the MUD window
            self.app._last_input = time.time()
            self.app.s.send("")
            return
        self.entry.delete(0, "end")
        sp = self.app.s.settings.command_splitter or ";"
        if self.split.get() and sp in msg.replace(sp + sp, ""):
            from .app import split_commands
            for c in split_commands(msg, sp):
                self.app.s.send(c)
            return
        self.app.s.send(msg.replace(sp + sp, sp) if self.split.get() else msg)


# ----------------------------------------------------------------- session stats
class StatsPane(ttk.Frame):
    ROWS = (("time", "Session time"), ("exp", "Experience gained"), ("eph", "Exp per hour (session)"),
            ("eph30", "Exp per hour (last 30 min)"), ("need", "Exp to next level"), ("ttl", "Time to level"),
            ("kills", "Kills"), ("avg", "Average exp per kill"), ("deaths", "Deaths"), ("rests", "Rests"),
            ("cash", "Cash looted (copper)"), ("steps", "Rooms walked"), ("lag", "Board lag (last 10 min)"),
            ("world", "MME data"))

    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        b = ttk.Frame(self)
        b.pack(fill="x", pady=(0, 6))
        ttk.Button(b, text="Reset session stats", command=self.reset).pack(side="left")
        ttk.Button(b, text="Exp chart…", command=app.open_exp_chart).pack(side="left", padx=6)
        ttk.Button(b, text="Rest log…", command=self.rest_log).pack(side="left")
        top = ttk.Frame(self)
        top.pack(fill="x")
        left = ttk.Frame(top)
        left.pack(side="left", anchor="n")
        self.lbl = {}
        for i, (k, label) in enumerate(self.ROWS):
            ttk.Label(left, text=label, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=2)
            l = ttk.Label(left, text="—", style="Head.TLabel")
            l.grid(row=i, column=1, sticky="w", padx=14)
            self.lbl[k] = l
        right = ttk.Frame(top)
        right.pack(side="left", anchor="n", padx=20)
        ttk.Label(right, text="Where the time went", style="Head.TLabel").pack(anchor="w")
        self.time_canvas = tk.Canvas(right, width=275, height=120, background=PANEL, highlightthickness=0)
        self.time_canvas.pack(anchor="w", pady=4)
        ttk.Label(self, text="Why it rested", style="Head.TLabel").pack(anchor="w", pady=(10, 2))
        self.rtree = ttk.Treeview(self, columns=("n", "avg", "tot", "brk"), show="tree headings", height=4)
        self.rtree.heading("#0", text="Reason")
        self.rtree.column("#0", width=220)
        for c, t in (("n", "Rests"), ("avg", "Avg"), ("tot", "Total"), ("brk", "Broken up")):
            self.rtree.heading(c, text=t)
            self.rtree.column(c, width=70, anchor="e")
        self.rtree.pack(fill="x")
        ttk.Label(self, text="Kills by monster", style="Head.TLabel").pack(anchor="w", pady=(10, 2))
        self.tree = ttk.Treeview(self, columns=("kills", "exp", "avg"), show="tree headings", height=7)
        self.tree.heading("#0", text="Monster")
        self.tree.column("#0", width=200)
        for c, t in (("kills", "Kills"), ("exp", "Exp"), ("avg", "Avg exp")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=80, anchor="e")
        self.tree.pack(fill="both", expand=True)
        app.live_panes.append(self)
        self.refresh()

    def reset(self):
        self.app.s.state.reset_stats()          # (everything the window shows: session.py hooks SessionStats in)
        self.app.s.log("Session statistics reset")
        self.refresh()

    def rest_log(self):
        """Every rest this session: when, why, how long, what it got back, why it ended."""
        ss = self.app.s.stats
        top = tk.Toplevel(self)
        top.title("MudPilot — Rest log")
        top.configure(background=PANEL)
        top.geometry("900x420")
        cols = ("secs", "kind", "why", "gain", "ended")
        t = ttk.Treeview(top, columns=cols, show="tree headings")
        t.heading("#0", text="Time")
        t.column("#0", width=80)
        for c, h, wd in (("secs", "Secs", 50), ("kind", "Kind", 70), ("why", "Why it sat down", 250),
                         ("gain", "Got back", 190), ("ended", "Why it got up", 200)):
            t.heading(c, text=h)
            t.column(c, width=wd, anchor="e" if c == "secs" else "w")
        sb = ttk.Scrollbar(top, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        for r in reversed(ss.rest_log):
            a, b = r["start"], r["end"]
            gain = f"HP {a['hp']:.0f}→{b['hp']:.0f}%  MA {a['ma']:.0f}→{b['ma']:.0f}%"
            t.insert("", "end", text=time.strftime("%H:%M:%S", time.localtime(r["t"])),
                     values=(r["secs"], r["kind"], r["why"], gain,
                             r["ended"] + (f" (interrupted {r['breaks']}×)" if r["breaks"] else "")))

    def refresh(self):
        s = self.app.s
        st, ss = s.state, s.stats
        secs = int(ss.elapsed())
        ttl = ss.time_to_level()
        need = max(0, st.exp_needed - st._exp_since_line) if st.exp_needed else None
        vals = {"time": fmt_dur(secs) if secs >= 60 else f"{secs}s", "exp": f"{st.exp_gained:,}",
                "eph": f"{ss.exp_rate():,.0f}", "eph30": f"{ss.exp_rate(1800):,.0f}",
                "need": f"{need:,}" if need is not None else "type exp", "ttl": fmt_dur(ttl) if ttl else "—",
                "kills": st.kills, "avg": f"{st.exp_gained / st.kills:,.0f}" if st.kills else "—",
                "deaths": st.deaths,
                "rests": f"{ss.rests}" + (f"  (avg {sum(r['secs'] for r in ss.rest_log) / len(ss.rest_log):.0f} s)"
                                          if ss.rest_log else ""), "cash": f"{st.copper_looted:,}", "steps": st.steps_walked,
                "world": f"{len(s.world.rooms):,} rooms · board {s.settings.board}" if s.world.loaded else "not imported"}
        ls = ss.lag_stats(600)
        vals["lag"] = f"avg {ls[0]:.2f} s · 90% under {ls[1]:.2f} s · worst {ls[2]:.1f} s" if ls else "—"
        for k, v in vals.items():
            self.lbl[k].configure(text=str(v))
        # time split bars
        c = self.time_canvas
        c.delete("all")
        total = sum(ss.time_in.values()) or 1
        colors = {"fighting": "#ff6b6b", "resting": "#6d8cff", "walking": ACCENT, "idle": "#5a6577"}
        for i, (k, v) in enumerate(ss.time_in.items()):
            y = 8 + i * 28
            w = 150 * v / total
            c.create_text(0, y + 7, anchor="w", text=k.title(), fill=MUTED, font=("Segoe UI", 9))
            c.create_rectangle(70, y, 70 + 150, y + 14, fill="#0f1318", outline="")
            c.create_rectangle(70, y, 70 + max(w, 1), y + 14, fill=colors[k], outline="")
            c.create_text(226, y + 7, anchor="w", text=f"{100 * v / total:.0f}%", fill=TEXT, font=("Segoe UI", 9))
        # rest reasons
        self.rtree.delete(*self.rtree.get_children())
        for why, n, avg, tot, brk in ss.rest_summary():
            self.rtree.insert("", "end", text=why, values=(n, f"{avg:.0f} s", fmt_dur(tot) if tot >= 60 else f"{tot:.0f} s",
                                                           brk or "—"))
        # kills by monster
        self.tree.delete(*self.tree.get_children())
        for name, d in sorted(ss.mobs.items(), key=lambda x: -x[1]["exp"]):
            self.tree.insert("", "end", text=name, values=(d["kills"], f"{d['exp']:,}",
                                                           f"{d['exp'] / max(d['kills'], 1):,.0f}"))


# ----------------------------------------------------------------- exp chart
class ExpChartPane(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.head = ttk.Label(self, text="", style="Head.TLabel")
        self.head.pack(anchor="w")
        self.sub = ttk.Label(self, text="", style="Muted.TLabel")
        self.sub.pack(anchor="w", pady=(0, 6))
        self.c = tk.Canvas(self, background=BG, highlightthickness=0)
        self.c.pack(fill="both", expand=True)
        self.c.bind("<Configure>", lambda e: self.refresh())
        app.live_panes.append(self)

    def refresh(self):
        s = self.app.s
        ss, st = s.stats, s.state
        ttl = ss.time_to_level()
        self.head.configure(text=f"{st.exp_gained:,} exp this session  ·  {ss.exp_rate():,.0f}/hr")
        self.sub.configure(text=f"Last 30 min: {ss.exp_rate(1800):,.0f}/hr" +
                                (f"  ·  level in {fmt_dur(ttl)}" if ttl else "  ·  type exp in the game for time to level"))
        c = self.c
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        pad_l, pad_r, pad_t, pad_b = 70, 16, 12, 30
        top_h = (H - pad_t - pad_b) * 0.62
        bar_top = pad_t + top_h + 26
        bar_h = H - pad_b - bar_top
        smp = ss.samples + [(time.time(), st.exp_gained, st.kills)]
        t0, t1 = smp[0][0], max(smp[-1][0], smp[0][0] + 60)
        ymax = max(max(e for _t, e, _k in smp), 1)

        def x(t):
            return pad_l + (W - pad_l - pad_r) * (t - t0) / (t1 - t0)

        def y(e):
            return pad_t + top_h - top_h * e / ymax

        # grid + labels
        for i in range(5):
            gy = pad_t + top_h * i / 4
            c.create_line(pad_l, gy, W - pad_r, gy, fill=GRID)
            c.create_text(pad_l - 8, gy, anchor="e", fill=MUTED, font=("Segoe UI", 8),
                          text=f"{ymax * (4 - i) / 4:,.0f}")
        c.create_text(pad_l, pad_t - 2, anchor="sw", fill=MUTED, font=("Segoe UI", 8), text="cumulative exp")
        mins = (t1 - t0) / 60
        step = next(sv for sv in (1, 5, 10, 15, 30, 60, 120, 240, 480) if mins / sv <= 8)
        m = 0
        while m <= mins:
            gx = x(t0 + m * 60)
            c.create_line(gx, pad_t, gx, H - pad_b, fill=GRID)
            c.create_text(gx, H - pad_b + 12, fill=MUTED, font=("Segoe UI", 8),
                          text=f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}m")
            m += step
        # cumulative line
        pts = []
        for t, e, _k in smp:
            pts += [x(t), y(e)]
        if len(pts) >= 4:
            c.create_line(*pts, fill=ACCENT, width=2, smooth=False)
        # exp per bucket bars
        nb = 24
        span = (t1 - t0) / nb
        buckets = [0] * nb
        prev = smp[0]
        for cur in smp[1:]:
            gained = cur[1] - prev[1]
            if gained > 0:
                bi = min(nb - 1, int((cur[0] - t0) / span))
                buckets[bi] += gained
            prev = cur
        bmax = max(max(buckets), 1)
        c.create_text(pad_l, bar_top - 4, anchor="sw", fill=MUTED, font=("Segoe UI", 8),
                      text=f"exp per {fmt_dur(span) if span >= 60 else f'{int(span)}s'}")
        bw = (W - pad_l - pad_r) / nb
        for i, v in enumerate(buckets):
            if v <= 0:
                continue
            h = bar_h * v / bmax
            bx = pad_l + i * bw
            c.create_rectangle(bx + 1, bar_top + bar_h - h, bx + bw - 1, bar_top + bar_h, fill=AMBER, outline="")
        c.create_text(pad_l - 8, bar_top, anchor="e", fill=MUTED, font=("Segoe UI", 8), text=f"{bmax:,.0f}")


# ----------------------------------------------------------------- inventory calculator
class GrabTicks:
    """A ☐/☑ "Grab" column on a gear list: ticked items go on the Loot tab's auto-grab list."""
    GRAB_COL = "grab"

    def _grab_init(self, tree, bottom):
        tree.heading(self.GRAB_COL, text="Grab")
        tree.column(self.GRAB_COL, width=46, anchor="center", stretch=False)
        tree.bind("<Button-1>", self._grab_click, add="+")
        bar = ttk.Frame(bottom)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="☑ Auto-grab all of these", command=lambda: self._grab_all(True)).pack(side="left")
        ttk.Button(bar, text="☐ Untick all", command=lambda: self._grab_all(False)).pack(side="left", padx=6)
        ttk.Label(bar, text="Ticked items are picked up whenever you see them (Settings → Loot → Always pick up).",
                  style="Muted.TLabel").pack(side="left", padx=8)

    def _grab_list(self):
        cfg = self.app.s.settings
        if cfg.loot_items is None:
            cfg.loot_items = []
        return cfg.loot_items

    def _grabbed(self, name) -> bool:
        return name.lower() in {x.strip().lower() for x in self._grab_list()}

    def _grab_set(self, name, on):
        lst = self._grab_list()
        lst[:] = [x for x in lst if x.strip().lower() != name.lower()]
        if on:
            lst.append(name)
            self.app.s.settings.auto_loot = True
        self.app.s.settings.save()

    def _grab_mark(self, name):
        return "☑" if self._grabbed(name) else "☐"

    def _grab_refresh(self):
        for iid in self.tree.get_children(""):
            for i in (iid, *self.tree.get_children(iid)):
                nm = self._grab_name(i)
                if nm:
                    self.tree.set(i, self.GRAB_COL, self._grab_mark(nm))

    def _grab_click(self, e):
        if self.tree.identify_region(e.x, e.y) != "cell":
            return
        col = self.tree.identify_column(e.x)
        if self.tree.column(col, "id") != self.GRAB_COL:
            return
        iid = self.tree.identify_row(e.y)
        nm = self._grab_name(iid) if iid else None
        if nm:
            self._grab_set(nm, not self._grabbed(nm))
            self._grab_refresh()
            return "break"

    def _grab_all(self, on):
        for iid in self.tree.get_children(""):
            nm = self._grab_name(iid)
            if nm:
                self._grab_set(nm, on)
        self._grab_refresh()


def item_window(app, g):
    """Full stats for one item (double-click in the inventory calculator)."""
    w = app.s.world
    top = tk.Toplevel(app.root)
    top.title(f"MudPilot — {g['name']}")
    top.configure(background=PANEL)
    top.transient(app.root)
    f = ttk.Frame(top, padding=10)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text=g["name"], style="Head.TLabel").pack(anchor="w")
    worn = G.worn_items(w, app.s.state.carrying)
    slot = G.slot_name(g)
    cur = next((c for k, c in worn.items() if k.split(" ")[0] == slot), None)
    if cur and cur is not g:
        ttk.Label(f, text=f"You wear {cur['name']} there now: AC {G.fmt(G.ac(cur))} / DR {G.fmt(G.dr(cur))}",
                  style="Muted.TLabel").pack(anchor="w")
    elif cur is g:
        ttk.Label(f, text="You're wearing this.", style="Muted.TLabel").pack(anchor="w")
    rows = G.item_stats(w, g)
    t = ttk.Treeview(f, columns=("v",), show="tree", height=min(24, len(rows) + 6))
    t.column("#0", width=200)
    t.column("v", width=260)
    t.pack(fill="both", expand=True, pady=6)
    secs = {}
    for sec, lbl, val in rows:
        if sec not in secs:
            secs[sec] = t.insert("", "end", text=sec, open=True)
        t.insert(secs[sec], "end", text=lbl, values=(str(val),))
    ttk.Label(f, text="Where to get it", style="Head.TLabel").pack(anchor="w", pady=(6, 2))
    for txt, room in G.sources(w, g, 8):
        r = ttk.Frame(f)
        r.pack(fill="x")
        ttk.Label(r, text=txt).pack(side="left")
        if room:
            ttk.Button(r, text="Go", width=4, command=lambda rm=room: app.goto_room(tuple(rm))).pack(side="right")
    b = ttk.Frame(f)
    b.pack(fill="x", pady=(8, 0))
    cfg = app.s.settings
    grab = tk.BooleanVar(value=g["name"].lower() in {x.strip().lower() for x in (cfg.loot_items or [])})

    def set_grab():
        lst = cfg.loot_items if cfg.loot_items is not None else []
        lst[:] = [x for x in lst if x.strip().lower() != g["name"].lower()] + ([g["name"]] if grab.get() else [])
        cfg.loot_items = lst
        if grab.get():
            cfg.auto_loot = True
        cfg.save()
    ttk.Checkbutton(b, text="Pick this up whenever I see it", variable=grab, command=set_grab).pack(side="left")
    ttk.Button(b, text="Close", command=top.destroy).pack(side="right")
    top.bind("<Escape>", lambda e: top.destroy())
    return top


class CalcPane(GrabTicks, ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        w = app.s.world
        if not getattr(w, "gear", None):
            ttk.Label(self, text="The inventory calculator needs item data from MME.\n"
                                 "Re-import this board's MME file (File → Import MME database) and reopen this window.",
                      style="Muted.TLabel", justify="left").pack(anchor="w", pady=20)
            return
        st = app.s.state
        self.cls_names = ["Any class"] + [v["Name"] for k, v in sorted(w.classes.items())]
        self.race_names = ["Any race"] + [v["Name"] for k, v in sorted(w.races.items())]
        form = ttk.Frame(self)
        form.pack(fill="x")
        self.goal = tk.StringVar(value="Armour class (AC)")
        self.cls = tk.StringVar(value=st.char_class if st.char_class in self.cls_names else "Any class")
        self.race = tk.StringVar(value=st.race if st.race in self.race_names else "Any race")
        self.level = tk.StringVar(value=str(st.level or app.s.settings.char_level or 0))
        self.align = tk.StringVar(value="Any")
        self.strength = tk.StringVar(value=str(st.strength or 0))
        self.limited = tk.BooleanVar(value=True)
        self.compare = tk.BooleanVar(value=True)
        r0 = ttk.Frame(form)
        r0.pack(fill="x")
        ttk.Label(r0, text="Best gear for").pack(side="left")
        ttk.Combobox(r0, textvariable=self.goal, values=list(G.GOALS), width=22, state="readonly").pack(side="left", padx=6)
        ttk.Button(r0, text="Calculate", style="Accent.TButton", command=self.run).pack(side="left", padx=6)
        ttk.Button(r0, text="Read my inventory", command=self.read_inv).pack(side="left")
        r1 = ttk.Frame(form)
        r1.pack(fill="x", pady=6)
        for lbl, var, vals, wd in (("Class", self.cls, self.cls_names, 12), ("Race", self.race, self.race_names, 11),
                                   ("Alignment", self.align, G.ALIGNMENTS, 8)):
            ttk.Label(r1, text=lbl).pack(side="left")
            ttk.Combobox(r1, textvariable=var, values=vals, width=wd, state="readonly").pack(side="left", padx=(4, 10))
        ttk.Label(r1, text="Level").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=255, textvariable=self.level, width=5).pack(side="left", padx=(4, 10))
        ttk.Label(r1, text="Str").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=255, textvariable=self.strength, width=5).pack(side="left", padx=4)
        r2 = ttk.Frame(form)
        r2.pack(fill="x")
        ttk.Checkbutton(r2, text="Include limited items", variable=self.limited).pack(side="left")
        ttk.Checkbutton(r2, text="Compare with what I'm wearing", variable=self.compare).pack(side="left", padx=12)
        self.mine = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="Show my gear", variable=self.mine, command=self._mine_toggle).pack(side="left")
        ttk.Label(r2, text="0 level/str = ignore", style="Muted.TLabel").pack(side="left", padx=8)
        self.total = ttk.Label(self, text="", style="Head.TLabel")
        self.total.pack(anchor="w", pady=(10, 4))
        cols = ("grab", "slot", "val", "cur", "gain", "where")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", height=14)
        self.tree.heading("#0", text="Slot / item")
        self.tree.column("#0", width=240)
        for c, t, wd in (("slot", "Worn at", 70), ("val", "Value", 60), ("cur", "Wearing now", 170), ("gain", "Gain", 55),
                         ("where", "Where to get it", 260)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wd, anchor="w" if c in ("cur", "where", "slot") else "e")
        self.tree.tag_configure("up", foreground="#5cff7a")
        self.tree.tag_configure("same", foreground=MUTED)
        self.tree.tag_configure("alt", foreground="#a9b4c4")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.tree.bind("<Double-1>", self._dbl)
        self._grab_init(self.tree, self)
        self.detail = ttk.Label(self, text="Select an item to see its stats. Double-click for full stats (and where to get it). "
                                "Tick Grab to pick it up whenever you see it.",
                                style="Muted.TLabel", wraplength=820, justify="left")
        self.detail.pack(anchor="w", pady=6)
        self.rows = {}
        self.run()

    def char(self):
        w = self.app.s.world
        cls = next((k for k, v in w.classes.items() if v["Name"] == self.cls.get()), 0)
        race = next((k for k, v in w.races.items() if v["Name"] == self.race.get()), 0)

        def num(v):
            try:
                return int(v.get())
            except (ValueError, tk.TclError):
                return 0
        return G.Char(cls=cls, race=race, level=num(self.level), align=self.align.get(),
                      strength=num(self.strength), include_limited=self.limited.get())

    def read_inv(self):
        if self.app.s.telnet.connected:
            self.app.s.send("i")
            self.after(2500, self.run)

    def _dbl(self, e):
        iid = self.tree.identify_row(e.y)
        g = self.rows.get(iid)
        if g and self.tree.identify_region(e.x, e.y) != "heading":
            item_window(self.app, g)
            return "break"

    def _mine_toggle(self):
        if self.mine.get() and self.app.s.telnet.connected:
            self.app.s.send("i")
            self.after(2500, self.run)
        self.run()

    def _run_mine(self):
        """What I'm wearing now, slot by slot, with AC/DR (and the chosen goal) per piece."""
        w = self.app.s.world
        worn = G.worn_items(w, self.app.s.state.carrying)
        goal = G.GOALS[self.goal.get()]
        unit = self.goal.get().split(" (")[0]
        order = ["Weapon"] + G.SLOTS
        tac = sum(G.ac(g) for g in worn.values())
        tdr = sum(G.dr(g) for g in worn.values())
        tv = sum(G.score(g, goal) for g in worn.values())
        self.total.configure(text=(f"Wearing: AC {G.fmt(round(tac, 1))}  ·  DR {G.fmt(round(tdr, 1))}" +
                                   ("" if goal in ("ac", "dr", "acdr") else f"  ·  {unit} {G.fmt(round(tv, 1))}"))
                             if worn else "Nothing worn found — connect and it reads your inventory (i)")
        for slot in sorted(worn, key=lambda k: order.index(k) if k in order else 99):
            g = worn[slot]
            iid = self.tree.insert("", "end", text=g["name"],
                                   values=(self._grab_mark(g["name"]), slot, G.fmt(G.score(g, goal)),
                                           f"AC {G.fmt(G.ac(g))} / DR {G.fmt(G.dr(g))}", "",
                                           G.sources(w, g, 1)[0][0]), tags=("same",))
            self.rows[iid] = g

    def run(self):
        w = self.app.s.world
        if getattr(self, "mine", None) is not None and self.mine.get():
            self.tree.delete(*self.tree.get_children())
            self.rows = {}
            self.tree.heading("cur", text="AC / DR")
            return self._run_mine()
        self.tree.heading("cur", text="Wearing now")
        current = G.worn_items(w, self.app.s.state.carrying) if self.compare.get() else {}
        res = G.optimize(w, self.goal.get(), self.char(), current)
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        tot = sum(r.value for r in res)
        cur_tot = sum(r.current_value for r in res)
        unit = self.goal.get().split(" (")[0]
        self.total.configure(text=f"Best total {unit}: {G.fmt(round(tot, 1))}" +
                                  (f"   ·   wearing now {G.fmt(round(cur_tot, 1))}   ·   +{G.fmt(round(tot - cur_tot, 1))} available"
                                   if current else "   ·   (Read my inventory to compare with what you wear)"))
        for r in res:
            if not r.best and not r.current:
                continue
            gain = r.value - r.current_value
            src = G.sources(w, r.best, 1)[0][0] if r.best else ""
            name = r.best["name"] if r.best else "(nothing better)"
            iid = self.tree.insert("", "end", text=f"{r.slot}: {name}",
                                   values=(self._grab_mark(r.best["name"]) if r.best else "", r.slot, G.fmt(r.value),
                                           (f"{r.current['name']} ({G.fmt(r.current_value)})" if r.current else "—"),
                                           f"+{G.fmt(round(gain, 1))}" if gain > 0 else "—", src),
                                   tags=("up" if gain > 0 else "same",), open=False)
            self.rows[iid] = r.best
            for g, v in r.alts:
                aid = self.tree.insert(iid, "end", text=f"   {g['name']}", values=(self._grab_mark(g["name"]), G.slot_name(g), G.fmt(v), "", "",
                                                                                   G.sources(w, g, 1)[0][0]),
                                       tags=("alt",))
                self.rows[aid] = g

    def _grab_name(self, iid):
        g = self.rows.get(iid)
        return g["name"] if g else None

    def show_detail(self):
        sel = self.tree.selection()
        g = self.rows.get(sel[0]) if sel else None
        if not g:
            return
        w = self.app.s.world
        where = "; ".join(t for t, _r in G.sources(w, g, 6))
        self.detail.configure(text=f"{g['name']}: {G.describe(w, g)}\nGet it: {where}", style="TLabel")

    def goto_source(self):
        sel = self.tree.selection()
        g = self.rows.get(sel[0]) if sel else None
        if not g:
            return
        for _t, room in G.sources(self.app.s.world, g, 6):
            if room:
                self.app.goto_room(tuple(room))
                return
        self.app.add_log(f"No walkable source room known for {g['name']}.")


class WeaponPane(GrabTicks, ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        w = app.s.world
        if not getattr(w, "gear", None):
            ttk.Label(self, text="Re-import this board's MME file to use the weapon calculator.",
                      style="Muted.TLabel").pack(anchor="w", pady=20)
            return
        st = app.s.state
        self.cls_names = ["Any class"] + [v["Name"] for k, v in sorted(w.classes.items())]
        self.race_names = ["Any race"] + [v["Name"] for k, v in sorted(w.races.items())]
        self.cls = tk.StringVar(value=st.char_class if st.char_class in self.cls_names else
                                (app.s.settings.char_class if app.s.settings.char_class in self.cls_names else "Any class"))
        self.race = tk.StringVar(value=st.race if st.race in self.race_names else "Any race")
        enc = st.enc[3] if st.enc else 33
        self.v = {k: tk.StringVar(value=str(v)) for k, v in (
            ("level", st.level or app.s.settings.char_level or 30), ("agility", st.agility or 60),
            ("strength", st.strength or 60), ("encum", enc), ("accuracy", 0), ("crit", 0))}
        self.mon = tk.StringVar(value="")
        self.limited = tk.BooleanVar(value=True)
        r0 = ttk.Frame(self)
        r0.pack(fill="x")
        ttk.Label(r0, text="Class").pack(side="left")
        ttk.Combobox(r0, textvariable=self.cls, values=self.cls_names, width=12, state="readonly").pack(side="left", padx=(4, 10))
        ttk.Label(r0, text="Race").pack(side="left")
        ttk.Combobox(r0, textvariable=self.race, values=self.race_names, width=11, state="readonly").pack(side="left", padx=(4, 10))
        for key, lbl in (("level", "Level"), ("agility", "Agility"), ("strength", "Str"), ("encum", "Enc %")):
            ttk.Label(r0, text=lbl).pack(side="left")
            ttk.Spinbox(r0, from_=0, to=999, textvariable=self.v[key], width=5).pack(side="left", padx=(4, 8))
        r1 = ttk.Frame(self)
        r1.pack(fill="x", pady=6)
        ttk.Label(r1, text="Against").pack(side="left")
        names = sorted({m["name"] for m in w.monsters.values() if m.get("in_game") and m["exp"] > 0})
        cb = ttk.Combobox(r1, textvariable=self.mon, values=[""] + names, width=24)
        cb.pack(side="left", padx=(4, 10))
        ttk.Label(r1, text="Your accuracy").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=999, textvariable=self.v["accuracy"], width=5).pack(side="left", padx=(4, 8))
        ttk.Label(r1, text="Crit % from gear").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=99, textvariable=self.v["crit"], width=4).pack(side="left", padx=(4, 8))
        ttk.Checkbutton(r1, text="Include limited", variable=self.limited).pack(side="left", padx=6)
        ttk.Button(r1, text="Calculate", style="Accent.TButton", command=self.run).pack(side="left", padx=6)
        ttk.Label(self, text="Blank target = damage before the mob's armour. Pick a mob and enter your accuracy to "
                             "include its AC, DR and dodge.", style="Muted.TLabel").pack(anchor="w")
        self.head = ttk.Label(self, text="", style="Head.TLabel")
        self.head.pack(anchor="w", pady=(8, 4))
        cols = ("grab", "type", "dmg", "swings", "hit", "crit", "hitpct", "str", "where")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", height=15)
        self.tree.heading("#0", text="Weapon")
        self.tree.column("#0", width=200)
        for c, t, wd in (("type", "Type", 70), ("dmg", "Dmg/round", 75), ("swings", "Swings", 55),
                         ("hit", "Avg hit", 55), ("crit", "Crit %", 50), ("hitpct", "Hit %", 50),
                         ("str", "Str", 40), ("where", "Where to get it", 240)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wd, anchor="w" if c in ("type", "where") else "e")
        self.tree.tag_configure("cur", foreground="#e6b450")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.detail_show())
        self.tree.bind("<Double-1>", lambda e: (lambda sw: sw and item_window(self.app, sw.weapon))(
            self.rows.get(self.tree.identify_row(e.y))))
        self._grab_init(self.tree, self)
        self.detail = ttk.Label(self, text="", style="Muted.TLabel", wraplength=860, justify="left")
        self.detail.pack(anchor="w", pady=6)
        self.rows = {}
        self.run()

    def _num(self, k):
        try:
            return int(self.v[k].get())
        except (ValueError, tk.TclError):
            return 0

    def run(self):
        w = self.app.s.world
        cls = next((k for k, v in w.classes.items() if v["Name"] == self.cls.get()), 0)
        race = next((k for k, v in w.races.items() if v["Name"] == self.race.get()), 0)
        combat = int(w.classes.get(cls, {}).get("CombatLVL") or 3) - 2 if cls else 3
        f = G.Fighter(level=self._num("level"), combat=combat, agility=self._num("agility"),
                      strength=self._num("strength"), encum_pct=self._num("encum"),
                      accuracy=self._num("accuracy"), crit=self._num("crit"))
        mon = w.monster_names.get(self.mon.get().strip().lower()) if self.mon.get().strip() else None
        res = G.best_weapons(w, G.Char(cls=cls, race=race, level=self._num("level"),
                                       include_limited=self.limited.get()), f, mon)
        wielded = ""
        from .gamestate import wielded as _wielded
        if _wielded(self.app.s.state.carrying or ""):
            wielded = _wielded(self.app.s.state.carrying or "").lower()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for sw in res:
            g = sw.weapon
            src = G.sources(w, g, 1)[0][0]
            tags = ("cur",) if g["name"].lower() == wielded else ()
            iid = self.tree.insert("", "end", text=("★ " if tags else "") + g["name"], tags=tags,
                                   values=(self._grab_mark(g["name"]), G.WEAPON_TYPES.get(int(g.get("WeaponType") or 0), "?"), sw.round_dmg,
                                           f"{sw.swings:.1f}", sw.avg_hit, sw.crit_pct,
                                           f"{sw.hit_pct}%", g.get("StrReq") or "", src))
            self.rows[iid] = sw
        best = res[0] if res else None
        if best:
            cur = next((s for s in res if s.weapon["name"].lower() == wielded), None)
            extra = f"   ·   wielding {cur.weapon['name']}: {cur.round_dmg}" if cur else ""
            self.head.configure(text=f"Best: {best.weapon['name']} — {best.round_dmg} damage/round"
                                     + (f" vs {mon['name']}" if mon else "") + extra)
        else:
            self.head.configure(text="No usable weapons found for these settings.")

    def _grab_name(self, iid):
        sw = self.rows.get(iid)
        return sw.weapon["name"] if sw else None

    def detail_show(self):
        sel = self.tree.selection()
        sw = self.rows.get(sel[0]) if sel else None
        if not sw:
            return
        w = self.app.s.world
        g = sw.weapon
        where = "; ".join(t for t, _r in G.sources(w, g, 6))
        hands = "two-handed (no shield)" if int(g.get("WeaponType") or 0) in (1, 3) else "one-handed"
        self.detail.configure(style="TLabel", text=(
            f"{g['name']}: {g.get('Min')}-{g.get('Max')} damage, speed {g.get('Speed')}, accuracy {g.get('Accy') or 0:+}, "
            f"{hands}; {sw.energy} energy per swing → {sw.swings:.1f} swings; avg hit {sw.avg_hit}, avg crit {sw.avg_crit} "
            f"at {sw.crit_pct}%" + (f"; {sw.note}" if sw.note else "") + f"\nGet it: {where}"))

    def goto_source(self):
        sel = self.tree.selection()
        sw = self.rows.get(sel[0]) if sel else None
        if not sw:
            return
        for _t, room in G.sources(self.app.s.world, sw.weapon, 6):
            if room:
                self.app.goto_room(tuple(room))
                return
        self.app.add_log(f"No walkable source room known for {sw.weapon['name']}.")


class CalcWindowPane(ttk.Frame):
    """Inventory calculator window: Armour and Weapons pages."""

    def __init__(self, master, app):
        super().__init__(master)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.armour = CalcPane(nb, app)
        self.weapons = WeaponPane(nb, app)
        nb.add(self.armour, text="Armour")
        nb.add(self.weapons, text="Weapons")
        self.nb = nb


# ----------------------------------------------------------------- party
class PartyPane(ttk.Frame):
    """MegaMUD's little party box: everyone's health and mana at a glance.
    Kept fresh by the bot's 'par' check (Settings → Combat: party check every N s)."""
    BAR_W = 120

    def __init__(self, master, app, docked=False):
        super().__init__(master, padding=8)
        self.app = app
        self.docked = docked
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.on_top = tk.BooleanVar(value=not docked)
        if not docked:
            ttk.Checkbutton(top, text="Always on top", variable=self.on_top, command=self._top).pack(side="left")
        else:
            ttk.Button(top, text="⧉ Pop out", command=app.open_party).pack(side="left")
        if not docked:
            ttk.Button(top, text="✕", width=2, command=lambda: self.winfo_toplevel().destroy()).pack(side="right")
        ttk.Button(top, text="Refresh", command=lambda: app.s.send("par") if app.s.telnet.connected else None
                   ).pack(side="right", padx=(0, 4))
        if not docked:
            grip = tk.Label(self, text="◢", background=BG, foreground=MUTED, cursor="bottom_right_corner", font=("Segoe UI", 9))
            grip.place(relx=1.0, rely=1.0, anchor="se")
            self._grip_w = grip
            grip.bind("<ButtonPress-1>", self._grip_start)
            grip.bind("<B1-Motion>", self._grip_move)
            # no big title bar: drag the box by its top row or the bars
            self.after(30, self._borderless)
            for w in (top, self):
                w.bind("<ButtonPress-1>", self._drag_start, add="+")
                w.bind("<B1-Motion>", self._drag_move, add="+")
        self.cv = tk.Canvas(self, background=BG, highlightthickness=0, height=120)
        self.cv.pack(fill="both", expand=True, pady=(6, 0))
        self.foot = ttk.Label(self, text="", style="Muted.TLabel", wraplength=360)
        self.foot.pack(anchor="w")
        self._seq = None
        self.after(50, self._top)
        self.refresh()

    def _borderless(self):
        tl = self.winfo_toplevel()
        try:
            tl.overrideredirect(True)
            tl.attributes("-topmost", bool(self.on_top.get()))
        except tk.TclError:
            pass
        self.cv.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.cv.bind("<B1-Motion>", self._drag_move, add="+")

    def _grip_start(self, e):
        tl = self.winfo_toplevel()
        self._grip = (e.x_root, e.y_root, tl.winfo_width(), tl.winfo_height())
        return "break"

    def _grip_move(self, e):
        g = getattr(self, "_grip", None)
        if g:
            self._user_sized = True
            w, h = max(220, g[2] + e.x_root - g[0]), max(110, g[3] + e.y_root - g[1])
            self.winfo_toplevel().geometry(f"{w}x{h}")
        return "break"

    def _drag_start(self, e):
        tl = self.winfo_toplevel()
        self._drag = (e.x_root - tl.winfo_x(), e.y_root - tl.winfo_y())

    def _drag_move(self, e):
        d = getattr(self, "_drag", None)
        if d:
            self.winfo_toplevel().geometry(f"+{e.x_root - d[0]}+{e.y_root - d[1]}")

    def _top(self):
        if self.docked:
            return                         # docked in the main window: never make the main window "on top"
        try:
            self.winfo_toplevel().attributes("-topmost", bool(self.on_top.get()))
        except tk.TclError:
            pass

    @staticmethod
    def _col(p):
        return "#2fbf71" if p >= 70 else AMBER if p >= 40 else "#ff5c5c"

    def refresh(self):
        if not self.winfo_exists():
            return
        st = self.app.s.state
        rows = []
        for name, info in st.party.items():
            rows.append((name, info.get("class", ""), info.get("hp", 0), info.get("ma", 0), info.get("rank", ""),
                         info.get("t", 0)))
        if not rows and st.max_hp:
            rows.append((self.app.s.settings.my_name or "You", st.char_class or "", int(st.hp_pct()),
                         int(st.ma_pct()) if st.max_ma else -1, "", time.time()))
        cv = self.cv
        cv.delete("all")
        cw = max(cv.winfo_width(), 200)
        try:
            self.foot.configure(wraplength=max(180, cw - 20))
            if getattr(self, "_grip_w", None):
                self._grip_w.lift()
        except tk.TclError:
            pass
        self.NAME_W = 110 if cw < 330 else 150
        self.BAR_W = max(40, int((cw - self.NAME_W - 16) / 2))
        y = 4
        cv.create_text(6, y, anchor="nw", text="Name", fill=MUTED, font=("Segoe UI", 8))
        cv.create_text(self.NAME_W, y, anchor="nw", text="Health", fill=MUTED, font=("Segoe UI", 8))
        cv.create_text(self.NAME_W + 10 + self.BAR_W, y, anchor="nw", text="Mana", fill=MUTED, font=("Segoe UI", 8))
        y += 16
        x = self.app.s.bot.x
        leader = x.leader() or (self.app.s.settings.my_name if x.leading() else None)
        waiting = {n.lower() for n in (x.waiting_on or [])}
        hold = self.app.s.remote.holding() if hasattr(self.app.s, "remote") else None
        if hold:
            waiting.add(hold.lower())          # they sent @wait
        try:
            mp_names = {n_.lower() for n_ in self.app.s.partysync.peers}
        except Exception:
            mp_names = set()
        mp_names.add((self.app.s.settings.my_name or "").lower())
        for name, cls, hp, ma, rank, _t in rows:
            col = AMBER if name.lower() in waiting else TEXT
            label = name + ("  ★" if leader and name.lower() == leader.lower() else "")
            nid = cv.create_text(6, y + 1, anchor="nw", text=label, fill=col, font=("Segoe UI", 10, "bold"))
            if name.split()[0].lower() in mp_names:
                # runs MudPilot (party sync heard from them, or it's you): a small green check after the name
                bb = cv.bbox(nid)
                if bb:
                    cv.create_text(bb[2] + 4, y + 1, anchor="nw", text="✓", fill="#2fbf71",
                                   font=("Segoe UI", 10, "bold"))
            try:
                conds = x.care.conditions(name)
            except Exception:
                conds = []
            if name.lower() == (self.app.s.settings.my_name or "").lower():
                conds = [c.capitalize() for c in x.ailments if c != "confused"] + conds
            bad = [c for c in conds if c not in ("Meditating", "Resting")]
            cv.create_text(6, y + 16, anchor="nw", text=f"{cls}{'  · ' + rank if rank else ''}"
                           + ("  · waiting" if name.lower() in waiting else "")
                           + ("  · " + ", ".join(conds) if conds else ""),
                           fill="#ff5c5c" if bad else AMBER if name.lower() in waiting else MUTED,
                           font=("Segoe UI", 8))
            for x0, pct in ((self.NAME_W, hp), (self.NAME_W + 10 + self.BAR_W, ma)):
                cv.create_rectangle(x0, y + 4, x0 + self.BAR_W, y + 20, fill=GRID, outline="")
                if pct is not None and pct >= 0:
                    w = int(self.BAR_W * max(0, min(pct, 100)) / 100)
                    cv.create_rectangle(x0, y + 4, x0 + w, y + 20,
                                        fill=self._col(pct) if x0 == self.NAME_W else "#3d7eff", outline="")
                    cv.create_text(x0 + self.BAR_W / 2, y + 12, text=f"{pct}%", fill=TEXT, font=("Segoe UI", 8, "bold"))
                else:
                    cv.create_text(x0 + self.BAR_W / 2, y + 12, text="—", fill=MUTED, font=("Segoe UI", 8))
            y += 36
        cv.configure(height=max(y, 60))
        if not self.docked and not getattr(self, "_user_sized", False):
            # fit the window to the party: two people = a small box
            tl = self.winfo_toplevel()
            self.update_idletasks()
            want = y + 54 + max(18, self.foot.winfo_reqheight())
            if abs(tl.winfo_height() - want) > 4:
                tl.geometry(f"{max(tl.winfo_width(), 300)}x{want}")
        if st.party:
            age = int(time.time() - max(r[5] for r in rows))
            # whose window this is: several MudPilots' party windows can sit on one screen (Dan, 2026-11-01: Miserable's
            # sat over Buddy's and looked like Buddy's party)
            me_ = self.app.s.settings.my_name or ""
            txt = (f"{me_}'s party · " if me_ else "") + f"{len(rows)} in party · updated {age}s ago" + \
                (f" · ★ = leader ({leader})" if leader else "")
            if x.waiting_on:
                txt = f"Leader waiting on: {', '.join(x.waiting_on)}  ·  " + txt
            self.foot.configure(text=txt)
        else:
            self.foot.configure(text="Not in a party (or 'par' not seen yet) — showing you")
        bs = self.app.s.bot.status or ""
        if bs.startswith(("Waiting", "Holding", "Resting", "Meditating", "Leader", "Party", "Stopped before")):
            self.foot.configure(text=f"Now: {bs}\n" + self.foot.cget("text"))
        self.after(1000, self.refresh)


# ----------------------------------------------------------------- history
class HistoryPane(ttk.Frame):
    """Exp/hr by day (bar chart + table) and, for the day you pick, by loop."""

    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        ttk.Label(self, text="Exp/hr per day — online (what you actually made) and while on a loop",
                  style="Head.TLabel").pack(anchor="w")
        self.chart = tk.Canvas(self, height=170, background=PANEL, highlightthickness=0)
        self.chart.pack(fill="x", pady=(4, 8))
        self.chart.bind("<Configure>", lambda e: self.draw())
        cols = ("on", "hunt", "exp", "eph", "ehh", "kills", "deaths", "rests", "rest", "lag", "drops", "best")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", height=9)
        self.tree.heading("#0", text="Day")
        self.tree.column("#0", width=95)
        for c, t, w in (("on", "Online", 62), ("hunt", "Looping", 62), ("exp", "Exp", 85), ("eph", "Exp/hr", 70),
                        ("ehh", "…looping", 70), ("kills", "Kills", 55), ("deaths", "Deaths", 50), ("rests", "Rests", 50),
                        ("rest", "Resting", 60), ("lag", "Lag", 45), ("drops", "Drops", 45), ("best", "Best loop", 150)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c == "best" else "e")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_loops())
        ttk.Label(self, text="Loops that day", style="Head.TLabel").pack(anchor="w", pady=(8, 2))
        self.loops = ttk.Treeview(self, columns=("secs", "exp", "eph"), show="tree headings", height=4)
        self.loops.heading("#0", text="Loop")
        self.loops.column("#0", width=260)
        for c, t in (("secs", "Time"), ("exp", "Exp"), ("eph", "Exp/hr")):
            self.loops.heading(c, text=t)
            self.loops.column(c, width=90, anchor="e")
        self.loops.pack(fill="x")
        self.refresh()

    @staticmethod
    def _hrs(x):
        return fmt_dur(x) if x >= 60 else f"{x:.0f}s"

    def refresh(self):
        h = self.app.s.history
        self.days = h.days()
        self.tree.delete(*self.tree.get_children())
        for day, d in self.days:
            on, hunt = d.get("on", 0), d.get("hunt", 0)
            loops = d.get("loops") or {}
            best = max(loops.items(), key=lambda kv: kv[1]["exp"] / max(kv[1]["secs"], 1), default=None)
            best_txt = (f"{best[0]} ({best[1]['exp'] / max(best[1]['secs'], 1) * 3.6:,.0f}k/hr)"
                        if best and best[1]["secs"] > 300 else "")
            self.tree.insert("", "end", iid=day, text=time.strftime("%a %b %d", time.strptime(day, "%Y-%m-%d")),
                             values=(self._hrs(on), self._hrs(hunt), f"{d.get('exp', 0):,}",
                                     f"{d.get('exp', 0) / max(on, 1) * 3.6:,.0f}k" if on > 300 else "—",
                                     f"{d.get('exp', 0) / max(hunt, 1) * 3.6:,.0f}k" if hunt > 300 else "—",
                                     d.get("kills", 0), d.get("deaths", 0), d.get("rests", 0),
                                     f"{100 * d.get('rest', 0) / on:.0f}%" if on else "—",
                                     f"{d['lag_sum'] / d['lag_n']:.2f}" if d.get("lag_n") else "—",
                                     d.get("drops", 0), best_txt))
        if self.days:
            self.tree.selection_set(self.days[0][0])
        self.draw()

    def draw(self):
        c = self.chart
        c.delete("all")
        days = list(reversed(getattr(self, "days", [])[:30]))
        W, H = max(c.winfo_width(), 300), 170
        if not days:
            c.create_text(W / 2, H / 2, text="No history yet — it fills in as you play.", fill=MUTED)
            return
        vals = [(day, d.get("exp", 0) / max(d.get("on", 0), 1) * 3600 if d.get("on", 0) > 300 else 0,
                 d.get("exp", 0) / max(d.get("hunt", 0), 1) * 3600 if d.get("hunt", 0) > 300 else 0) for day, d in days]
        top = max(max(v[1], v[2]) for v in vals) or 1
        n = len(vals)
        bw = min(34, (W - 40) / n)
        for i, (day, on, hunt) in enumerate(vals):
            x = 30 + i * bw
            h1 = (H - 40) * hunt / top
            h2 = (H - 40) * on / top
            c.create_rectangle(x + 2, H - 22 - h1, x + bw - 2, H - 22, fill="#24405e", outline="")
            c.create_rectangle(x + 6, H - 22 - h2, x + bw - 6, H - 22, fill=ACCENT, outline="")
            if on:
                c.create_text(x + bw / 2, H - 26 - max(h1, h2), text=f"{on / 1e6:.2f}M", fill=TEXT, font=("Segoe UI", 7))
            c.create_text(x + bw / 2, H - 10, text=day[8:], fill=MUTED, font=("Segoe UI", 7))
        c.create_rectangle(W - 190, 6, W - 180, 16, fill=ACCENT, outline="")
        c.create_text(W - 176, 11, anchor="w", text="online", fill=MUTED, font=("Segoe UI", 8))
        c.create_rectangle(W - 120, 6, W - 110, 16, fill="#24405e", outline="")
        c.create_text(W - 106, 11, anchor="w", text="while looping", fill=MUTED, font=("Segoe UI", 8))

    def show_loops(self):
        sel = self.tree.selection()
        d = dict(self.days).get(sel[0]) if sel else None
        self.loops.delete(*self.loops.get_children())
        for t, lp in sorted((d or {}).get("loops", {}).items(), key=lambda kv: -kv[1]["exp"]):
            self.loops.insert("", "end", text=t, values=(self._hrs(lp["secs"]), f"{lp['exp']:,}",
                                                         f"{lp['exp'] / max(lp['secs'], 1) * 3.6:,.0f}k" if lp["secs"] > 120 else "—"))


# ----------------------------------------------------------------- timeline
TL_COLORS = {"fighting": "#ff6b6b", "resting": "#6d8cff", "walking": ACCENT, "waiting": AMBER,
             "idle": "#3a4352", "offline": "#1c2129"}
TL_EVENT = {"death": ("✕", "#ff4d4d"), "drop": ("⚡", "#c9d1dc"), "hangup": ("☎", "#ff9a3c"),
            "level": ("▲", "#ffd23f"), "boss": ("★", "#e6b450")}


class TimelinePane(ttk.Frame):
    """One strip per hour: what the bot was doing, minute by minute. Click anywhere to see the screen then."""
    ROW, LEFT = 26, 64

    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Where the time went — click a moment to see the screen", style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Refresh", command=self.draw).pack(side="right")
        lg = ttk.Frame(self)
        lg.pack(fill="x", pady=(4, 4))
        for k, c in TL_COLORS.items():
            tk.Canvas(lg, width=12, height=12, background=c, highlightthickness=0).pack(side="left", padx=(0, 3))
            ttk.Label(lg, text=k, style="Muted.TLabel").pack(side="left", padx=(0, 10))
        for k, (sym, c) in TL_EVENT.items():
            ttk.Label(lg, text=f"{sym} {k}", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.summary = ttk.Label(self, text="", style="Muted.TLabel")
        self.summary.pack(anchor="w")
        self.cv = tk.Canvas(self, height=300, background=PANEL, highlightthickness=0)
        self.cv.pack(fill="both", expand=True, pady=(4, 6))
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Button-1>", self.click)
        self.txt = tk.Text(self, height=12, background="#0b0d10", foreground=TEXT, insertbackground=TEXT,
                           font=("Consolas", 9), wrap="none", relief="flat")
        self.txt.pack(fill="both", expand=True)
        self.txt.insert("end", "Click the timeline above.")
        self.txt.configure(state="disabled")
        self.draw()

    def hours(self):
        tl = self.app.s.timeline
        if not tl.segs:
            return []
        first = int(tl.segs[0][0] // 3600) * 3600
        last = int(time.time() // 3600) * 3600
        return list(range(int(last), int(first) - 1, -3600))[:24]

    def draw(self):
        cv, tl = self.cv, self.app.s.timeline
        cv.delete("all")
        W = max(cv.winfo_width(), 400)
        hrs = self.hours()
        if not hrs:
            cv.create_text(W / 2, 40, text="Nothing yet — it records as you play.", fill=MUTED)
            return
        tot = {}
        for a, b, k in tl.segs:
            tot[k] = tot.get(k, 0) + (b - a)
        allt = sum(v for k, v in tot.items() if k != "offline") or 1
        self.summary.configure(text="  ·  ".join(f"{k} {100 * v / allt:.0f}%" for k, v in
                                                sorted(tot.items(), key=lambda kv: -kv[1]) if k != "offline"))
        cv.configure(scrollregion=(0, 0, W, len(hrs) * self.ROW + 10))
        span = W - self.LEFT - 10
        for i, h in enumerate(hrs):
            y = 6 + i * self.ROW
            cv.create_text(self.LEFT - 8, y + 9, anchor="e", fill=MUTED, font=("Segoe UI", 8),
                           text=time.strftime("%a %H:00", time.localtime(h)))
            cv.create_rectangle(self.LEFT, y, self.LEFT + span, y + 18, fill="#0f1318", outline="")
            for a, b, k in tl.segs:
                if b < h or a > h + 3600:
                    continue
                x1 = self.LEFT + span * (max(a, h) - h) / 3600
                x2 = self.LEFT + span * (min(b, h + 3600) - h) / 3600
                cv.create_rectangle(x1, y, max(x2, x1 + 1), y + 18, fill=TL_COLORS.get(k, MUTED), outline="")
            for t, k, _x in tl.events:
                if h <= t < h + 3600 and k in TL_EVENT:
                    sym, c = TL_EVENT[k]
                    cv.create_text(self.LEFT + span * (t - h) / 3600, y + 9, text=sym, fill=c, font=("Segoe UI", 10, "bold"))
        self._hrs, self._span = hrs, span

    def click(self, e):
        hrs = getattr(self, "_hrs", [])
        i = int((self.cv.canvasy(e.y) - 6) // self.ROW)
        if not (0 <= i < len(hrs)) or e.x < self.LEFT:
            return
        t = hrs[i] + 3600 * (e.x - self.LEFT) / self._span
        tl = self.app.s.timeline
        seg = next((k for a, b, k in tl.segs if a <= t <= b), "—")
        lines = tl.screen_around(t, 45, 45)
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", f"{time.strftime('%a %H:%M:%S', time.localtime(t))} — {seg}\n\n")
        if not lines:
            self.txt.insert("end", "(no screen kept for that moment — it keeps the last ~30,000 lines)")
        for tt, x in lines:
            self.txt.insert("end", f"{time.strftime('%H:%M:%S', time.localtime(tt))}  {x}\n")
        self.txt.configure(state="disabled")
        near = min(range(len(lines)), key=lambda j: abs(lines[j][0] - t)) if lines else 0
        self.txt.see(f"{near + 3}.0")


class DeathsPane(ttk.Frame):
    """Each death: HP over the last minute, who hit you for how much, and what might have saved it."""

    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        from .timeline import load_deaths
        self.deaths = load_deaths()
        left = ttk.Frame(self)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Deaths", style="Head.TLabel").pack(anchor="w")
        self.lb = tk.Listbox(left, width=26, background="#0f1318", foreground=TEXT, selectbackground="#24405e",
                             relief="flat", highlightthickness=0)
        self.lb.pack(fill="y", expand=True)
        for d in self.deaths:
            self.lb.insert("end", time.strftime("%a %b %d %H:%M", time.localtime(d["t"])) +
                           (f"  {d['room'][0]}/{d['room'][1]}" if d.get("room") else ""))
        self.lb.bind("<<ListboxSelect>>", lambda e: self.show())
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.head = ttk.Label(right, text="" if self.deaths else "No deaths recorded. Good.", style="Head.TLabel")
        self.head.pack(anchor="w")
        self.cv = tk.Canvas(right, height=160, background=PANEL, highlightthickness=0)
        self.cv.pack(fill="x", pady=4)
        self.tips = ttk.Label(right, text="", wraplength=640, justify="left")
        self.tips.pack(anchor="w", pady=(2, 6))
        self.txt = tk.Text(right, height=14, background="#0b0d10", foreground=TEXT, font=("Consolas", 9),
                           wrap="none", relief="flat")
        self.txt.pack(fill="both", expand=True)
        if self.deaths:
            self.lb.selection_set(0)
            self.after(50, self.show)

    def show(self):
        sel = self.lb.curselection()
        if not sel:
            return
        d = self.deaths[sel[0]]
        by = sorted((d.get("by") or {}).items(), key=lambda kv: -kv[1])
        self.head.configure(text=f"Died {time.strftime('%a %b %d %H:%M:%S', time.localtime(d['t']))}"
                                 + (f" — hits from {', '.join(f'{w} {n}' for w, n in by[:3])}" if by else ""))
        self.tips.configure(text="\n".join("• " + t for t in d.get("tips") or []))
        c = self.cv
        c.delete("all")
        c.update_idletasks()
        W, H = max(c.winfo_width(), 400), 160
        mx = d.get("max_hp") or 1
        pts = d.get("hp") or []
        c.create_text(6, 6, anchor="nw", text="HP, last 60 s", fill=MUTED, font=("Segoe UI", 8))
        if pts:
            xy = []
            for t, hp in pts:
                xy += [30 + (W - 40) * (t + 60) / 60, H - 15 - (H - 30) * max(0, hp) / mx]
            if len(xy) >= 4:
                c.create_line(*xy, fill="#5cff7a", width=2)
        for t, _w, n in d.get("hits") or []:
            x = 30 + (W - 40) * (t + 60) / 60
            c.create_line(x, H - 15, x, H - 15 - min(H - 30, (H - 30) * n / mx), fill="#ff6b6b")
        c.create_line(30, H - 15, W - 10, H - 15, fill=GRID)
        self.txt.delete("1.0", "end")
        for t, x in d.get("lines") or []:
            self.txt.insert("end", f"{t:6.1f}s  {x}\n")
        self.txt.see("end")


# ----------------------------------------------------------------- pMUD-style extras
class SchedulePane(ttk.Frame):
    """Window → Scheduled actions: log on/off, relog, go to, loop or a command, at a time or every N minutes."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        from .extrafeatures import ACTIONS
        self.app, self.s = app, app.s
        cols = ("on", "when", "action", "arg")
        self.t = ttk.Treeview(self, columns=cols, show="headings", height=8)
        for c, w, h in zip(cols, (40, 140, 110, 300), ("On", "When", "Do", "What")):
            self.t.heading(c, text=h)
            self.t.column(c, width=w)
        self.t.pack(fill="both", expand=True)
        f = ttk.Frame(self)
        f.pack(fill="x", pady=6)
        self.kind = tk.StringVar(value="at")
        ttk.Radiobutton(f, text="At", variable=self.kind, value="at").pack(side="left")
        self.at = tk.StringVar(value="06:00")
        ttk.Entry(f, textvariable=self.at, width=6).pack(side="left", padx=(2, 8))
        ttk.Radiobutton(f, text="Every", variable=self.kind, value="every").pack(side="left")
        self.every = tk.StringVar(value="60")
        ttk.Entry(f, textvariable=self.every, width=5).pack(side="left", padx=2)
        ttk.Label(f, text="min  do").pack(side="left", padx=(0, 4))
        self.act = tk.StringVar(value=ACTIONS[0])
        ttk.Combobox(f, textvariable=self.act, values=ACTIONS, state="readonly", width=9).pack(side="left")
        self.arg = tk.StringVar()
        ttk.Entry(f, textvariable=self.arg, width=24).pack(side="left", padx=4)
        ttk.Button(f, text="Add", style="Accent.TButton", command=self.add).pack(side="left")
        b = ttk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="On / off", command=self.toggle).pack(side="left")
        ttk.Button(b, text="Remove", command=self.remove).pack(side="left", padx=4)
        ttk.Label(self, text="Go to takes a map/room (10/297), loop takes part of a loop's name, command is sent as "
                             "typed. Times are this PC's clock. Skipped (and said in the Log) when it doesn't make "
                             "sense — e.g. log on while already on.", style="Muted.TLabel", wraplength=680,
                  justify="left").pack(anchor="w", pady=(6, 0))
        self.fill()

    def fill(self):
        self.t.delete(*self.t.get_children())
        for i, it in enumerate(self.s.settings.schedules or []):
            when = f"at {it['at']}" if it.get("at") else f"every {it.get('every')} min"
            self.t.insert("", "end", iid=str(i), values=("☑" if it.get("on", True) else "☐", when,
                                                         it.get("action"), it.get("arg", "")))

    def _save(self, items):
        self.s.settings.schedules = items
        self.s.settings.save()
        self.fill()

    def add(self):
        it = {"action": self.act.get(), "arg": self.arg.get().strip(), "on": True}
        if self.kind.get() == "at":
            if not re.match(r"^\d{1,2}:\d{2}$", self.at.get().strip()):
                return messagebox.showinfo("Scheduled actions", "Time as HH:MM, e.g. 06:30", parent=self)
            it["at"] = self.at.get().strip()
        else:
            try:
                it["every"] = max(1, float(self.every.get()))
            except ValueError:
                return
        self._save(list(self.s.settings.schedules or []) + [it])

    def _sel(self):
        s = self.t.selection()
        return int(s[0]) if s else None

    def toggle(self):
        i = self._sel()
        if i is None:
            return
        items = [dict(x) for x in self.s.settings.schedules or []]
        items[i]["on"] = not items[i].get("on", True)
        self._save(items)

    def remove(self):
        i = self._sel()
        if i is None:
            return
        items = list(self.s.settings.schedules or [])
        del items[i]
        self._save(items)


class LeaderboardPane(ttk.Frame):
    """Window → XP leaderboard: 'top 200' samples, everyone's exp/hr over the last 48 h."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        app._check(top, "leaderboard_on", "Send 'top 200' every").pack(side="left")
        ttk.Spinbox(top, from_=10, to=720, width=5, textvariable=app._var("leaderboard_mins")).pack(side="left", padx=4)
        ttk.Label(top, text="min (not in fights)").pack(side="left")
        ttk.Button(top, text="Ask now", command=lambda: self.s.send("top 200")).pack(side="right")
        cols = ("name", "exp", "rate")
        self.t = ttk.Treeview(self, columns=cols, show="headings")
        for c, w, h in zip(cols, (160, 140, 140), ("Player", "Experience", "Exp/hr")):
            self.t.heading(c, text=h)
            self.t.column(c, width=w, anchor="w" if c == "name" else "e")
        self.t.pack(fill="both", expand=True, pady=6)
        self.after(500, self.fill)

    def fill(self):
        if not self.winfo_exists():
            return
        self.t.delete(*self.t.get_children())
        for name, exp, rate in self.s.leaderboard.rates()[:200]:
            self.t.insert("", "end", values=(name, f"{exp:,}", f"{rate:,.0f}" if rate else "—"))
        self.after(30000, self.fill)


class QuestsPane(ttk.Frame):
    """Window → Quests: the board's quest pages, with lines for your class picked out."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="Read them from the game", style="Accent.TButton",
                   command=self.fetch).pack(side="left")
        ttk.Label(top, text="Find").pack(side="left", padx=(12, 4))
        self.q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.q, width=28)
        e.pack(side="left")
        self.q.trace_add("write", lambda *a: self.fill())
        self.txt = tk.Text(self, background="#0f1318", foreground="#e0e6ef", borderwidth=0, wrap="word",
                           font=("Consolas", 10))
        self.txt.tag_configure("head", foreground="#ffd166")
        self.txt.tag_configure("me", foreground="#5cff7a")
        self.txt.tag_configure("hit", background="#5a4a00")
        self.txt.pack(fill="both", expand=True, pady=6)
        ttk.Label(self, text="Sends ? questlist (1–3) and ? questflags (1–3) and keeps what the board says. Green = "
                             "mentions your class.", style="Muted.TLabel").pack(anchor="w")
        self.fill()

    def fetch(self):
        if not self.s.telnet.connected:
            return
        self.s.quests.fetch_all()
        self.s.send("abil", from_bot=True)             # your quest flags (granted abilities)
        self.after(8000, self.fill)

    def _mme_quests(self, q):
        """MME's quest steps (who raises which quest flag), with where you're at and what's next."""
        w, st = self.s.world, self.s.state
        steps = getattr(w, "quest_steps", {}) or {}
        if not steps:
            return
        self.txt.insert("end", "Quest flags (from MME — your value from the last 'abil')\n", ("head",))
        names = getattr(st, "abil_names", {}) or {}
        for ab in sorted(steps):
            cur = st.abil_rows.get(("granted", ab)) or st.abil_rows.get(("total", ab))
            have = cur[0] if cur else None
            top = max((x["value"] for x in steps[ab] if not x["add"]), default=0)
            nm = names.get(ab) or f"ability {ab}"
            hint = w.quest_hint(ab, top, have or 0) if (have or 0) < top else "done"
            line = f"  {nm}({ab}): {have if have is not None else '?'} / {top} — {hint}"
            if q and q not in line.lower():
                continue
            self.txt.insert("end", line + "\n", ("me",) if have and have >= top else ())
        self.txt.insert("end", "\n")

    def fill(self):
        self.txt.delete("1.0", "end")
        q = self.q.get().strip().lower()
        self._mme_quests(q)
        pages = self.s.quests.pages
        if not pages:
            self.txt.insert("end", "Nothing read yet — press 'Read them from the game' while you're in the realm.")
            return
        for cmd, pg in pages.items():
            self.txt.insert("end", f"{cmd}\n", ("head",))
            for line in pg.get("lines") or []:
                if q and q not in line.lower():
                    continue
                tags = ("me",) if self.s.quests.for_me(line) else ()
                self.txt.insert("end", line + "\n", tags)
            self.txt.insert("end", "\n")
