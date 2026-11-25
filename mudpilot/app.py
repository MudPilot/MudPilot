"""MudPilot main window (Tkinter)."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from . import config
from .ansi import COLORS
from .extras import room_text
from .mapview import MapView, MapSearch
from .megamud_files import find_mp_files, path_from_route
from .session import Session
from .spells import calc
from .windows import ChatPane, StatsPane, ExpChartPane, CalcPane, CalcWindowPane, PartyPane, HistoryPane, \
    TimelinePane, DeathsPane, SchedulePane, LeaderboardPane, QuestsPane, popout
from .worlddb import WorldDB, DIR_WORDS

FG = {  # (normal, bold) colours for ANSI 0-7
    0: ("#3b3b3b", "#7f7f7f"), 1: ("#c23b3b", "#ff5c5c"), 2: ("#2fa84f", "#5cff7a"),
    3: ("#c8a23a", "#ffe35c"), 4: ("#3d5fd6", "#6d8cff"), 5: ("#b43fb4", "#ff6bff"),
    6: ("#2fa8a8", "#5cffff"), 7: ("#c9c9c9", "#ffffff"), None: ("#c9c9c9", "#ffffff"),
}
BG = "#0b0d10"
PANEL = "#151a21"
# dull window colours (Dan: no bright reds or yellows — browns, tans, dull greens); auto picks one per data folder
WINDOW_COLOURS = [("tan", "#8a7356"), ("teal", "#4f6b68"), ("olive", "#5f6b3a"), ("brown", "#6b4f3a"),
                  ("slate", "#4f5d6b"), ("plum", "#6b5266"), ("sage", "#5d7360"), ("khaki", "#7a7448"),
                  ("rust", "#7a5340"), ("stone", "#6a6560")]
TEXT = "#e0e6ef"
MUTED = "#8a94a6"
ACCENT = "#2fbf71"
QUICK_BUTTONS = (
    ("auto_combat", "Combat", "Fight mobs in range"), ("auto_preattack", "PreAttack", "Cast the pre-attack spell first"),
    ("auto_nuke", "Nuke", "Area attack spells (from the 'at least N monsters' on Settings → Combat)"), ("auto_heal", "Heal", "Heal spell below the heal %"),
    ("auto_rest", "Rest", "Rest / meditate below the rest %"), ("auto_bless", "Bless", "Keep bless spells up"),
    ("auto_light", "Light", "Light up dark rooms (Health tab: light command)"),
    ("loot_cash", "Cash", "Pick up coins"), ("auto_loot", "Get", "Pick up the items on the Loot tab"),
    ("eco_travel", "Eco", "Travelling somewhere (Go to / a path that isn't a loop): walk past small fry that can't "
                          "hurt you; still fight anything worth the exp or that hits hard"),
    ("auto_sneak", "Sneak", "Sneak before each step"), ("auto_hide", "Hide", "Hide while resting"),
    ("auto_search", "Search", "Search each room once for hidden gold and items (hidden exits on the way are always searched)"),
    ("look_on_sound", "Listen", "Look toward movement you hear (once per direction every few seconds)"),
    ("hangup_on_pvp", "PvP", "Hang up the moment a player attacks you"),
    ("hangup_on_player", "Users", "Hang up when ANY player shows up (normally off: right-click a name → "
                                  "Enemy to hang up on just them)"),
    ("no_hang", "NoHang", "NoHang: never hang up on my own — overrides PvP, low HP, enemies and message rules "
                          "(for a boss or a corpse run). Alt+H and the Hang up button still work."),
    ("no_wait", "NoWait", "NoWait: ignore @wait and don't stop for hurt party members — for timed lairs like "
                          "pyramid level 1. Dangerous: nobody gets to rest"),
    ("hands_off", "Hands off", "Hands off: switch everything automatic off — no fighting, walking, spells, resting, "
                               "looting or party replies. Low-HP / PvP hang-ups still work"),
)
MODE_DEFAULT_SKIP = ("no_hang", "no_wait", "hands_off")
SETTINGS_TABS = ("General", "BBS", "Health", "Spells", "Combat", "Attack spells", "Bless", "Loot", "Party", "PvP", "Responses",
                 "Talk", "Phone alerts", "Auto-roam", "Events", "Other")


def split_commands(cmd: str, sp: str = ";") -> list:
    """MegaMUD-style: 'e;mist;.@do sand;simp dragon' → four commands. ';;' types a real ';'.
    ^M inside a command (e.g. '.@do go portal^Me^M') is left alone — it's for the party to run."""
    if not sp or sp not in cmd:
        return [cmd]
    esc = "\x00"
    parts = cmd.replace(sp + sp, esc).split(sp)
    out = [p.replace(esc, sp).strip() for p in parts]
    return [p for p in out if p] or [""]


PERUSE_IID = "routine:peruse"       # the Peruse books row in the Loops list

class Tip:
    def __init__(self, w, text):
        self.w, self.text, self.tw = w, text, None
        w.bind("<Enter>", self.show)
        w.bind("<Leave>", self.hide)

    def show(self, _e=None):
        if self.tw:
            return
        x, y = self.w.winfo_rootx() + 10, self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tw = tk.Toplevel(self.w)
        self.tw.wm_overrideredirect(True)
        self.tw.geometry(f"+{x}+{y}")
        text = getattr(self.w, "_tiptext", None) or self.text
        tk.Label(self.tw, text=text, background="#2a3342", foreground=TEXT, font=("Segoe UI", 9),
                 padx=6, pady=3).pack()

    def hide(self, _e=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


KEYPAD = {"KP_8": "n", "KP_2": "s", "KP_6": "e", "KP_4": "w", "KP_9": "ne", "KP_7": "nw",
          "KP_3": "se", "KP_1": "sw", "KP_Add": "u", "KP_Subtract": "d", "KP_5": ""}


def worn_list_of(carrying):
    from .gamestate import worn_list
    return worn_list(carrying)


class FlowRow(ttk.Frame):
    """Buttons that wrap onto another line when the panel is too narrow, instead of running off its edge (Dan,
    2026-11-03: on Revolution's screen the Bosses tab lost its buttons and the Track box off the side/bottom)."""

    def __init__(self, master, gap=4, **kw):
        super().__init__(master, **kw)
        self._items, self._gap, self._width = [], gap, 0
        self.bind("<Configure>", lambda ev: self._reflow(ev.width))

    def add(self, w):
        self._items.append(w)
        self.configure(height=max(i.winfo_reqheight() for i in self._items))
        self._reflow(self.winfo_width(), force=True)
        return w

    def _reflow(self, width, force=False):
        if width <= 1 or (width == self._width and not force):
            return
        self._width = width
        x = y = rowh = 0
        for w in self._items:
            need, h = w.winfo_reqwidth(), w.winfo_reqheight()
            if x and x + need > width:
                x, y, rowh = 0, y + rowh + self._gap, 0
            w.place(x=x, y=y)
            x += need + self._gap
            rowh = max(rowh, h)
        self.configure(height=y + rowh)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        from . import uilog as _uilog
        _uilog._wrap_menu()                  # menu picks are logged ("You: menu 'Goto'")
        from . import report as _report
        _report.install_error_hooks(root)
        root.title("MudPilot")
        self._set_icon(root)
        self._alert_title = None
        root.geometry("1360x820")
        try:
            from .windows import safe_geometry
            _g = safe_geometry(root, (self._early_settings().window_geom or {}).get("main"))
            if _g:
                root.geometry(_g)
            if (self._early_settings().window_geom or {}).get("main_zoomed"):
                root.after(200, lambda: root.state("zoomed") if os.name == "nt" else None)
        except Exception:
            pass
        root.minsize(980, 600)
        root.configure(background=PANEL)
        from .splash import progress
        self.s = Session()
        try:
            self.s.chat.load_recent()           # the chat box picks up where it left off (0.8.198)
        except Exception:
            pass
        self.s.tk_after = self.root.after          # bgplan: remote @goto plans on a worker thread too
        progress(78, "Building the window…")
        self.s.on_line = self.add_line
        self.s.on_banner = lambda text, kind: self.root.after(0, self.add_banner, text, kind)
        self.s.on_partial = self.set_partial
        self.s.on_log = self.add_log
        _uilog.install(self)                 # buttons, shortcut keys and settings you change are logged too
        self.s.on_clear = lambda: None
        self.s.on_sent = self.echo_sent
        self.s.on_settings_changed = lambda: self.root.after(0, self._sync_vars)
        self.history: list = []
        self.hist_i = 0
        self._map_seq = -1
        self._vars = {}
        self._save_after = None
        self.windows: dict = {}
        self.live_panes: list = []
        self._style()
        self._build()
        self._load_world_status()
        self.root.after(50, self._loop)
        st = self.s.settings
        self.exit_code = 0
        self.s.control.on_restart = lambda: self.root.after(0, self._restart_quit)
        if st.update_check:
            self.root.after(8000, lambda: self.check_updates(quiet=True))
        back = self.s.control.load_resume()
        # (0.8.201, bug hunt: hung up before the restart — wait out the stay-offline time; -1 = stay off)
        off = float((back or {}).get("hold_off") or 0)
        if (st.auto_connect or (back and back.get("connect"))) and st.host and off >= 0:
            self.root.after(800 + int(off * 1000), lambda: None if (off and self.s.telnet.connected) else
                            self._do_connect(st.host, st.port, st.username, None, st.save_password, auto=True))
        if getattr(st, "_first_run", False):
            self.root.after(1500, self.ask_board_first_run)     # (0.8.201, Dan: a fresh install asks its board)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind_all("<Control-Shift-D>", self.copy_diagnostics)
        self.root.bind_all("<Control-Shift-d>", self.copy_diagnostics)

    # ------------------------------------------------------------------ look
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=PANEL, foreground=TEXT, fieldbackground="#0f1318",
                     bordercolor="#2a3342", lightcolor=PANEL, darkcolor=PANEL, font=("Segoe UI", 9))
        st.configure("TNotebook", background=PANEL, borderwidth=0)
        st.configure("TNotebook.Tab", background="#1c232c", foreground=MUTED, padding=(8, 4))
        st.map("TNotebook.Tab", background=[("selected", "#243041")], foreground=[("selected", TEXT)])
        st.configure("TButton", background="#243041", foreground=TEXT, padding=(10, 4), borderwidth=0)
        st.map("TButton", background=[("active", "#2e3d52"), ("pressed", "#1a2230")])
        st.configure("Accent.TButton", background="#1f7a4a")
        st.map("Accent.TButton", background=[("active", "#26915a")])
        st.configure("Stop.TButton", background="#7a2a2a")
        st.map("Stop.TButton", background=[("active", "#933333")])
        st.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TLabel", background=PANEL, foreground=TEXT)
        st.configure("Muted.TLabel", foreground=MUTED)
        st.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))
        st.configure("TLabelframe", background=PANEL, foreground=TEXT, bordercolor="#2a3342")
        st.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
        st.configure("Treeview", background="#0f1318", fieldbackground="#0f1318", foreground=TEXT,
                     rowheight=22, borderwidth=0)
        st.configure("Treeview.Heading", background="#1c232c", foreground=MUTED)
        st.map("Treeview", background=[("selected", "#1f4f7a")])
        st.configure("TEntry", foreground=TEXT, insertcolor=TEXT)
        st.configure("TCombobox", foreground=TEXT, arrowcolor=TEXT, background="#243041")
        st.map("TCombobox", fieldbackground=[("readonly", "#0f1318")], foreground=[("readonly", TEXT)],
               selectbackground=[("readonly", "#0f1318")], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", "#0f1318")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        st.configure("TSpinbox", foreground=TEXT, arrowcolor=TEXT)
        st.configure("HP.Horizontal.TProgressbar", background="#2fbf71", troughcolor="#0f1318")
        st.configure("MA.Horizontal.TProgressbar", background="#3d7be0", troughcolor="#0f1318")

    # ------------------------------------------------------------------ layout
    def _build(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Open character…", command=self.open_character)
        fm.add_separator()
        fm.add_command(label="Connect…", command=self.connect_dialog)
        fm.add_command(label="Disconnect", command=lambda: self.s.telnet.connected and self.connect_toggle())
        fm.add_separator()
        fm.add_command(label="Import MME database (.mdb)…", command=self.import_mme)
        fm.add_command(label="Import MegaMUD paths (.mp files)…", command=self.import_mp_files)
        fm.add_command(label="Import MegaMUD paths folder…", command=self.import_mp_folder)
        fm.add_command(label="Import MegaMUD Rooms.md (Goto list)…", command=self.import_rooms_md)
        fm.add_command(label="Import MegaMUD character (.ini)…", command=self.import_megamud_char)
        fm.add_separator()
        fm.add_command(label="Start practice server (local)", command=self.start_practice)
        fm.add_command(label="Open data folder", command=lambda: self._open(config.DATA_DIR))
        fm.add_separator()
        fm.add_command(label="Exit", command=self.quit)
        m.add_cascade(label="File", menu=fm)
        pm = tk.Menu(m, tearoff=0)
        pm.add_command(label="New character…", command=self.new_profile)
        pm.add_command(label="Duplicate this character…", command=lambda: self.new_profile(copy=True))
        pm.add_command(label="Import MegaMUD character (.ini)…", command=self.import_megamud_char)
        m.add_cascade(label="Character", menu=pm)
        om = tk.Menu(m, tearoff=0)
        om.add_command(label="Settings…", command=self.open_settings, accelerator="Alt+I")
        om.add_command(label="Game Data…", command=self.open_game_data, accelerator="Alt+D")
        om.add_separator()
        self.config_var = tk.StringVar(value=self.s.settings.active_config)
        self.config_menu = om
        self._config_idx = []
        for slot in "1234":
            om.add_radiobutton(label=self.s.settings.config_name(slot), variable=self.config_var, value=slot,
                               command=lambda sl=slot: self.switch_config(sl), accelerator=f"Alt+{slot}")
            self._config_idx.append(om.index("end"))
        om.add_command(label="Rename this config profile…", command=self.rename_config)
        om.add_separator()
        om.add_checkbutton(label="Away From Keyboard", variable=self._var("afk"), accelerator="Alt+K")
        om.add_command(label="Font…", command=self.font_dialog)
        om.add_command(label="Hang up now", command=self.hangup_now, accelerator="Alt+H")
        om.add_command(label="Resume (walk into the boss room)", command=self.resume_boss, accelerator="Alt+R")
        om.add_separator()
        for name in SETTINGS_TABS:
            om.add_command(label=f"{name}…", command=lambda n=name: self.open_settings(n))
        om.add_separator()
        for name in ("Map", "Paths", "Bosses", "Stats"):
            om.add_command(label=name, command=lambda n=name: self.show_tab(n))
        m.add_cascade(label="Options", menu=om)
        wm = tk.Menu(m, tearoff=0)
        wm.add_command(label="Experience chart", command=self.open_exp_chart)
        wm.add_command(label="Session statistics", command=self.open_stats_window)
        wm.add_command(label="Combat summary (hits, misses, spells, damage taken)", command=lambda: popout(
            self, "Combat summary", lambda w: __import__("mudpilot.panes2", fromlist=["x"]).CombatSummaryPane(w, self),
            "900x720"))
        wm.add_command(label="Item history (and stashed coins)", command=lambda: popout(
            self, "Item history", lambda w: __import__("mudpilot.panes2", fromlist=["x"]).ItemHistoryPane(w, self),
            "860x520"))
        wm.add_command(label="History (by day)", command=self.open_history)
        wm.add_command(label="Timeline (where the time went)", command=lambda: popout(
            self, "Timeline", lambda w: TimelinePane(w, self), "1100x760"))
        wm.add_command(label="Deaths (replays)", command=lambda: popout(
            self, "Deaths", lambda w: DeathsPane(w, self), "1000x600"))
        wm.add_command(label="Conversations", command=self.open_chat_window)
        wm.add_command(label="Scheduled actions…", command=self.open_schedules)
        wm.add_command(label="Track a player…", command=self.track_player)
        wm.add_command(label="XP leaderboard (everyone's exp/hr)", command=self.open_leaderboard)
        wm.add_command(label="All characters (every MudPilot on the LAN)", command=self.open_overview)
        wm.add_command(label="Quests", command=self.open_quests)
        wm.add_command(label="Quest guide (step by step, from MME)", command=lambda: popout(
            self, "Quest guide", lambda w: __import__("mudpilot.panes2", fromlist=["x"]).QuestGuidePane(w, self),
            "1000x640"))
        wm.add_command(label="Peruse books (Golden Spire Secret Library)",
                       command=lambda: self.s.bot.log(self.s.bot.peruse.start()))
        wm.add_command(label="Inventory calculator", command=self.open_calc)
        wm.add_command(label="Party", command=self.open_party, accelerator="Alt+P")
        wm.add_command(label="Map in its own window", command=self.open_map_window)
        wm.add_command(label="Minimize / restore the map panel", command=self.toggle_map_min)
        wm.add_command(label="Reset layout (MegaMUD style)", command=self.reset_layout)
        wm.add_command(label="Path builder (make paths/loops without walking)", command=self.open_pathbuilder)
        wm.add_command(label="CP / Exp calculator", command=self.open_expcalc)
        wm.add_command(label="Stat & mana-regen breakpoints", command=self.open_statbreaks)
        wm.add_command(label="Combat calculator (you vs a monster)", command=self.open_combatcalc)
        wm.add_command(label="Spell book", command=self.open_spellbook)
        wm.add_command(label="Back-scroll / find…", accelerator="Alt+B", command=self.open_backscroll)
        wm.add_command(label="Game data (players, rooms, macros…)", command=self.open_game_data)
        wm.add_separator()
        wm.add_command(label="Log", command=lambda: self.show_tab("Log"))
        wm.add_separator()
        wm.add_command(label="Dock conversations top-right (on/off)", command=self.toggle_dock)
        m.add_cascade(label="Window", menu=wm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="Report a problem…", command=self.report_problem)
        hm.add_command(label="Help topics…", accelerator="F1", command=self.open_help)
        hm.add_command(label="Step-by-step guides (shows you where to click)…", command=self.open_guides)
        hm.add_command(label="Setup guide", command=self.open_guide)
        hm.add_command(label="Remote @ commands", command=self.remote_help)
        hm.add_command(label="My quests (flags and the next step in each)", command=lambda: popout(
            self, "Quest guide", lambda w: __import__("mudpilot.panes2", fromlist=["x"]).QuestGuidePane(w, self),
            "1180x640"))
        hm.add_command(label="Copy diagnostics (paste to Claude)   Ctrl+Shift+D", command=self.copy_diagnostics)
        self.root.bind("<Alt-b>", lambda e: self.s.bot.backstep())
        hm.add_command(label="Save debug bundle (zip for Claude)…", command=self.save_debug_bundle)
        hm.add_command(label="Open session recordings folder", command=self.open_traces)
        hm.add_command(label="Check for updates…", command=lambda: self.check_updates(quiet=False))
        hm.add_command(label="About MudPilot", command=self.about)
        m.add_cascade(label="Help", menu=hm)
        self.root.config(menu=m)
        self.root.bind("<Control-s>", lambda e: self.open_settings())
        self.root.bind("<F1>", lambda e: self.open_help())
        for seq, fn in (("h", self.hangup_now), ("i", self.open_settings), ("d", self.open_game_data),
                        ("v", lambda: self.open_settings("Events")), ("p", self.open_party),
                        ("k", lambda: self._var("afk").set(not self.s.settings.afk))):
            self.root.bind_all(f"<Alt-{seq}>", lambda e, f=fn: (f(), "break")[1])
            self.root.bind_all(f"<Alt-{seq.upper()}>", lambda e, f=fn: (f(), "break")[1])
        for slot in "1234":
            self.root.bind_all(f"<Alt-Key-{slot}>", lambda e, sl=slot: (self.switch_config(sl), "break")[1])
        self.root.bind_all("<KeyPress>", self._macro_key, add="+")
        self.root.bind_all("<KeyRelease>", self._key_up, add="+")
        self.root.bind("<FocusOut>", lambda e: getattr(self, "_held_keys", {}).clear(), add="+")
        self.root.bind_all("<KeyPress>", self._stray_key, add="+")

        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        if getattr(self, "_logo_small", None):
            ttk.Label(top, image=self._logo_small).pack(side="left", padx=(0, 8))
        ttk.Label(top, text="Character").pack(side="left", padx=(0, 4))
        self.profile_var = tk.StringVar(value=self.s.settings.profile)
        self.profile_box = ttk.Combobox(top, textvariable=self.profile_var, width=16, state="readonly",
                                        values=config.Settings.list_profiles())
        self.profile_box.pack(side="left", padx=(0, 10))
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: self.switch_profile(self.profile_var.get()))
        ttk.Label(top, text="Board").pack(side="left", padx=(0, 4))
        self.board_var = tk.StringVar(value=self.s.settings.board)
        self.board_box = ttk.Combobox(top, textvariable=self.board_var, width=12, state="readonly",
                                      values=config.list_boards())
        self.board_box.pack(side="left", padx=(0, 10))
        self.board_box.bind("<<ComboboxSelected>>", lambda e: self.set_board(self.board_var.get()))
        self.btn_connect = ttk.Button(top, text="☎ Connect", style="Accent.TButton", width=13,
                                      command=self.connect_toggle)
        self.btn_connect.pack(side="left")
        self.btn_stop = ttk.Button(top, text="■ Stop (Esc)", style="Stop.TButton", width=12, command=self.stop_or_rego)
        self.btn_stop.pack(side="left", padx=6)
        try:
            self._goto_img = tk.PhotoImage(file=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                             "assets", "logo_16.png"))
        except (tk.TclError, OSError):
            self._goto_img = None
        ttk.Button(top, text=" Goto", image=self._goto_img or "", compound="left",
                   command=lambda: self.open_picker("goto")).pack(side="left", padx=(0, 4))
        ttk.Button(top, text="⟳ Loop", command=lambda: self.open_picker("loop")).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="↶ Back", command=lambda: self.s.bot.backstep()).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="⚙ Settings", command=self.open_settings).pack(side="left")
        ttk.Button(top, text="Aa Font", command=self.font_dialog).pack(side="left", padx=6)
        ttk.Button(top, text="A−", width=3, command=lambda: self.zoom_font(-1)).pack(side="left")
        ttk.Button(top, text="A+", width=3, command=lambda: self.zoom_font(1)).pack(side="left", padx=(2, 0))
        ttk.Button(top, text="⚑ Report a problem", command=self.report_problem).pack(side="left", padx=(8, 0))
        # PvP realm with PvP hang-up off: a flashing red reminder (click = turn it on, hold 1 s = stop nagging)
        self.btn_pvp = None
        self._pvp_label_args = dict(text="⚠ PvP hang-up OFF", background="#a01818", foreground="#ffffff",
                                font=("Segoe UI", 9, "bold"), padx=8, pady=1, cursor="hand2")
        self._pvp_snoozed = False
        self.root.after(1500, self._pvp_flash)
        self.lbl_status = ttk.Label(top, text="Idle", style="Muted.TLabel")
        self.lbl_status.pack(side="right")
        bar = tk.Frame(self.root, background=PANEL)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        self.quick = {}
        icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
        self._icon_imgs = {}
        use_icons = self.s.settings.toolbar_icons
        qbar = tk.Frame(bar, background=PANEL)        # the toggle buttons (drag to reorder) — the red badges follow
        qbar.pack(side="left")
        self._qbar = qbar
        for key, label, tip in QUICK_BUTTONS:
            v = self._var(key)
            img = None
            if use_icons:
                try:
                    img = self._icon_imgs[key] = tk.PhotoImage(file=os.path.join(icon_dir, f"{key}_off.png"))
                    self._icon_imgs[key + "_on"] = tk.PhotoImage(file=os.path.join(icon_dir, f"{key}.png"))
                except (tk.TclError, OSError):
                    img = None
            if img is not None:
                # MegaMUD-style icon toggle: dark when off, green when on; hover shows what it is
                b = tk.Checkbutton(qbar, image=img, selectimage=self._icon_imgs[key + "_on"], variable=v,
                                   indicatoron=False, relief="flat", borderwidth=0,
                                   padx=6, pady=4, background="#1a212b", selectcolor="#1f7a4a",
                                   activebackground="#2e3d52", cursor="hand2", offrelief="flat", overrelief="flat")
                b.pack(side="left", padx=1)
            else:
                b = tk.Checkbutton(qbar, text=label, variable=v, indicatoron=False, width=len(label) + 2,
                                   font=("Segoe UI", 9, "bold"), relief="flat", borderwidth=0, padx=4, pady=3,
                                   background="#243041", foreground=MUTED, selectcolor="#1f7a4a",
                                   activebackground="#2e3d52", activeforeground=TEXT, cursor="hand2")
                b.pack(side="left", padx=2)
                v.trace_add("write", lambda *a, b=b, v=v: b.configure(foreground=TEXT if v.get() else MUTED))
                b.configure(foreground=TEXT if v.get() else MUTED)
            Tip(b, f"{label} — {tip}  ({'on' if v.get() else 'off'}: click to switch)")
            v.trace_add("write", lambda *a, b=b, v=v, label=label, tip=tip: setattr(
                b, "_tiptext", f"{label} — {tip}  ({'on' if v.get() else 'off'}: click to switch)"))
            self.quick[key] = b
            self._toolbar_drag_bind(b, key)
        self._toolbar_pack()
        qbar.bind("<Button-3>", self._toolbar_menu)
        self.btn_manual = tk.Label(bar, text="", background="#a01818", foreground="#ffffff",
                                   font=("Segoe UI", 9, "bold"), padx=8, pady=1, cursor="hand2")
        self.btn_manual.bind("<ButtonRelease-1>", lambda e: self.s.bot.manual.mob and self.s.bot.manual.end(
            "you clicked the MANUAL badge", takeover=True))
        Tip(self.btn_manual, "You're fighting this monster by hand (you typed an attack or a spell at it):\n"
                             "MudPilot won't attack it until combat's been off for 2 rounds with no attack from you,\n"
                             "or 4 rounds since your last one. Click to hand it back to MudPilot now")
        self.btn_pvp = tk.Label(bar, **self._pvp_label_args)
        self.btn_pvp.bind("<ButtonPress-1>", self._pvp_press)
        self.btn_pvp.bind("<ButtonRelease-1>", self._pvp_release)
        Tip(self.btn_pvp, "This is a PvP realm and 'Hang up when a player attacks me' is off.\n"
                          "Click to turn it on · hold for a second to stop this reminder")
        self.btn_nohang = tk.Label(bar, text="⚠ NoHang ON — no automatic hang-ups", background="#a01818",
                                   foreground="#ffffff", font=("Segoe UI", 9, "bold"), padx=8, pady=1, cursor="hand2")
        self.btn_nohang.bind("<ButtonRelease-1>", lambda e: (self._var("no_hang").set(False),
                                                             self.add_log("NoHang off — hang-ups work again")))
        Tip(self.btn_nohang, "NoHang is on: PvP, low HP, Enemy and message-rule hang-ups are all off.\n"
                             "Click to turn NoHang off")
        self.btn_nowait = tk.Label(bar, text="⚠ NoWait ON — ignoring @wait", background="#a01818",
                                   foreground="#ffffff", font=("Segoe UI", 9, "bold"), padx=8, pady=1, cursor="hand2")
        self.btn_nowait.bind("<ButtonRelease-1>", lambda e: (self._var("no_wait").set(False),
                                                             self.add_log("NoWait off — @wait works again")))
        Tip(self.btn_nowait, "NoWait is on: @wait from the party is ignored and the leader doesn't wait for hurt "
                             "members.\nClick to turn NoWait off")
        self.btn_handsoff = tk.Label(bar, text="✋ Hands off — nothing automatic", background="#a06a00",
                                     foreground="#ffffff", font=("Segoe UI", 9, "bold"), padx=8, pady=1, cursor="hand2")
        self.btn_handsoff.bind("<ButtonRelease-1>", lambda e: (self._var("hands_off").set(False),
                                                               self.add_log("Hands off ended — automation back on")))
        Tip(self.btn_handsoff, "Hands off is on: MudPilot isn't doing anything by itself.\nClick to switch it back on")
        tk.Label(bar, text="  green = on · hover for names",
                 background=PANEL, foreground=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=8)
        self.toolbar = bar
        self._var("show_toolbar").trace_add("write", lambda *a: self._toolbar_vis())
        self.root.after(10, self._toolbar_vis)
        self.root.after(50, self._window_colour)

        info = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        info.pack(fill="x")
        self._info_row = info
        self.lbl_room = ttk.Label(info, text="Room: —", style="Head.TLabel", width=46)
        self.lbl_room.pack(side="left")
        ttk.Label(info, text="HP").pack(side="left", padx=(12, 4))
        self.pb_hp = ttk.Progressbar(info, length=150, style="HP.Horizontal.TProgressbar", maximum=100)
        self.pb_hp.pack(side="left")
        self.lbl_hp = ttk.Label(info, text="", width=10)
        self.lbl_hp.pack(side="left", padx=4)
        ttk.Label(info, text="MA").pack(side="left", padx=(8, 4))
        self.pb_ma = ttk.Progressbar(info, length=110, style="MA.Horizontal.TProgressbar", maximum=100)
        self.pb_ma.pack(side="left")
        self.lbl_ma = ttk.Label(info, text="", width=10)
        self.lbl_ma.pack(side="left", padx=4)
        self.lbl_mobs = ttk.Label(info, text="", style="Muted.TLabel")
        self.lbl_mobs.pack(side="left", padx=8)

        self._build_statusbar()
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        left = ttk.Frame(pane)
        stf = self.s.settings
        self.term = tk.Text(left, background=BG, foreground=FG[None][0], insertbackground=TEXT,
                            font=self._term_font(), wrap="word",
                            borderwidth=0, padx=6, pady=4, state="disabled", width=60, height=10)
        sb = ttk.Scrollbar(left, command=lambda *a: (self._see_cancel(), self.term.yview(*a)))
        self._term_sb = sb
        self.term.configure(yscrollcommand=self._on_term_scroll)
        for k, (n, b) in FG.items():
            ks = "x" if k is None else k
            self.term.tag_configure(f"c{ks}", foreground=n)
            self.term.tag_configure(f"c{ks}b", foreground=b)
        self.term.tag_configure("sent", foreground="#e6b450")
        self.term.tag_configure("botsent", foreground="#6c8fb3")
        self.term.mark_set("partial", "end-1c")
        self.term.mark_gravity("partial", "left")
        self.term.bind("<Button-3>", self._term_menu)
        ent_row = ttk.Frame(left)
        self.entry = tk.Entry(ent_row, background="#0f1318", foreground=TEXT, insertbackground=TEXT,
                              font=(stf.term_font or "Consolas", int(stf.term_font_size or 10) + 1),
                              borderwidth=0, relief="flat")
        self.entry.pack(fill="x", ipady=5)
        ent_row.pack(side="bottom", fill="x", pady=(4, 0))
        sb.pack(side="right", fill="y")
        self.term.pack(side="left", fill="both", expand=True)
        # number pad / F-key macros must win over the command line's own typing (else "8" lands in the box)
        self.entry.bindtags(("MPScreen", "MPMacro") + self.entry.bindtags())
        self.entry.bind_class("MPMacro", "<KeyPress>", self._macro_key)
        self.entry.bind_class("MPScreen", "<KeyPress>", self._screen_key)
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<<Paste>>", self._paste_lines)
        self.entry.bind("<Up>", lambda e: self.hist(-1))
        self.entry.bind("<Down>", lambda e: self.hist(1))
        for w in (self.entry, self.term):          # back-scroll the MUD screen without leaving the command line
            w.bind("<Prior>", lambda e: self.scroll_page(-1))
            w.bind("<Next>", lambda e: self.scroll_page(1))
            w.bind("<Control-End>", self.scroll_bottom)
            w.bind("<Control-Home>", lambda e: (self._see_cancel(), self.term.see("1.0"), "break")[2])
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):     # your own scrolling wins over a queued follow
            self.term.bind(seq, lambda e: self._see_cancel(), add="+")
        self.root.bind("<Alt-b>", self.open_backscroll)
        self.root.bind("<Alt-r>", lambda e: self.resume_boss())
        self.root.bind("<Escape>", lambda e: self.stop_bot())
        self.term.bind("<Control-MouseWheel>", lambda e: (self.zoom_font(1 if e.delta > 0 else -1), "break")[1])
        self.term.bind("<Control-Button-4>", lambda e: (self.zoom_font(1), "break")[1])
        self.term.bind("<Control-Button-5>", lambda e: (self.zoom_font(-1), "break")[1])
        for seq, d in (("<Control-equal>", 1), ("<Control-plus>", 1), ("<Control-minus>", -1)):
            self.root.bind(seq, lambda e, d=d: (self.zoom_font(d), "break")[1])
        pane.add(left, weight=2)

        rside = ttk.PanedWindow(pane, orient="vertical")
        pane.add(rside, weight=1)
        self.main_pane = pane
        self.right_pane = rside
        # conversations docked top-right (MegaMUD layout); View menu can undock it into a tab
        self.dock_frame = ttk.Frame(rside)
        hdr = ttk.Frame(self.dock_frame)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Conversations", style="Head.TLabel").pack(side="left", padx=6, pady=(4, 0))
        self.docked_chat = ChatPane(self.dock_frame, self)
        self.docked_chat.pack(fill="both", expand=True)
        self.tools_box = ttk.Frame(rside)
        th = ttk.Frame(self.tools_box)
        th.pack(fill="x")
        self.tools_min_btn = ttk.Button(th, text="▁ Minimize", width=11, command=self.toggle_map_min)
        self.tools_min_btn.pack(side="right")
        ttk.Button(th, text="⧉ Map window", width=13, command=self.open_map_window).pack(side="right", padx=4)
        right = ttk.Notebook(self.tools_box)
        right.pack(fill="both", expand=True)
        self.tools_nb = right
        if self.s.settings.dock_chat:
            rside.add(self.dock_frame, weight=1)
        rside.add(self.tools_box, weight=1)
        self.extra_maps = []
        self._layout_dragged = False
        self._layout_t0 = time.time()

        def dragged(e):
            self._layout_dragged = True        # only a split you set yourself is remembered
            self.root.after(50, self._remember_layout)
        for pw in (pane, rside):
            pw.bind("<ButtonRelease-1>", dragged, add="+")
        # the window keeps sizing itself for a few seconds after start (maximise, the splash closing): apply the
        # split again as it does, until you move it — at 0.3 s alone the conversations box opened squeezed
        # (only when its size really changed: on a Mac applying the split fires <Configure> again, ~230,000
        # times in the first 10 s)
        self._layout_size = None

        def resized(e):
            if time.time() - self._layout_t0 >= 10 or self._layout_dragged or (e.width, e.height) == self._layout_size:
                return
            self._layout_size = (e.width, e.height)
            self.root.after_idle(self._apply_layout)
        rside.bind("<Configure>", resized, add="+")
        self.root.after(300, self._apply_layout)
        self.root.after(1200, self._reopen_windows)
        from .windows import remember_window
        self.root.after(1500, lambda: remember_window(self, self.root, "main", reopen=False))
        mapbox = ttk.Frame(right)
        mbar = ttk.Frame(mapbox, padding=(4, 2))
        mbar.pack(fill="x")
        self.map = MapView(mapbox, self.s, on_goto=self.goto_room)
        MapSearch(mbar, self.map, width=22)
        ttk.Label(mbar, text="Enter to search · double-click to walk", style="Muted.TLabel").pack(side="left")
        self.map.pack(fill="both", expand=True)
        right.add(mapbox, text="Map")
        right.add(self._paths_tab(right), text="Paths")
        right.add(PartyPane(right, self, docked=True), text="Party")
        self.chat_tab = self._chat_tab(right)
        right.add(self.chat_tab, text="Chat")
        if self.s.settings.dock_chat:
            right.hide(self.chat_tab)
        right.add(self._boss_tab(right), text="Bosses")
        right.add(self._stats_tab(right), text="Stats")
        logf = ttk.Frame(right)
        # scrolled up = it stays put (Dan, 2026-10-30: every new line pulled it to the bottom, so you couldn't read
        # back); new lines show on a button that jumps to the bottom, like the game screen's back-scroll bar
        self.log_jump = ttk.Button(logf, text="", command=self._log_bottom)
        lsb = ttk.Scrollbar(logf, orient="vertical")
        self.logbox = tk.Text(logf, background="#0f1318", foreground=MUTED, font=("Consolas", 9),
                              borderwidth=0, state="disabled", wrap="word", yscrollcommand=lsb.set)
        lsb.configure(command=self.logbox.yview)
        self.logbox.tag_configure("chatkw", foreground="#0b0d10", background="#ffd84d")   # chat keyword hits (0.8.201)
        lsb.pack(side="right", fill="y")
        self.logbox.pack(fill="both", expand=True)
        self._log_new = 0
        self.logbox.bind("<MouseWheel>", lambda e: self.root.after(50, self._log_at_bottom_check), add="+")
        lsb.bind("<ButtonRelease-1>", lambda e: self.root.after(50, self._log_at_bottom_check), add="+")
        right.add(logf, text="Log")
        self._build_settings()
        self.entry.focus_set()

    # ------------------------------------------------------------------ settings widgets
    def _var(self, key):
        if key in self._vars:
            return self._vars[key]
        val = getattr(self.s.settings, key)
        if isinstance(val, bool):
            v = tk.BooleanVar(value=val)
        elif isinstance(val, int):
            v = tk.IntVar(value=val)
        elif isinstance(val, float):
            v = tk.DoubleVar(value=val)
        elif isinstance(val, list):
            v = tk.StringVar(value=", ".join(val))
        else:
            v = tk.StringVar(value=val)
        v.trace_add("write", lambda *a, k=key, vv=v: self._set(k, vv))
        self._vars[key] = v
        return v

    def _set(self, key, v):
        cur = getattr(self.s.settings, key)
        try:
            raw = v.get()
        except tk.TclError:
            return
        if isinstance(cur, list):
            raw = [x.strip() for x in str(raw).split(",") if x.strip()]
        setattr(self.s.settings, key, raw)
        pend = self.__dict__.setdefault("_ui_changed", {})
        if key not in pend:
            pend[key] = cur                      # what it was before you started changing it
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, self._save_and_log)

    def _save_and_log(self):
        """Settings you changed: saved, and logged once each ('You: set auto_rest: True → False')."""
        from . import uilog
        pend, self._ui_changed = getattr(self, "_ui_changed", {}), {}
        for k, old in pend.items():
            new = getattr(self.s.settings, k, None)
            if new != old:
                uilog.setting_changed(k, old, new)
        self.s.settings.save()

    def _check(self, parent, key, label):
        return ttk.Checkbutton(parent, text=label, variable=self._var(key))

    def _row(self, parent, r, label, key, kind="spin", frm=0, to=999, width=8, hint=""):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        if kind == "spin":
            w = ttk.Spinbox(parent, from_=frm, to=to, textvariable=self._var(key), width=width)
        else:
            w = ttk.Entry(parent, textvariable=self._var(key), width=width)
        w.grid(row=r, column=1, sticky="we", pady=3)
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=8)
        return w

    # ------------------------------------------------------------------ tabs
    def _paths_tab(self, nb):
        """Go to a room, run a loop, or run a path — one thing at a time, like MegaMUD's Goto / Loop buttons."""
        f = ttk.Frame(nb, padding=8)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.paths_mode = tk.StringVar(value="loop")
        for val, lbl in (("goto", "Go to room"), ("loop", "Loops"), ("path", "Paths"), ("camp", "Camp lairs")):
            tk.Radiobutton(bar, text=lbl, variable=self.paths_mode, value=val, indicatoron=False, width=11,
                           font=("Segoe UI", 9, "bold"), relief="flat", borderwidth=0, padx=6, pady=4,
                           background="#243041", foreground=TEXT, selectcolor="#1f7a4a", activebackground="#2e3d52",
                           activeforeground=TEXT, cursor="hand2", command=self._paths_mode_changed).pack(side="left", padx=(0, 3))
        mb = ttk.Menubutton(bar, text="More ▾")
        more = tk.Menu(mb, tearoff=0)
        more.add_command(label="Import MegaMUD paths folder…", command=self.import_mp_folder)
        more.add_command(label="Import .mp files…", command=self.import_mp_files)
        more.add_command(label="Path builder…", command=self.open_pathbuilder)
        more.add_command(label="Record a loop by walking it…", command=lambda: self.record_route("loop", True))
        more.add_command(label="Record a path by walking it…", command=lambda: self.record_route("path", True))
        more.add_command(label="Draw a loop on the map…", command=lambda: self.record_route("loop", False))
        more.add_separator()
        more.add_command(label="Edit loop on the map (no attack / don't rest / stash room)…", command=self.edit_loop_dialog)
        more.add_command(label="Stash room for this loop…", command=self.loop_stash_dialog)
        more.add_command(label="Loop stats (which loop pays best)…", command=self.open_loop_stats)
        more.add_command(label="Loop rotation…", command=self.loop_rotation_dialog)
        more.add_command(label="Find loops automatically (lair chains)…", command=self.loop_builder_dialog)
        more.add_command(label="Analyze selected loop…", command=self.analyze_loop_dialog)
        more.add_command(label="Best spots for me…", command=self.spots_dialog)
        more.add_command(label="Move selected to area folder…", command=self.move_path_folder)
        more.add_command(label="Delete selected path", command=self.delete_path)
        more.add_command(label="Save last Go-to route as .mp…", command=self.save_route)
        mb["menu"] = more
        first = bar.pack_slaves()
        # packed ahead of the Go to / Loops / Paths buttons so a narrow window squeezes them, not "More ▾"
        # (Revolution's window showed only the arrow)
        mb.pack(side="right", before=first[0]) if first else mb.pack(side="right")
        sr = ttk.Frame(f)
        sr.pack(fill="x", pady=(6, 0))
        self.paths_q = tk.StringVar()
        self.paths_entry = ttk.Entry(sr, textvariable=self.paths_q)
        self.paths_entry.pack(side="left", fill="x", expand=True)
        self.paths_entry.bind("<Return>", lambda e: self._paths_go())
        self.paths_q.trace_add("write", lambda *a: self._paths_filter())
        self.paths_btn = ttk.Button(sr, text="Run loop", style="Accent.TButton", command=self._paths_go, width=12)
        self.paths_btn.pack(side="left", padx=(6, 0))
        ttk.Button(sr, text="How?", command=self.how_dialog, width=6).pack(side="left", padx=(6, 0))
        self.paths_hint = ttk.Label(f, text="", style="Muted.TLabel")
        self.paths_hint.pack(anchor="w", pady=(2, 4))
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        cols = ("steps", "exphr", "match", "from")
        self.tree = ttk.Treeview(body, columns=cols, show="tree headings", height=12)
        self.tree.heading("#0", text="Name")
        self.tree.column("#0", width=200)
        for c, t, w in (("steps", "Steps", 45), ("exphr", "Exp/hr", 70), ("match", "Match", 50), ("from", "Starts at", 200)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.bind("<Double-1>", lambda e: self._paths_go())
        pm = tk.Menu(self.tree, tearoff=0)
        pm.add_command(label="Analyze this loop…", command=self.analyze_loop_dialog)
        pm.add_command(label="Edit loop on the map (no attack / don't rest / stash room)…", command=self.edit_loop_dialog)
        pm.add_command(label="Stash room for this loop…", command=self.loop_stash_dialog)
        pm.add_command(label="Move to area folder…", command=self.move_path_folder)
        pm.add_command(label="Send to a party member…", command=self.send_path_dialog)

        def _ctx(e):
            iid = self.tree.identify_row(e.y)
            if iid:
                self.tree.selection_set(iid)
                pm.tk_popup(e.x_root, e.y_root)
        self.tree.bind("<Button-3>", _ctx)
        self.results = tk.Listbox(body, height=12, background="#0f1318", foreground=TEXT, borderwidth=0,
                                  selectbackground="#1f4f7a", font=("Consolas", 10))
        self.results.bind("<Double-1>", lambda ev: self.goto_selected())
        self.camp_box = self._camp_box(body)  # Camp lairs (0.8.201)
        self.goto_var = self.paths_q          # older helpers use this name
        lf = ttk.Frame(f)
        lf.pack(fill="x", pady=(6, 0))
        ttk.Label(lf, text="When unsure of the room, type").pack(side="left")
        ttk.Entry(lf, textvariable=self._var("locate_cmd"), width=8).pack(side="left", padx=6)
        ttk.Label(lf, text="(your board's room-number command; blank = off)", style="Muted.TLabel").pack(side="left")
        self._result_keys = []
        self._last_route = None
        self._paths_mode_changed()
        return f

    def _paths_mode_changed(self):
        mode = self.paths_mode.get()
        self.paths_q.set("")
        self.camp_box.pack_forget()
        if mode == "camp":
            self.tree.pack_forget()
            self.results.pack_forget()
            self.camp_box.pack(fill="both", expand=True)
            self.paths_hint.configure(text="Mark lairs (Add this room, type map/room and Enter, or Game Data → Rooms), "
                                           "then Start camping. It waits beside each lair and goes in as it comes back.")
            self._camp_refresh()
        elif mode == "goto":
            self.tree.pack_forget()
            self.results.pack(fill="both", expand=True)
            self.paths_btn.configure(text="Go")
            self.paths_hint.configure(text="Type a room name (e.g. Dark Alley) or map/room (e.g. 3/606), pick it, then Go "
                                           "(or double-click). Double-clicking a room on the Map works too.")
            self.results.delete(0, "end")
        else:
            self.results.pack_forget()
            self.tree.pack(fill="both", expand=True)
            self.paths_btn.configure(text="Run loop" if mode == "loop" else "Run path")
            self.paths_hint.configure(text=("Pick a loop and Run (double-click). If you're not on it, MudPilot walks to "
                                            "its start first." if mode == "loop" else
                                            "Pick a path and Run. MudPilot walks to its start first if needed."))
            self.refresh_paths()
        self.paths_entry.focus_set()

    def _paths_filter(self):
        if self.paths_mode.get() == "camp":
            return
        if self.paths_mode.get() == "goto":
            if len(self.paths_q.get().strip()) >= 2:
                self.search_rooms()
        else:
            self.refresh_paths()

    def _waypoints(self, rooms, most=18) -> list:
        """The areas along these rooms, in order — Black House, Fungus Forest, Cracked Plain, Old Mine, Webbed Mine,
        Diamond Mine… (Dan: areas say which way it goes better than single rooms). Each with one room to look at
        on the map: a known room (Rooms.md) in that stretch if there is one, else a room with monsters (a lair),
        else its first room. [(label, room)]"""
        w = self.s.world
        try:
            known = {}
            for _g, n, k in self.s.known_rooms():
                known.setdefault(tuple(k), n)
        except Exception:
            known = {}
        segs = []                                    # [area, [rooms]]
        for k in rooms:
            r = w.room(k)
            a = (r.name.split(",")[0].strip() if r else "") or f"{k[0]}/{k[1]}"
            if segs and segs[-1][0] == a:
                segs[-1][1].append(k)
            else:
                segs.append([a, [k]])
        out, listed = [], set()
        for a, ks in segs:
            if a.lower() in listed:
                continue                             # (a town's streets come round again — once is enough)
            listed.add(a.lower())
            pick = next((k for k in ks if k in known), None)
            label = a + (f" — {known[pick]}" if pick and known[pick].lower() != a.lower() else "")
            if pick is None:
                pick = next((k for k in ks if (w.room(k) and w.room(k).lair)), ks[0])
            out.append((label, pick))
        if len(out) > most:                          # a long way: spread them out, keeping first and last
            step = (len(out) - 1) / (most - 1)
            out = [out[round(i * step)] for i in range(most)]
        return out

    def show_on_map(self, room):
        """Centre the map on a room (outlined yellow) — the How? window's double-click."""
        m = getattr(self, "map", None)
        if m is None:
            return
        st = self.s.state
        me = st.room or (st.candidates[0] if st.candidates else None)
        m.scout = (tuple(room), me)
        m.follow_paused = True
        try:
            self.tools_nb.select(m.master)
        except Exception:
            pass
        m.redraw()

    def how_dialog(self):
        """Dan: pick a loop or path and see a few known rooms along it (and on the way there) — which way it goes.
        Select one and say it isn't safe (that room, or its whole area): it goes on your avoid list and the way
        there is worked out again."""
        mp = self._selected_path() if self.tree.selection() else None
        if not mp:
            messagebox.showinfo("How?", "Pick a loop or path in the list first.")
            return
        w, st, cfg = self.s.world, self.s.state, self.s.settings
        d = tk.Toplevel(self.root)
        d.title(f"How: {mp.title} - MudPilot")
        d.configure(background=PANEL)
        d.geometry("760x420")
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        head = ttk.Label(fr, text="", style="Muted.TLabel", wraplength=730, justify="left")
        head.pack(anchor="w")
        tv = ttk.Treeview(fr, columns=("room", "note"), show="tree headings", height=14)
        tv.heading("#0", text="Areas along the way")
        tv.column("#0", width=330)
        tv.heading("room", text="Room")
        tv.column("room", width=80)
        tv.heading("note", text="")
        tv.column("note", width=300)
        tv.tag_configure("bad", foreground="#ff6b6b")
        tv.tag_configure("part", foreground="#8a94a6")
        tv.pack(fill="both", expand=True, pady=(6, 0))
        rows = {}
        tv.bind("<Double-1>", lambda e: (rows.get(tv.selection()[0]) and self.show_on_map(rows[tv.selection()[0]]))
                if tv.selection() else None)

        def fill():
            tv.delete(*tv.get_children())
            rows.clear()
            rooms = [x.room for x in mp.steps if x.room] + ([mp.steps[-1].dest] if mp.steps and mp.steps[-1].dest else [])
            here = st.room
            avoid = self.s.bot.avoid_set()
            note = ""
            if here and rooms and here not in rooms:
                self.s.bot.__dict__.pop("_way_memo", None)
                try:
                    rt = self.s.bot.plan_route(here, rooms[0])
                except Exception:
                    rt = None
                if rt:
                    way = [here] + [ex.to for ex in rt]
                    tv.insert("", "end", text=f"Getting there from here — {len(rt)} steps", tags=("part",))
                    for n, k in self._waypoints(way):
                        bad = self.s.bot.danger_room(k) or k in avoid
                        rows[tv.insert("", "end", text=f"   {n}", values=(f"{k[0]}/{k[1]}", "dangerous" if bad else ""),
                                       tags=("bad",) if bad else ())] = k
                    nb = [ex.to for ex in rt if self.s.bot.danger_room(ex.to) or ex.to in avoid]
                    if nb:
                        note = f"Careful: the way there passes {len(nb)} dangerous or avoided room(s). "
                else:
                    tv.insert("", "end", text="No way there from here on the map (with what you avoid)", tags=("bad",))
            tv.insert("", "end", text=f"{'The loop' if mp.is_loop else 'The path'} — {len(mp.steps)} steps", tags=("part",))
            if rooms:
                for n, k in self._waypoints(rooms):
                    rows[tv.insert("", "end", text=f"   {n}", values=(f"{k[0]}/{k[1]}", ""))] = k
            else:
                tv.insert("", "end", text="   (its rooms aren't matched to the map yet)", tags=("part",))
            head.configure(text=note + "Double-click a place to see it on the map. Pick one and mark it not safe: it goes on your avoid list (Settings → "
                                       "Other → Routing — asked before going through) and the way there is worked "
                                       "out again. A loop's own rooms are fixed — pick another loop if they're the problem.")

        def picked():
            sel = tv.selection()
            return rows.get(sel[0]) if sel else None

        def unsafe(area):
            k = picked()
            if not k:
                messagebox.showinfo("How?", "Pick one of the places first.", parent=d)
                return
            r = w.room(k)
            if area:
                name = (r.name.split(",")[0].strip() if r else "")
                if not name:
                    return
                lst = list(cfg.avoid_names or [])
                if name.lower() not in [x.lower() for x in lst]:
                    lst.append(name)
                cfg.avoid_names = lst
                self.add_log(f"Routing: '{name}' marked not safe — routes keep out of it (Settings → Other → Routing)")
            else:
                lst = list(cfg.avoid_rooms or [])
                key = f"{k[0]}/{k[1]}"
                if key not in lst:
                    lst.append(key)
                cfg.avoid_rooms = lst
                self.add_log(f"Routing: {key} {r.name if r else ''} marked not safe — routes keep out of it")
            cfg.save()
            fill()
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Not safe: this room", command=lambda: unsafe(False)).pack(side="left")
        ttk.Button(b, text="Not safe: this whole area", command=lambda: unsafe(True)).pack(side="left", padx=6)
        ttk.Button(b, text="Close", command=d.destroy).pack(side="right")
        fill()

    def _paths_go(self):
        mode = self.paths_mode.get()
        if mode == "camp":
            self._camp_go()
            return
        if mode == "goto":
            self.goto_selected()
            return
        sel = self.tree.selection()
        if not sel or sel[0].startswith("folder:"):
            kids = [k for top in self.tree.get_children()
                    for k in ([top] if not top.startswith("folder:") else self.tree.get_children(top))]
            if len(kids) == 1:
                self.tree.selection_set(kids[0])
            else:
                return
        if self.tree.selection()[0] == PERUSE_IID:
            self.add_log(self.s.bot.peruse.start())
            return
        mp = self._selected_path()
        if not mp:
            return
        here = self.s.state.room
        on_it = bool(here) and any(st.room == here for st in mp.steps)
        if not on_it and mp.resolved and mp.steps and mp.steps[0].room:
            self.plan_route(lambda ask: self.s.bot.goto(mp.steps[0].room, then=mp, ask=ask), "to the path's start")
        else:
            self.s.bot.start_path(mp, loop=(mode == "loop"))

    # ------------------------------------------------------------------ Camp lairs (0.8.201, lair_camp.py)
    def _camp_box(self, parent):
        """The Paths tab's Camp lairs list: the marked lairs, each one's respawn time and when it's next back."""
        box = ttk.Frame(parent)
        cols = ("name", "respawn", "next")
        self.camp_tree = ttk.Treeview(box, columns=cols, show="tree headings", height=10)
        self.camp_tree.heading("#0", text="Lair")
        self.camp_tree.column("#0", width=70)
        for c, t_, w_ in (("name", "Name", 190), ("respawn", "Respawn", 110), ("next", "Next back", 90)):
            self.camp_tree.heading(c, text=t_)
            self.camp_tree.column(c, width=w_, anchor="w")
        self.camp_tree.pack(fill="both", expand=True)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Add this room", command=self._camp_add_here).pack(side="left")
        ttk.Button(row, text="Remove", command=self._camp_remove).pack(side="left", padx=4)
        self._check(row, "lair_camp_throughput", "Least-late pick (not closest ready)").pack(side="left", padx=8)
        self.camp_note = ttk.Label(box, text="", style="Muted.TLabel")
        self.camp_note.pack(anchor="w")
        self.camp_tree.bind("<Delete>", lambda e: self._camp_remove())
        return box

    def _camp_refresh(self):
        """Every 2 s while the Camp lairs list is showing (only then: nothing ticks for a hidden list)."""
        if getattr(self, "_camp_after", None):
            try:
                self.root.after_cancel(self._camp_after)
            except Exception:
                pass
            self._camp_after = None
        if self.paths_mode.get() != "camp":
            return
        lc = self.s.lair_camp
        try:
            rows, err = lc.rows(), ""
        except Exception as ex:
            rows, err = [], f"Couldn't work out the lair times: {ex}"
        keep = set(self.camp_tree.selection())
        self.camp_tree.delete(*self.camp_tree.get_children())
        for room, name, resp, nxt in rows:
            iid = f"{room[0]}/{room[1]}"
            self.camp_tree.insert("", "end", iid=iid, text=iid, values=(name, resp, nxt))
        for iid in keep:
            if self.camp_tree.exists(iid):
                self.camp_tree.selection_add(iid)
        self.paths_btn.configure(text="Stop camping" if lc.on else "Start camping")
        self.camp_note.configure(text=err or ("No lairs marked yet." if not rows else lc.status if lc.on else
                                              "Not camping. Respawn: learned (timed by you), mme (Rooms.Delay) "
                                              "or default."))
        self._camp_after = self.root.after(2000, self._camp_refresh)

    def _camp_go(self):
        """The Paths button in Camp lairs: a typed map/room is added; otherwise Start / Stop camping."""
        from .lair_camp import room_key
        txt = self.paths_q.get().strip()
        lc = self.s.lair_camp
        if txt:
            k = room_key(txt)
            self.add_log(lc.add(k) if k else f"'{txt}' isn't a map/room (e.g. 14/6534)")
            self.paths_q.set("")
        elif lc.on:
            lc.stop("Stopped by you (Stop camping)")
            if self.s.bot.walking:
                self.s.bot.stop("Stopped by you (Stop camping)")
        else:
            self.add_log("Camp lairs: " + lc.start(by="you"))
        self._camp_refresh()

    def _camp_add_here(self):
        k = self.s.state.room
        self.add_log(self.s.lair_camp.add(k) if k else "Not sure which room this is — press Enter (look) first")
        self._camp_refresh()

    def _camp_remove(self):
        from .lair_camp import room_key
        for iid in self.camp_tree.selection():
            k = room_key(iid)
            if k:
                self.add_log(self.s.lair_camp.remove(k))
        self._camp_refresh()

    def _combat_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        f.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(f, text="Engage rules", style="Head.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        self._row(f, r, "Attack only if mobs ≥", "min_mobs", to=20, hint="minimum attackable mobs in room"); r += 1
        self._row(f, r, "…and mobs ≤", "max_mobs", to=99, hint="skip rooms with more than this"); r += 1
        self._check(f, "defend_out_of_range", "Fight back if attacked outside that range").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "danger_check", "Danger check: before a lair, rest up if what spawns there could hurt too much "
                    "(learns from your fights)").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "danger_stop", "…and stop the loop if even full HP isn't enough").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "attack_on_entry", "Attack on room entry — first thing when you walk in on hostile monsters "
                    "(ahead of par, blesses; healing still first if hurt)").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "skip_zero_exp", "Ignore mobs worth 0 exp (shopkeepers, guards)").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "manual_override", "Hands off a monster you attack or cast at yourself — until combat's off 2 "
                    "rounds with nothing from you, or 4 rounds since your last attack").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Label(f, text="Only evil (hostile) monsters are attacked — good ones (guards, the mayor) and neutral ones (wild turkey, "
                          "shopkeepers) are left alone, using MME's data. "
                          "Anything that attacks you is always fought back.", style="Muted.TLabel").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "attack_neutral", "Also attack neutral monsters (wild turkey, shopkeepers, healers…)").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "attack_good", "Also attack good monsters (guards, the mayor — gives you evil points)").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Melee attack command", "attack_cmd", kind="entry", width=20, hint="{target} = mob"); r += 1
        self._row(f, r, "Backstab weapon", "backstab_weapon", kind="entry", width=20,
                  hint="wielded for a 'bs', then back (blank = off)"); r += 1
        self._check(f, "auto_weapon_swap", "Weapon can't hurt it (needs more magic)? Wield one I carry that can, then mine again after").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Never attack", "ignore_mobs", kind="entry", width=30, hint="comma list"); r += 1
        self._row(f, r, "Only attack", "only_mobs", kind="entry", width=30, hint="blank = everything"); r += 1
        ttk.Label(f, text="Eco travel (the Eco button)", style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(14, 0)); r += 1
        self._check(f, "eco_travel", "On the way somewhere (Go to / a path that isn't a loop), walk past small fry").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Still fight if worth ≥", "eco_min_exp", to=10_000_000, hint="exp a kill (0 = auto: level × 50, or ½ min of your exp/hr)"); r += 1
        self._row(f, r, "…or it hits ≥", "eco_max_hit", to=5000, hint="damage a hit (0 = 8% of max HP, at least 25)"); r += 1
        self._row(f, r, "…or a pack hits ≥ % HP a round", "eco_pack_pct", to=100, hint="what you walk past adds up (10 locusts): wipe the room (0 = off)"); r += 1
        self._row(f, r, "…and fight back below HP %", "eco_hp_pct", to=100, hint="everything on you gets fought"); r += 1
        ttk.Label(f, text="Combat spells", style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(14, 0)); r += 1
        self._check(f, "auto_spells", "Pick attack spells automatically from the spells I know (skips resisted ones)").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Attack spell(s)", "attack_spells", kind="entry", width=20,
                  hint="e.g. magm, esto — used when automatic is off; first one first"); r += 1
        self._row(f, r, "Pre-attack spell", "pre_attack_spell", kind="entry", width=12,
                  hint="cast once as each fight opens (PreAttack button)"); r += 1
        self._row(f, r, "Cast late in the round", "late_round_spells", kind="entry", width=12,
                  hint="partial-round spells (e.g. slep): held for the last 2 s of the round so they last"); r += 1
        self._row(f, r, "Dangerous fight: curse first", "danger_opener_spell", kind="entry", width=12,
                  hint="e.g. mist — only when the fight looks dangerous (blank = off)"); r += 1
        dg = ttk.Frame(f)
        dg.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Label(dg, text="   Dangerous = expected damage ≥").pack(side="left")
        ttk.Spinbox(dg, from_=10, to=200, width=4, textvariable=self._var("danger_opener_pct")).pack(side="left", padx=4)
        ttk.Label(dg, text="% of my HP, or ≥").pack(side="left")
        ttk.Spinbox(dg, from_=0, to=20, width=3, textvariable=self._var("danger_opener_mobs")).pack(side="left", padx=4)
        ttk.Label(dg, text="monsters, or a boss").pack(side="left")
        self._check(dg, "danger_big_spells", "…and use the hardest-hitting spells").pack(side="left", padx=12)
        self._row(f, r, "Area spell", "multi_spell", kind="entry", width=12,
                  hint="blank = best area spell I know"); r += 1
        af = ttk.Frame(f)
        af.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(af, "use_area_min", "Use area spells when there are at least").pack(side="left")
        ttk.Spinbox(af, from_=2, to=20, width=4, textvariable=self._var("multi_min_mobs")).pack(side="left", padx=4)
        ttk.Label(af, text="monsters (fewer = single-target spells only; unticked = never)",
                  style="Muted.TLabel").pack(side="left")
        ttk.Label(f, text="Area spells are cast with no target (fbal, msto, mist, esto, swar…). The Nuke button switches "
                          "area spells on/off, the Cast button single-target ones.",
                  style="Muted.TLabel").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "aoe_safety", "No area spells while a player outside my party is in the room, while I'm "
                    "not sure who's here, or just after the party breaks up").grid(row=r, column=0, columnspan=3,
                                                                                  sticky="w"); r += 1
        return f

    def _spells_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        f.columnconfigure(1, weight=1)
        r = 0
        self._check(f, "auto_spells", "Choose spells automatically from every attack spell I know").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        kf = ttk.Frame(f)
        kf.grid(row=r, column=0, columnspan=3, sticky="we", pady=(0, 4)); r += 1
        self.sp_known = ttk.Label(kf, text="", style="Muted.TLabel", wraplength=470, justify="left")
        self.sp_known.pack(side="left", fill="x", expand=True)
        ttk.Button(kf, text="Re-read spells", command=self.reread_spells).pack(side="right")
        ttk.Label(f, text="Pick by").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self._var("spell_pick"), values=("damage", "damage per mana"), width=16,
                     state="readonly").grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="damage = strongest spell that works on the mob", style="Muted.TLabel").grid(
            row=r, column=2, sticky="w", padx=8); r += 1
        self._check(f, "spell_efficiency", "Spell efficiency: start on the hardest spell, dial back to a cheaper one "
                    "when I'm doing nearly all the damage and it kills just as fast").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        se = ttk.Frame(f)
        se.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Label(se, text="…at most").pack(side="left", padx=(20, 0))
        ttk.Spinbox(se, from_=0, to=6, width=3, textvariable=self._var("spell_eff_max_steps")).pack(side="left", padx=4)
        ttk.Label(se, text="steps down, never to a spell doing under").pack(side="left")
        ttk.Spinbox(se, from_=0, to=100, width=4, textvariable=self._var("spell_eff_floor_pct")).pack(side="left", padx=4)
        ttk.Label(se, text="% of the hardest one's damage").pack(side="left")
        self._row(f, r, "Cheapest spell for monsters under", "spell_cheap_below_exp", to=10_000_000,
                  hint="exp a kill — trash gets the cheap spell, the big one is for what's worth it (0 = off)"); r += 1
        self._row(f, r, "Extra spells (optional)", "attack_spells", kind="entry", width=30,
                  hint="only if a spell isn't in your list"); r += 1
        self._row(f, r, "Cast command", "cast_cmd", kind="entry", width=20, hint="{short} {target}"); r += 1
        self._row(f, r, "Character level", "char_level", to=255, hint="0 = spell cap"); r += 1
        self._row(f, r, "Spellcasting", "spellcasting", to=500, hint="0 = assume always lands"); r += 1
        self._row(f, r, "Spell damage bonus %", "spell_dmg_bonus", to=300); r += 1
        self._row(f, r, "Switch below % of rated", "spell_min_pct", to=100); r += 1
        self._row(f, r, "Keep mana in reserve", "spell_mana_reserve", to=999); r += 1
        self._check(f, "spell_fallback_melee", "Melee when no spell is effective enough").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        scf = ttk.Frame(f)
        scf.grid(row=r, column=0, columnspan=3, sticky="we"); r += 1
        self._check(scf, "auto_scrolls", "After a level-up, buy and read scrolls for spells I can now learn "
                    "(shops near the loop, cash on hand)").pack(side="left")
        ttk.Button(scf, text="Look for scrolls now", command=self.look_for_scrolls).pack(side="right")
        ttk.Label(f, text="Attack, pre-attack and area spells are on the Combat tab.", style="Muted.TLabel").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Label(f, text="Against mobs in this room", style="Head.TLabel").grid(
            row=r, column=0, sticky="w", pady=(12, 4)); r += 1
        cols = ("spell", "elem", "rated", "vs", "pct", "src")   # spell, element, rated, vs this room, %, single/area
        self.sp_tree = ttk.Treeview(f, columns=cols, show="headings", height=9)
        for c, w, t in zip(cols, (150, 70, 55, 60, 50, 110),
                           ("Spell", "Element", "Rated", "Vs room", "%", "How")):
            self.sp_tree.heading(c, text=t)
            self.sp_tree.column(c, width=w)
        self.sp_tree.tag_configure("bad", foreground="#ff6b6b")
        self.sp_tree.tag_configure("good", foreground="#a9b4c4")
        self.sp_tree.tag_configure("pick", foreground="#5cff7a")
        self.sp_tree.grid(row=r, column=0, columnspan=3, sticky="nsew"); r += 1
        f.rowconfigure(r - 1, weight=1)
        self.sp_info = ttk.Label(f, text="", style="Muted.TLabel", wraplength=420)
        self.sp_info.grid(row=r, column=0, columnspan=3, sticky="w", pady=6)
        self._sp_key = None
        return f

    def _sync_vars(self):
        st = self.s.settings
        for key, var in self._vars.items():
            val = getattr(st, key)
            try:
                if var.get() != (", ".join(val) if isinstance(val, list) else val):
                    var.set(", ".join(val) if isinstance(val, list) else val)
            except tk.TclError:
                pass
        self.refresh_buffs()
        self.refresh_remote()

    # ------------------------------------------------------------------ windows

    def show_tab(self, i):
        nb = self.map.master.master          # (0.8.201: the map sits in a box inside the notebook; .master alone
        # was that box, so Options → Map / Paths / Bosses / Stats did nothing)
        names = ["Map", "Paths", "Combat", "Spells", "Bless", "Events", "Chat", "Bosses", "Remote", "Stats", "Log"]
        name = names[i] if isinstance(i, int) and i < len(names) else i
        if name in SETTINGS_TABS or name in ("Remote",):
            self.open_settings("Talk" if name == "Remote" else name)
            return
        if name == "Chat" and self.s.settings.dock_chat:
            self.docked_chat.entry.focus_set()
            return
        for tab in nb.tabs():
            if nb.tab(tab, "text") == name:
                nb.select(tab)
                return

    def _build_settings(self):
        w = tk.Toplevel(self.root)
        w.title("MudPilot — Settings")
        from .windows import tie_to_main
        tie_to_main(self, w, "Settings")
        w.configure(background=PANEL)
        w.geometry("1000x760")
        w.protocol("WM_DELETE_WINDOW", w.withdraw)
        w.withdraw()
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        builders = {"General": self._general_tab, "BBS": self._bbs_tab, "Health": self._health_tab,
                    "Combat": self._combat_tab, "Spells": self._heal_spells_tab, "Attack spells": self._spells_tab,
                    "Auto-roam": self._roam_tab, "Responses": self._responses_tab, "Bless": self._bless_tab,
                    "Loot": self._loot_tab, "PvP": self._pvp_tab, "Party": self._party_tab, "Other": self._other_tab, "Talk": self._remote_tab, "Events": self._events_tab,
                    "Phone alerts": self._alerts_tab}
        self.settings_tabs = {}
        for name in SETTINGS_TABS:
            t = self._scrolled(nb, builders[name])
            nb.add(t, text=name)
            self.settings_tabs[name] = t
        b = ttk.Frame(w)
        b.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(b, text="Changes apply right away and are saved to this character.", style="Muted.TLabel").pack(side="left")
        ttk.Button(b, text="Close", style="Accent.TButton", command=w.withdraw).pack(side="right")
        self.settings_win, self.settings_nb = w, nb

    def _scrolled(self, nb, builder):
        """Put a settings page in a scrollable area so long tabs never get cut off."""
        outer = ttk.Frame(nb)
        cv = tk.Canvas(outer, background=PANEL, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        inner = builder(cv)
        win = cv.create_window(0, 0, window=inner, anchor="nw")

        def fit(e=None):
            cv.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight()))
            cv.itemconfigure(win, width=max(cv.winfo_width(), inner.winfo_reqwidth()))
            need = inner.winfo_reqheight() > cv.winfo_height() + 2
            if need and not sb.winfo_ismapped():
                sb.pack(side="right", fill="y")
            elif not need and sb.winfo_ismapped():
                sb.pack_forget()
        inner.bind("<Configure>", fit)
        cv.bind("<Configure>", fit)

        def wheel(e):
            if inner.winfo_reqheight() > cv.winfo_height():
                cv.yview_scroll(-1 if (e.delta > 0 or getattr(e, "num", 0) == 4) else 1, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            cv.bind_all(seq, lambda e: wheel(e) if str(e.widget).startswith(str(outer)) else None, add="+")
        cv.pack(side="left", fill="both", expand=True)
        return outer

    def open_settings(self, tab=None):
        try:
            gone = not self.settings_win.winfo_exists()
        except tk.TclError:
            gone = True
        if gone:
            # destroyed (adding an item bless rebuilds it): build it again — Buddy, 2026-10-29: Settings did
            # nothing at all, every click 'bad window path name .!toplevel2'
            self._build_settings()
        w = self.settings_win
        if self.root.state() == "iconic":
            self.root.deiconify()
        self.root.lift()                             # its own MudPilot right behind it
        w.deiconify()
        w.lift()
        if tab and tab in self.settings_tabs:
            self.settings_nb.select(self.settings_tabs[tab])
        self._sp_key = None
        self.refresh_spell_table()

    def _heal_spells_tab(self, nb):
        """MegaMUD's Spells tab: healing / regeneration, cures and other spells."""
        f = ttk.Frame(nb, padding=12)
        hl = ttk.LabelFrame(f, text="Healing / regeneration", padding=8)
        hl.grid(row=0, column=0, sticky="nsew")
        ot = ttk.LabelFrame(f, text="Other spells", padding=8)
        ot.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        rows = (("Minor heal", "heal_cmd", "heal_pct"), ("Major heal", "major_heal_cmd", "major_heal_pct"))
        ttk.Label(hl, text="spell", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(hl, text="below HP %", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        for i, (lbl, k, pk) in enumerate(rows, start=1):
            ttk.Label(hl, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(hl, textvariable=self._var(k), width=12).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Spinbox(hl, from_=1, to=100, width=5, textvariable=self._var(pk)).grid(row=i, column=2, sticky="w")
        for i, (lbl, k, hint) in enumerate((("HP regen", "hp_regen_cmd", "cast when you rest"),
                                            ("Mana regen", "ma_regen_cmd", "cast when you meditate"),
                                            ("When HP full", "hp_full_cmd", "cast once at full HP"),
                                            ("When mana full", "ma_full_cmd", "cast once at full mana")), start=3):
            ttk.Label(hl, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(hl, textvariable=self._var(k), width=12).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Label(hl, text=hint, style="Muted.TLabel").grid(row=i, column=2, sticky="w")
        ttk.Label(hl, text="Max attack casts").grid(row=7, column=0, sticky="w", pady=(8, 2))
        ttk.Spinbox(hl, from_=0, to=99, width=5, textvariable=self._var("max_off_casts")).grid(row=7, column=1, sticky="w", padx=4)
        ttk.Label(hl, text="per fight, then melee (0 = no limit)", style="Muted.TLabel").grid(row=7, column=2, sticky="w")
        for i, (lbl, k) in enumerate((("Cure blindness", "cure_blind_cmd"), ("Cure poison", "cure_poison_cmd"),
                                      ("Cure disease", "cure_disease_cmd"), ("Freedom", "freedom_cmd"),
                                      ("Room light", "light_cmd"))):
            ttk.Label(ot, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(ot, textvariable=self._var(k), width=14).grid(row=i, column=1, sticky="w", padx=4)
        for j, (k, t) in enumerate((("cures_first", "Cures before minor heal"), ("ignore_poison", "Ignore poison"),
                                    ("ignore_blindness", "Ignore blindness"), ("ignore_confusion", "Ignore confusion"),
                                    ("party_cures", "Cure party members too (poison from 'par', '@blind' etc.)"),
                                    ("report_conditions", "In a party, say '@blind' / '@held' when I can't cure it"))):
            self._check(ot, k, t).grid(row=6 + j, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Type the spell's short command (mihe, mahe, cure…). Heals are cast when the Heal button is on; "
                          "cures when the game says you're poisoned, blind, diseased or held. Bless spells and their "
                          "timers are on the Bless tab; party heals on the Party tab.",
                  style="Muted.TLabel", wraplength=700, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        return f

    def _responses_tab(self, nb):
        """Messages / Responses: team commands like 'br nuke', 'br bs Bob' — and track alerts."""
        f = ttk.Frame(nb, padding=10)
        top = ttk.Frame(f)
        top.pack(fill="x")
        self._check(top, "responses_on", "Answer messages with responses").pack(side="left")
        ttk.Label(f, text="When a message matches, MudPilot sends the response. * matches one word ({1}, {2}…). "
                          "Specials: #nuke (strongest area spell), #attack {1}, #hold (stay put until @ok), #hangup. "
                          "From: team = your party, Friends and Talk-tab players.",
                  style="Muted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(4, 6))
        cols = ("on", "match", "channels", "from", "do")
        self.rs_tree = ttk.Treeview(f, columns=cols, show="headings", height=9)
        for c, t, w in (("on", "On", 40), ("match", "Message", 150), ("channels", "Heard on", 220),
                        ("from", "From", 100), ("do", "Response", 300)):
            self.rs_tree.heading(c, text=t)
            self.rs_tree.column(c, width=w, anchor="w")
        self.rs_tree.pack(fill="x")
        self.rs_tree.bind("<Double-1>", lambda e: self._rs_edit())
        b = ttk.Frame(f)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="Add…", style="Accent.TButton", command=lambda: self._rs_edit(new=True)).pack(side="left")
        ttk.Button(b, text="Edit…", command=self._rs_edit).pack(side="left", padx=4)
        ttk.Button(b, text="On/Off", command=self._rs_toggle).pack(side="left")
        ttk.Button(b, text="Remove", command=self._rs_remove).pack(side="left", padx=4)
        ttk.Button(b, text="Add the starter set", command=self._rs_starters).pack(side="left")
        tr = ttk.LabelFrame(f, text="Track alerts", padding=8)
        tr.pack(fill="x", pady=(8, 0))
        self._check(tr, "track_alert", "When my tracking finds players (not friends/party), tell the team").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(tr, text="Tell them on").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(tr, textvariable=self._var("track_alert_channel"), values=("broadcast", "gangpath", "say", "party"),
                     width=12, state="readonly").grid(row=1, column=1, sticky="w", padx=4)
        self._check(tr, "track_hangup", "…and hang up myself").grid(row=1, column=2, sticky="w", padx=10)
        self._row(tr, 2, "Message", "track_alert_msg", kind="entry", width=40, hint="{names} {room} {roomname}")
        self._row(tr, 3, "Track pattern", "track_pattern", kind="entry", width=40,
                  hint="blank = built in; a regex whose group is the name")
        self._rs_fill()
        return f

    def _rs_fill(self):
        if not hasattr(self, "rs_tree"):
            return
        self.rs_tree.delete(*self.rs_tree.get_children())
        for i, r in enumerate(self.s.responses.rules()):
            self.rs_tree.insert("", "end", iid=str(i), values=("✓" if r.get("enabled", True) else "", r.get("match", ""),
                                                             r.get("channels", ""), r.get("from", "team"), r.get("do", "")))

    def _rs_sel(self):
        s = self.rs_tree.selection()
        return int(s[0]) if s else None

    def _rs_toggle(self):
        i = self._rs_sel()
        if i is not None:
            r = self.s.responses.rules()[i]
            r["enabled"] = not r.get("enabled", True)
            self.s.settings.save()
            self._rs_fill()

    def _rs_remove(self):
        i = self._rs_sel()
        if i is not None:
            del self.s.responses.rules()[i]
            self.s.settings.save()
            self._rs_fill()

    def _rs_starters(self):
        from .responses import DEFAULT_RESPONSES
        have = {r.get("match", "").lower() for r in self.s.responses.rules()}
        for r in DEFAULT_RESPONSES:
            if r["match"].lower() not in have:
                self.s.responses.rules().append(dict(r))
        self.s.settings.save()
        self._rs_fill()

    def _rs_edit(self, new=False):
        from .responses import CHANNELS
        rules = self.s.responses.rules()
        i = None if new else self._rs_sel()
        if not new and i is None:
            return
        r = dict(rules[i]) if i is not None else {"enabled": True, "match": "", "channels": "broadcast,gangpath,telepath",
                                                   "from": "team", "do": ""}
        d = tk.Toplevel(self.root)
        d.title("Response")
        d.configure(background=PANEL)
        d.transient(self.settings_win)
        fr = ttk.Frame(d, padding=14)
        fr.pack()
        mv, fv, dv = tk.StringVar(value=r["match"]), tk.StringVar(value=r.get("from", "team")), tk.StringVar(value=r["do"])
        ttk.Label(fr, text="Message").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(fr, textvariable=mv, width=30).grid(row=0, column=1, sticky="w")
        ttk.Label(fr, text="e.g. nuke  ·  bs *  ·  attack *", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(fr, text="Heard on").grid(row=1, column=0, sticky="w", pady=3)
        chs = {c.strip() for c in r.get("channels", "").split(",")}
        cvars = {}
        cf = ttk.Frame(fr)
        cf.grid(row=1, column=1, columnspan=2, sticky="w")
        for c in CHANNELS:
            cvars[c] = tk.BooleanVar(value=c in chs or "any" in chs)
            ttk.Checkbutton(cf, text="game line" if c == "game" else c, variable=cvars[c]).pack(side="left", padx=(0, 6))
        ttk.Label(fr, text="From").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(fr, textvariable=fv, values=("team", "anyone"), width=28).grid(row=2, column=1, sticky="w")
        ttk.Label(fr, text="team, anyone, or names: Bob, Jim", style="Muted.TLabel").grid(row=2, column=2, sticky="w", padx=8)
        ttk.Label(fr, text="Response").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(fr, textvariable=dv, width=30).grid(row=3, column=1, sticky="w")
        ttk.Label(fr, text="e.g. #nuke  ·  bs {1}  ·  sn^Mhide", style="Muted.TLabel").grid(row=3, column=2, sticky="w", padx=8)

        def ok():
            if not mv.get().strip() or not dv.get().strip():
                return
            if fv.get().strip().lower() == "anyone" and not messagebox.askyesno(
                    "Response", "Anyone on the board could trigger this. Are you sure?", parent=d):
                return
            r.update(match=mv.get().strip(), do=dv.get().strip(), **{"from": fv.get().strip() or "team"},
                     channels=",".join(c for c, v in cvars.items() if v.get()) or "broadcast")
            if i is None:
                rules.append(r)
            else:
                rules[i] = r
            self.s.settings.save()
            self._rs_fill()
            d.destroy()
        b = ttk.Frame(fr)
        b.grid(row=4, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")

    def _roam_tab(self, nb):
        """MegaMUD's Auto-roam: which exits to wander through, which doors to open, room commands."""
        f = ttk.Frame(nb, padding=12)
        grid = (("NW", 0, 0), ("N", 0, 1), ("NE", 0, 2), ("W", 1, 0), ("E", 1, 2), ("SW", 2, 0), ("S", 2, 1), ("SE", 2, 2))
        self.roam_vars = {}
        for col, (title, key) in enumerate((("Move", "roam_dirs"), ("Open doors", "roam_open_dirs"))):
            lf = ttk.LabelFrame(f, text=title, padding=8)
            lf.grid(row=0, column=col, sticky="n", padx=(0, 10))
            cur = {d.upper() for d in getattr(self.s.settings, key) or []}
            for d, r, c in grid + (("U", 0, 4), ("D", 2, 4)):
                v = tk.BooleanVar(value=d in cur)
                self.roam_vars[(key, d)] = v
                ttk.Checkbutton(lf, text=d, variable=v, command=lambda k=key: self._roam_save(k)).grid(row=r, column=c, padx=2, pady=2)
        sr = ttk.LabelFrame(f, text="Special rooms", padding=8)
        sr.grid(row=0, column=2, sticky="nsew")
        f.columnconfigure(2, weight=1)
        ttk.Label(sr, text="One per line:  map/room = commands   e.g.  3/606 = ring bell^Mn",
                  style="Muted.TLabel").pack(anchor="w")
        self.roam_text = tk.Text(sr, height=8, width=40, background="#0f1318", foreground=TEXT, insertbackground=TEXT,
                                 borderwidth=0, font=("Consolas", 10))
        self.roam_text.pack(fill="both", expand=True, pady=4)
        self.roam_text.insert("1.0", "\n".join(f"{x.get('room')} = {x.get('cmd')}" for x in self.s.settings.roam_rooms or []))
        self.roam_text.bind("<FocusOut>", lambda e: self._roam_rooms_save())
        b = ttk.Frame(f)
        b.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(b, text="Start auto-roaming", style="Accent.TButton", command=self.start_roam).pack(side="left")
        ttk.Button(b, text="Stop", command=self.stop_bot).pack(side="left", padx=6)
        ttk.Label(f, text="Auto-roam wanders through the ticked exits (never straight back unless it's the only way), "
                          "fighting, resting and looting as usual. General tab → Default task can start it on connect.",
                  style="Muted.TLabel", wraplength=700, justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        return f

    def _roam_save(self, key):
        setattr(self.s.settings, key, [d for (k, d), v in self.roam_vars.items() if k == key and v.get()])
        self.s.settings.save()

    def _roam_rooms_save(self):
        rows = []
        for line in self.roam_text.get("1.0", "end").splitlines():
            if "=" in line:
                room, cmd = line.split("=", 1)
                if room.strip() and cmd.strip():
                    rows.append({"room": room.strip(), "cmd": cmd.strip()})
        self.s.settings.roam_rooms = rows
        self.s.settings.save()

    def start_roam(self):
        if self.s.bot.walking:
            self.s.bot.stop("Stopped: auto-roam")
        self.s.bot.x.start_roam()

    def _general_tab(self, nb):
        f = ttk.Frame(nb, padding=12)
        st = self.s.settings
        lf = ttk.LabelFrame(f, text="Initial", padding=10)
        lf.pack(fill="x")
        self.task_var = tk.StringVar(value=st.default_task)
        ttk.Radiobutton(lf, text="Do nothing", variable=self.task_var, value="nothing",
                        command=self._set_task).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(lf, text="Begin looping at", variable=self.task_var, value="loop",
                        command=self._set_task).grid(row=1, column=0, sticky="w")
        self.task_loop = ttk.Combobox(lf, textvariable=self._var("default_loop"), width=28,
                                      values=sorted(p.title for p in self.s.paths if p.is_loop))
        self.task_loop.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Radiobutton(lf, text="Begin auto-roaming", variable=self.task_var, value="roam",
                        command=self._set_task).grid(row=2, column=0, sticky="w")
        self._check(lf, "auto_connect", "Auto-connect when MudPilot opens").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._check(lf, "ignore_mode_defaults", "Ignore manual/auto mode defaults").grid(row=4, column=0, columnspan=2, sticky="w")
        self._check(lf, "backup_settings", "Back up settings files when making changes").grid(row=5, column=0, columnspan=2, sticky="w")
        self._check(lf, "show_toolbar", "Show the quick-button toolbar").grid(row=6, column=0, columnspan=2, sticky="w")
        self._check(lf, "update_check", "Check for a new MudPilot when it opens (asks GitHub; nothing about you is sent)").grid(
            row=99, column=0, columnspan=2, sticky="w")
        self._check(lf, "toolbar_icons", "Icon buttons like MegaMUD (off = text buttons; takes effect next start)").grid(
            row=7, column=0, columnspan=2, sticky="w")
        wc = ttk.Frame(lf)
        wc.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(wc, text="Window colour").pack(side="left")
        cb = ttk.Combobox(wc, textvariable=self._var("window_colour"), width=12, state="readonly",
                          values=["auto"] + [n for n, _c in WINDOW_COLOURS])
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.root.after(50, self._window_colour))
        ttk.Label(wc, text="a dull colour per MudPilot window, so you can tell them apart (auto = by data folder)",
                  style="Muted.TLabel").pack(side="left")
        ttk.Label(f, text="Manual mode = you're driving. Auto mode = walking a path or loop. The quick buttons switch "
                          "to that mode's defaults when a loop starts or stops; flip a button any time to override.",
                  style="Muted.TLabel", wraplength=700).pack(anchor="w", pady=(10, 4))
        row = ttk.Frame(f)
        row.pack(fill="both", expand=True)
        self.mode_vars = {}
        for mode, title in (("manual", "Manual-Mode Defaults"), ("auto", "Auto-Mode Defaults")):
            box = ttk.LabelFrame(row, text=title, padding=8)
            box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            d = st.mode_defaults.setdefault(mode, {})
            for key, label, _tip in QUICK_BUTTONS:
                if key in MODE_DEFAULT_SKIP:
                    continue                          # NoHang is for the moment you flip it — never a mode default
                v = tk.BooleanVar(value=d.get(key, key not in ("auto_light", "auto_sneak", "auto_hide", "auto_search",
                                                       "hangup_on_player")))
                d.setdefault(key, v.get())
                v.trace_add("write", lambda *a, m=mode, k=key, v=v: self._set_mode_default(m, k, v))
                ttk.Checkbutton(box, text=f"Auto-{label}", variable=v).pack(anchor="w")
                self.mode_vars[(mode, key)] = v
        sy = ttk.LabelFrame(f, text="Sync between PCs", padding=8)
        sy.pack(fill="x", pady=(10, 0))
        r1 = ttk.Frame(sy)
        r1.pack(fill="x")
        ttk.Label(r1, text="Shared folder").pack(side="left")
        fv = tk.StringVar(value=self.s.sync.folder)
        ent = ttk.Entry(r1, textvariable=fv, width=50)
        ent.pack(side="left", padx=4)
        res = ttk.Label(sy, text=self.s.sync.last or ("off — pick a folder both PCs can see (OneDrive, Dropbox, a network share)"
                                                    if not self.s.sync.folder else ""), style="Muted.TLabel")

        def setf(*a):
            self.s.sync.set_folder(fv.get())
            res.configure(text="saved — this PC syncs through that folder" if fv.get().strip() else "sync off")
        ent.bind("<FocusOut>", setf)
        ent.bind("<Return>", setf)

        def browse():
            from tkinter import filedialog
            p = filedialog.askdirectory(parent=sy, title="Folder both PCs can see")
            if p:
                fv.set(p)
                setf()

        def now():
            setf()
            res.configure(text=self.s.sync.sync_now())
        ttk.Button(r1, text="Browse…", command=browse).pack(side="left")
        ttk.Button(r1, text="Sync now", style="Accent.TButton", command=now).pack(side="left", padx=6)
        res.pack(anchor="w", pady=(4, 0))
        ttk.Label(sy, text="Characters, settings, macros, paths, players, and what it's learned (lair times, loop stats, "
                           "bosses, history) — learned data is merged so neither PC loses anything. Passwords stay in "
                           "each PC's Credential Manager. Syncs at start, every 30 min and on close. Set the same "
                           "folder on each PC.", style="Muted.TLabel", wraplength=720, justify="left").pack(anchor="w")
        return f

    def _window_colour(self):
        """Each MudPilot window its own dull colour (Dan: hunting for the right window) — the title bar on Windows 11,
        and a strip across the top of the window everywhere."""
        name = (self.s.settings.window_colour or "").strip().lower()
        cols = dict(WINDOW_COLOURS)
        if name not in cols:
            import zlib
            name = WINDOW_COLOURS[zlib.crc32(os.path.basename(os.path.normpath(config.DATA_DIR)).lower().encode())
                                  % len(WINDOW_COLOURS)][0]
        col = cols[name]
        if not hasattr(self, "_colour_strip"):
            self._colour_strip = tk.Frame(self.root, height=5, background=col)
            first = self.root.pack_slaves()
            self._colour_strip.pack(fill="x", side="top", before=first[0] if first else None)
        self._colour_strip.configure(background=col)
        if os.name == "nt":
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                r, g, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
                for attr, val in ((35, r | (g << 8) | (b << 16)), (36, 0x00E6E6E6)):   # caption, caption text
                    v = ctypes.c_int(val)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass                                   # Windows 10: no title bar colour — the strip still shows

    # ------------------------------------------------------------ toolbar order (drag a button to move it)
    def _toolbar_keys(self):
        """The toggle buttons in your order (Settings: toolbar_order); any new ones go on the end."""
        default = [k for k, _l, _t in QUICK_BUTTONS]
        saved = [k for k in (getattr(self.s.settings, "toolbar_order", None) or []) if k in default]
        return saved + [k for k in default if k not in saved]

    def _toolbar_pack(self):
        for b in self.quick.values():
            b.pack_forget()
        icons = bool(self.s.settings.toolbar_icons)
        for k in self._toolbar_keys():
            b = self.quick.get(k)
            if b is not None:
                b.pack(side="left", padx=1 if icons else 2)

    def _toolbar_drag_bind(self, b, key):
        def press(e):
            self._tb_drag = {"key": key, "x": e.x_root, "moved": False}
        def motion(e):
            d = getattr(self, "_tb_drag", None)
            if d and abs(e.x_root - d["x"]) > 8:
                d["moved"] = True
                b.configure(cursor="sb_h_double_arrow")
        def release(e):
            d, self._tb_drag = getattr(self, "_tb_drag", None), None
            b.configure(cursor="hand2")
            if not d or not d["moved"]:
                return None                        # a click: the button switches as usual
            keys = self._toolbar_keys()
            keys.remove(key)
            pos = len(keys)
            for i, k in enumerate(keys):
                w = self.quick[k]
                if e.x_root < w.winfo_rootx() + w.winfo_width() / 2:
                    pos = i
                    break
            keys.insert(pos, key)
            self.s.settings.toolbar_order = keys
            self.s.settings.save()
            self._toolbar_pack()
            return "break"                         # a drag doesn't switch it
        b.bind("<ButtonPress-1>", press, add="+")
        b.bind("<B1-Motion>", motion, add="+")
        b.bind("<ButtonRelease-1>", release)
        b.bind("<Button-3>", self._toolbar_menu)

    def _toolbar_menu(self, e):
        m = tk.Menu(self.root, tearoff=False)
        m.add_command(label="Drag a button left or right to move it", state="disabled")
        m.add_command(label="Reset to default order", command=self._toolbar_reset)
        m.tk_popup(e.x_root, e.y_root)

    def _toolbar_reset(self):
        self.s.settings.toolbar_order = []
        self.s.settings.save()
        self._toolbar_pack()
        self.add_log("Toolbar buttons back in their default order")

    def _toolbar_vis(self):
        if not hasattr(self, "toolbar"):
            return
        if self.s.settings.show_toolbar:
            if not self.toolbar.winfo_ismapped():
                self.toolbar.pack(fill="x", padx=8, pady=(0, 6), before=self._info_row)
        else:
            self.toolbar.pack_forget()

    def _set_task(self):
        self.s.settings.default_task = self.task_var.get()
        self.s.settings.save()

    def _set_mode_default(self, mode, key, v):
        self.s.settings.mode_defaults.setdefault(mode, {})[key] = bool(v.get())
        self.s.settings.save()

    def _bbs_tab(self, nb):
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(1, weight=1)
        r = 0
        self._row(f, r, "BBS host", "host", kind="entry", width=28, hint="name or IP, no telnet://"); r += 1
        self._row(f, r, "Port", "port", to=65535, hint="usually 23"); r += 1
        self._row(f, r, "User-ID", "username", kind="entry", width=20); r += 1
        self._check(f, "auto_reconnect", "Reconnect automatically if the line drops").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Reconnect after (sec)", "reconnect_delay", to=3600,
                  hint="and again this often, for as long as MudPilot is open"); r += 1
        self._row(f, r, "Line is dead after (sec)", "dead_line_secs", to=900,
                  hint="sent a command and the board said nothing — drop and reconnect (0 = off)"); r += 1
        self._check(f, "resume_after_reconnect", "After reconnecting, carry on with the loop/path it was on "
                    "(never after a hang-up)").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._check(f, "reinvite_after_reconnect", "Back in after a drop or hang-up: invite whoever was in my party "
                    "(they get the @join telepath)").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self._row(f, r, "Room-number command", "locate_cmd", kind="entry", width=10, hint="sent when unsure of the room (blank = off)"); r += 1
        self._row(f, r, "Username prompt", "user_prompt", kind="entry", width=40,
                  hint="paste the line, e.g. Please enter your username or \"new\":  (blank = usual ones)"); r += 1
        self._row(f, r, "Password prompt", "pass_prompt", kind="entry", width=40,
                  hint="paste the line (blank = usual ones)"); r += 1
        lg = ttk.LabelFrame(f, text="Logon steps — when this text appears, type that (Enter is added for you)", padding=8)
        lg.grid(row=50, column=0, columnspan=3, sticky="we", pady=(10, 0))
        self._logon_frame_row = r + 1
        ttk.Label(lg, text="When you see", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(lg, text="Type", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(lg, text="Every time", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        self.logon_vars = []
        cur = list(self.s.settings.logon_steps or [])
        for i in range(6):
            d = cur[i] if i < len(cur) else {}
            mv, sv, ev = tk.StringVar(value=d.get("match", "")), tk.StringVar(value=d.get("send", "")), \
                tk.BooleanVar(value=bool(d.get("every")))
            ttk.Entry(lg, textvariable=mv, width=42).grid(row=i + 1, column=0, sticky="w", pady=1)
            ttk.Entry(lg, textvariable=sv, width=16).grid(row=i + 1, column=1, sticky="w", padx=6)
            ttk.Checkbutton(lg, variable=ev).grid(row=i + 1, column=2)
            for v in (mv, sv, ev):
                v.trace_add("write", lambda *a: self._logon_save())
            self.logon_vars.append((mv, sv, ev))
        lb = ttk.Frame(lg)
        lb.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(lb, text="Paradigm: pick P at the menu", command=self._logon_paradigm).pack(side="left")
        ttk.Label(lb, text="  e.g. Please enter your selection:  →  P   ·   ^M between commands sends several lines",
                  style="Muted.TLabel").pack(side="left")
        er = ttk.Frame(lg)
        er.grid(row=9, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(er, text="Enter the realm at", variable=self._var("auto_enter_realm")).pack(side="left")
        ttk.Entry(er, textvariable=self._var("enter_realm_prompt"), width=14).pack(side="left", padx=4)
        ttk.Label(er, text="by typing").pack(side="left")
        ttk.Entry(er, textvariable=self._var("enter_realm_cmd"), width=4).pack(side="left", padx=4)
        ttk.Label(er, text="— not after a hang-up (then you type it)", style="Muted.TLabel").pack(side="left")
        ttk.Label(f, text="Password").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        pwf = ttk.Frame(f)
        pwf.grid(row=r, column=1, columnspan=2, sticky="w"); r += 1
        st = self.s.settings
        self.bbs_pw = tk.StringVar(value=config.get_password(st.username, st.host) or "")
        self.bbs_pw_entry = ttk.Entry(pwf, textvariable=self.bbs_pw, width=24, show="•" if st.hide_password else "")
        self.bbs_pw_entry.pack(side="left")
        self.bbs_lock = ttk.Button(pwf, width=8, command=self._toggle_pw_lock)
        self.bbs_lock.pack(side="left", padx=6)
        self.bbs_pw_note = ttk.Label(pwf, text="", style="Muted.TLabel")
        self.bbs_pw_note.pack(side="left")
        self._pw_after = None
        self.bbs_pw.trace_add("write", lambda *a: self._pw_changed())
        for k in ("username", "host"):
            self._var(k).trace_add("write", lambda *a: self.root.after(700, self._pw_reload))
        self._toggle_pw_lock(init=True)
        ttk.Label(f, text="Typed into the login prompt for you. Stored in Windows Credential Manager (encrypted), not in "
                          "MudPilot's files. The lock just hides it on screen.",
                  style="Muted.TLabel", wraplength=560, justify="left").grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        return f

    def _logon_save(self):
        rows = []
        for mv, sv, ev in self.logon_vars:
            if mv.get().strip() and sv.get().strip():
                rows.append({"match": mv.get().strip(), "send": sv.get().strip(), "every": bool(ev.get())})
        self.s.settings.logon_steps = rows
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, self.s.settings.save)

    def _logon_paradigm(self):
        for mv, sv, ev in self.logon_vars:
            if mv.get().strip().lower() == "please enter your selection:":
                return
        for mv, sv, ev in self.logon_vars:
            if not mv.get().strip():
                mv.set("Please enter your selection:")
                sv.set("P")
                return

    def _toggle_pw_lock(self, init=False):
        st = self.s.settings
        if not init:
            st.hide_password = not st.hide_password
            st.save()
        self.bbs_pw_entry.configure(show="•" if st.hide_password else "")
        self.bbs_lock.configure(text="🔒 Show" if st.hide_password else "🔓 Hide")

    def _pw_reload(self):
        st = self.s.settings
        pw = config.get_password(st.username, st.host) or ""
        if pw != self.bbs_pw.get():
            self._pw_loading = True
            self.bbs_pw.set(pw)
            self._pw_loading = False

    def _pw_changed(self):
        if getattr(self, "_pw_loading", False):
            return
        if self._pw_after:
            self.root.after_cancel(self._pw_after)
        self._pw_after = self.root.after(800, self._pw_save)

    def _pw_save(self):
        st = self.s.settings
        pw = self.bbs_pw.get()
        self.s.password = pw or None
        if not st.username:
            self.bbs_pw_note.configure(text="set the User-ID first")
            return
        ok = config.set_password(st.username, pw or None, st.host)
        st.save_password = bool(pw)
        st.save()
        self.bbs_pw_note.configure(text="saved" if ok else "couldn't save (keyring missing) — used for this session only")

    def _health_tab(self, nb):
        """MegaMUD layout: mana on the left, health on the right. Each % shows what it is right now
        (e.g. 40% = 187 MA · 2 casts of eart), so you can make sure you can still area-cast 3 times."""
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        self._pct_labels = []
        ma = ttk.LabelFrame(f, text="Mana", padding=8)
        ma.grid(row=0, column=0, sticky="nsew")
        hp = ttk.LabelFrame(f, text="Health", padding=8)
        hp.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        def pct_row(parent, r, label, key, kind):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            ttk.Spinbox(parent, from_=0, to=100, width=5, textvariable=self._var(key)).grid(row=r, column=1, sticky="w")
            lab = ttk.Label(parent, text="", style="Muted.TLabel")
            lab.grid(row=r, column=2, sticky="w", padx=8)
            self._pct_labels.append((lab, key, kind))
            self._var(key).trace_add("write", lambda *a: self._pct_refresh())

        pct_row(ma, 0, "Rest below MA %", "rest_below_ma", "ma")
        pct_row(ma, 1, "Rest until MA %", "rest_until_ma", "ma")
        # Dan: the heal mana lines sit with the rest lines (0 = heal at any mana)
        pct_row(ma, 2, "Heal in a fight above MA %", "heal_min_ma_fight", "ma")
        pct_row(ma, 3, "Heal out of a fight above MA %", "heal_min_ma_rest", "ma")
        self._check(ma, "use_meditate", "Meditate when only mana is low").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Entry(ma, textvariable=self._var("meditate_cmd"), width=8).grid(row=4, column=2, sticky="w", padx=8)
        ttk.Label(ma, text="Mana regen spell").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(ma, textvariable=self._var("ma_regen_cmd"), width=8).grid(row=5, column=1, sticky="w")
        ttk.Label(ma, text="cast when you rest for mana", style="Muted.TLabel").grid(row=5, column=2, sticky="w", padx=8)
        fx = ttk.Frame(ma)
        fx.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(fx, text="Keep mana regen up…",
                   command=lambda: self.edit_buff(new=True, preset=self._regen_preset())).pack(side="left")
        ttk.Label(fx, text="  your class's spell (flux / ntap / nity), recast whenever its rate drops below the "
                           "minimum you set", style="Muted.TLabel").pack(side="left")
        self._mana_casts = ttk.Label(ma, text="", style="Muted.TLabel", justify="left", wraplength=360)
        self._mana_casts.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        r = 0
        ttk.Label(hp, text="Heal command").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
        ttk.Entry(hp, textvariable=self._var("heal_cmd"), width=10).grid(row=r, column=1, sticky="w"); r += 1
        pct_row(hp, r, "Heal below HP %", "heal_pct", "hp"); r += 1
        pct_row(hp, r, "Rest below HP %", "rest_below_hp", "hp"); r += 1
        pct_row(hp, r, "Rest until HP %", "rest_until_hp", "hp"); r += 1
        pct_row(hp, r, "Run below HP %", "run_pct", "hp"); r += 1
        hg = ttk.Frame(hp)
        hg.grid(row=r, column=0, columnspan=3, sticky="w", pady=(4, 0)); r += 1
        self._check(hg, "hangup_low_hp", "Hang up below").pack(side="left")
        ttk.Spinbox(hg, from_=1, to=99, width=4, textvariable=self._var("hangup_hp_pct")).pack(side="left", padx=4)
        ttk.Label(hg, text="%").pack(side="left")
        lab = ttk.Label(hg, text="", style="Muted.TLabel")
        lab.pack(side="left", padx=8)
        self._pct_labels.append((lab, "hangup_hp_pct", "hp"))
        self._var("hangup_hp_pct").trace_add("write", lambda *a: self._pct_refresh())
        ttk.Label(hp, text="HP regen spell").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(hp, textvariable=self._var("hp_regen_cmd"), width=8).grid(row=r, column=1, sticky="w")
        ttk.Label(hp, text="cast when you rest", style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=8); r += 1
        ttk.Label(hp, text="Rest command").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(hp, textvariable=self._var("rest_cmd"), width=8).grid(row=r, column=1, sticky="w"); r += 1
        dth = ttk.Frame(hp)
        dth.grid(row=r, column=0, columnspan=3, sticky="w", pady=(4, 0)); r += 1
        ttk.Label(dth, text="If I die:").pack(side="left")
        ttk.Radiobutton(dth, text="stop and stay put", value="stay", variable=self._var("death_action")).pack(side="left", padx=6)
        ttk.Radiobutton(dth, text="hang up", value="hangup", variable=self._var("death_action")).pack(side="left")
        ttk.Label(dth, text="  (never walks the loop again by itself; your phone gets where and what)",
                  style="Muted.TLabel").pack(side="left")
        ttk.Label(hp, text="Run 0 = never run. Alt+H hangs up by hand.", style="Muted.TLabel").grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(4, 0))
        sw = ttk.LabelFrame(f, text="Rest / meditate commands (gear swaps)", padding=8)
        sw.grid(row=1, column=0, columnspan=2, sticky="we", pady=(10, 0))
        sw.columnconfigure(1, weight=1)
        sw.columnconfigure(3, weight=1)
        self._check(sw, "rest_swap_on", "Rest").grid(row=0, column=0, sticky="w")
        self._check(sw, "med_swap_on", "Meditate").grid(row=0, column=2, sticky="w", padx=(12, 0))
        for i, (lbl, key, col) in enumerate((("Pre-rest", "pre_rest_cmd", 0), ("Post-rest", "post_rest_cmd", 0),
                                             ("Pre-med", "pre_med_cmd", 2), ("Post-med", "post_med_cmd", 2))):
            row = 1 + i % 2
            ttk.Label(sw, text=lbl).grid(row=row, column=col, sticky="w", padx=(12 if col else 0, 6), pady=2)
            ttk.Entry(sw, textvariable=self._var(key), width=26).grid(row=row, column=col + 1, sticky="we", pady=2)
        ttk.Label(sw, text="^M separates commands, e.g. eq sparkling ring^Mremove platinum ring",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._check(sw, "auto_regen_gear", "Auto regen gear: put on the best HP regen (rest) / mana regen (meditate) "
                                           "gear in my pack, my fighting gear back after").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(sw, text="Picks from MME's item stats and your inventory — no commands to keep up to date. Use the "
                           "boxes above only for anything else (they run after it).",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=4, sticky="w")
        stl = ttk.LabelFrame(f, text="Stealth / light", padding=8)
        stl.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Label(stl, text="Sneak").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Combobox(stl, textvariable=self._var("sneak_mode"), values=("smart", "always"), width=8,
                     state="readonly").grid(row=3, column=1, sticky="w")
        ttk.Label(stl, text="smart = only into lair rooms (or when solo) — saves a command every step",
                  style="Muted.TLabel").grid(row=3, column=2, sticky="w", padx=8)
        lp = ttk.LabelFrame(f, text="On a loop", padding=8)
        lp.grid(row=3, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self._row(lp, 0, "Rest outside lair rooms: walk up to", "safe_rest_steps", to=10, width=4,
                  hint="steps on (0 = rest wherever) — nothing spawns on you mid-rest")
        self._row(lp, 1, "Wait in an empty lair up to", "lair_wait_secs", to=120, width=4,
                  hint="seconds for it to fill (0 = keep walking)")
        pc = ttk.Frame(lp)
        pc.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._check(pc, "lair_pace", "Lair pacing: if the next lair won't have refilled yet (due within").pack(side="left")
        ttk.Spinbox(pc, from_=5, to=300, width=4, textvariable=self._var("lair_pace_max")).pack(side="left", padx=4)
        ttk.Label(pc, text="s) and I'm not full, rest here meanwhile").pack(side="left")
        ttk.Label(lp, text="Refill times are learned per lair as you loop (Paths → More → Loop stats shows stocked vs "
                           "empty lairs).", style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w")
        sc = ttk.Frame(lp)
        sc.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._check(sc, "scripter_wait", "Someone clearing the lairs just ahead of me: no refill waits till I've "
                                         "caught up (up to").pack(side="left")
        ttk.Spinbox(sc, from_=30, to=900, width=4, textvariable=self._var("scripter_wait_max")).pack(side="left", padx=4)
        ttk.Label(sc, text="s), then share their rooms").pack(side="left")
        self._check(lp, "scripter_trail", "…or trail them: go where they go and take the kills, only inside my loop's "
                    "rooms — never follow them out (leader / solo)").grid(row=5, column=0, columnspan=3, sticky="w")
        rs = ttk.LabelFrame(f, text="Smarter resting", padding=8)
        rs.grid(row=4, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self._check(rs, "rest_up_on_tick", "Get up on the regen tick when it's only a sliver short of 'rest until' "
                    "(saves sitting through one more tick)").grid(row=0, column=0, columnspan=3, sticky="w")
        self._check(rs, "rest_smart_full", "Solo: take one more tick when it fills you right up "
                    "(saves a separate rest later)").grid(row=1, column=0, columnspan=3, sticky="w")
        mt = ttk.Frame(rs)
        mt.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._check(mt, "mana_throttle", "Stretch mana: cheaper spells from").pack(side="left")
        ttk.Spinbox(mt, from_=0, to=50, width=4, textvariable=self._var("mana_throttle_band")).pack(side="left", padx=4)
        ttk.Label(mt, text="% above 'Rest below MA' (it still stops to rest at that line)").pack(side="left")
        self._regen_lbl = ttk.Label(rs, text="", style="Muted.TLabel")
        self._regen_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        sm = ttk.Frame(rs)
        sm.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._check(sm, "smart_rest", "Smart resting: pick the quickest way back — rest, meditate + heal command, "
                    "or HP regen spell + meditate (heals straight away under").pack(side="left")
        ttk.Spinbox(sm, from_=0, to=90, width=4, textvariable=self._var("smart_rest_safe_hp")).pack(side="left", padx=4)
        ttk.Label(sm, text="% HP)").pack(side="left")
        ttk.Label(rs, text="Uses the Heal command and HP regen spell above, and this character's own rest / meditate "
                           "rates — it learns them from your rests first, then starts choosing.",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Label(rs, text="Stats → Rest log shows why each rest started and ended.", style="Muted.TLabel").grid(
            row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(rs, text="Auto-tune resting…", command=self.autotune_dialog).grid(row=5, column=0, sticky="w",
                                                                                     pady=(6, 0))
        for i, (lbl, k, hint) in enumerate((("Sneak command", "sneak_cmd", "before each step when Sneak is on"),
                                            ("Hide command", "hide_cmd", "while resting when Hide is on"),
                                            ("Light command", "light_cmd", "e.g. light torch — in dark rooms"))):
            self._row(stl, i, lbl, k, kind="entry", width=14, hint=hint)
        self._pct_refresh()
        return f

    def _pct_refresh(self):
        """'40% = 187 MA' next to each %, and how many area / attack casts the mana thresholds leave you."""
        st, cfg = self.s.state, self.s.settings
        rc = self.s.bot.regen
        if getattr(self, "_regen_lbl", None) is not None:
            self._regen_lbl.configure(text=(f"Regen tick learned: every {rc.period:.0f} s, about {rc.gain('hp'):.1f}% HP / "
                                            f"{rc.gain('ma'):.1f}% mana a tick" if rc.learned else
                                            "Regen tick: not learned yet — it watches a few rests first"))
        for lab, key, kind in getattr(self, "_pct_labels", []):
            try:
                pct = int(self._var(key).get() or 0)
            except (ValueError, tk.TclError):
                pct = 0
            top = st.max_ma if kind == "ma" else st.max_hp
            unit = "MA" if kind == "ma" else "HP"
            try:
                if not top:
                    lab.configure(text=f"(type 'st' in game to see {unit})")
                elif pct <= 0:
                    lab.configure(text="off")
                else:
                    lab.configure(text=f"= {top * pct // 100} {unit} of {top}")
            except tk.TclError:
                pass
        lab = getattr(self, "_mana_casts", None)
        if lab is None:
            return
        try:
            if not st.max_ma:
                lab.configure(text="")
                return
            spells = []
            area = self._area_spell()
            if area:
                spells.append(area)
            for sh in (cfg.attack_spells or [])[:1]:
                sp = self.s.spellbook.find(sh)
                if sp and sp not in spells:
                    spells.append(sp)
            lines = []
            for key, what in (("rest_below_ma", "when you stop to rest"), ("rest_until_ma", "when you get up")):
                try:
                    pct = int(self._var(key).get() or 0)
                except (ValueError, tk.TclError):
                    pct = 0
                if not pct:
                    continue
                mana = st.max_ma * pct // 100 - int(cfg.spell_mana_reserve or 0)
                bits = [f"{max(0, mana) // max(1, int(sp.get('ManaCost') or 1))}× {sp.get('Short')} "
                        f"({int(sp.get('ManaCost') or 0)})" for sp in spells if int(sp.get("ManaCost") or 0)]
                if bits:
                    lines.append(f"At {pct}% {what}: " + ", ".join(bits))
            lab.configure(text="\n".join(lines))
        except tk.TclError:
            pass

    def _area_spell(self):
        """Your area attack spell: the Combat tab's, else the strongest area spell you know."""
        from .spells import spell_kind
        cfg = self.s.settings
        if cfg.multi_spell:
            sp = self.s.spellbook.find(cfg.multi_spell)
            if sp:
                return sp
        best = None
        try:
            for sp in self.s.spell_candidates():
                if spell_kind(sp) not in (None, "single") and (best is None or int(sp.get("ManaCost") or 0) >
                                                               int(best.get("ManaCost") or 0)):
                    best = sp
        except Exception:
            return None
        return best

    NEAREST_BANK = "the nearest bank"

    def _bank_dropdown(self, parent):
        """Pick the bank by name; it's saved as its room ('17/2435'), blank for the nearest."""
        try:
            banks = self.s.trips.bank_choices()
        except Exception:
            banks = []
        by_label = {lbl: f"{r[0]}/{r[1]}" for lbl, r in banks}
        by_room = {v: k for k, v in by_label.items()}
        store = self._var("bank_room")
        cur = (store.get() or "").strip()
        shown = tk.StringVar(value=self.NEAREST_BANK if not cur else by_room.get(cur, cur))
        values = [self.NEAREST_BANK] + list(by_label) + ([cur] if cur and cur not in by_room else [])
        width = max(len(v) for v in values) + 2
        cb = ttk.Combobox(parent, textvariable=shown, values=values, width=min(width, 40), state="readonly")

        def picked(_e=None):
            v = shown.get()
            store.set("" if v == self.NEAREST_BANK else by_label.get(v, v))
        cb.bind("<<ComboboxSelected>>", picked)
        return cb

    def _loot_tab(self, nb):
        """Cash rules, auto-grab items, drop smaller coins, stash room (each lap)."""
        f = ttk.Frame(nb, padding=10)
        cash = ttk.LabelFrame(f, text="Cash (Cash button on)", padding=8)
        cash.grid(row=0, column=0, sticky="nsew")
        ttk.Label(cash, text="Pick up", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(cash, text="…until level (0 = always)", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(cash, text="Stash", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        rules = self.s.settings.cash_rules
        self.cash_vars = {}
        for i, (k, lbl) in enumerate((("copper farthing", "Copper"), ("silver noble", "Silver"), ("gold crown", "Gold"),
                                      ("platinum piece", "Platinum"), ("runic coin", "Runic")), start=1):
            r = rules.setdefault(k, {"get": True, "skip_at": 0})
            gv, sv = tk.BooleanVar(value=r.get("get", True)), tk.StringVar(value=str(r.get("skip_at", 0)))
            stv = tk.BooleanVar(value=k in (self.s.settings.stash_coins or []))
            ttk.Checkbutton(cash, text=lbl, variable=gv).grid(row=i, column=0, sticky="w", pady=1)
            ttk.Spinbox(cash, from_=0, to=255, width=5, textvariable=sv).grid(row=i, column=1, sticky="w", padx=8)
            ttk.Checkbutton(cash, variable=stv).grid(row=i, column=2)
            for v in (gv, sv, stv):
                v.trace_add("write", lambda *a: self._cash_save())
            self.cash_vars[k] = (gv, sv, stv)
        dr = ttk.Frame(cash)
        dr.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._check(dr, "drop_small_coins", "Drop smaller coins for bigger ones at").pack(side="left")
        ttk.Spinbox(dr, from_=0, to=100, width=4, textvariable=self._var("drop_coins_enc")).pack(side="left", padx=4)
        ttk.Label(dr, text="% encumbrance").pack(side="left")
        self._check(cash, "drop_unwanted_coins", "Drop coins I've stopped collecting").grid(row=8, column=0, columnspan=3, sticky="w")
        hv = ttk.Frame(cash)
        hv.grid(row=9, column=0, columnspan=3, sticky="w")
        self._check(hv, "coins_not_heavy", "Don't pick up coins once I'm Heavy (at").pack(side="left")
        ttk.Spinbox(hv, from_=10, to=100, width=4, textvariable=self._var("coins_heavy_pct")).pack(side="left", padx=4)
        ttk.Label(hv, text="% encumbrance)").pack(side="left")
        it = ttk.LabelFrame(f, text="Items (Get button on)", padding=8)
        it.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        it.columnconfigure(1, weight=1)
        self._row(it, 0, "Grab these", "loot_items", kind="entry", width=34, hint="")
        ttk.Label(it, text="comma list; part of the name is fine; * = everything", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w")
        self._row(it, 2, "Never grab", "loot_never", kind="entry", width=34, hint="")
        self._row(it, 3, "Item command", "get_item_cmd", kind="entry", width=16, hint="{item}")
        self._row(it, 4, "Cash command", "get_cash_cmd", kind="entry", width=16, hint="{qty} {item}")
        self._row(it, 5, "Drop command", "drop_cmd", kind="entry", width=16, hint="{qty} {item}")
        ttk.Button(it, text="Item rules…", command=self.item_rules_dialog).grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Label(it, text="per item: max / keep / drop / never; checks weight first", style="Muted.TLabel").grid(
            row=6, column=1, columnspan=2, sticky="w", pady=(6, 0))
        stf = ttk.LabelFrame(f, text="Stash (each lap)", padding=8)
        stf.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        stf.columnconfigure(1, weight=1)
        sr = ttk.Frame(stf)
        sr.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(sr, text="Default stash room").pack(side="left")
        ttk.Entry(sr, textvariable=self._var("stash_room"), width=10).pack(side="left", padx=4)
        ttk.Button(sr, text="Use the room I'm in", command=self._stash_here).pack(side="left", padx=4)
        self.stash_name = ttk.Label(sr, text="", style="Muted.TLabel")
        self.stash_name.pack(side="left", padx=6)
        self._var("stash_room").trace_add("write", lambda *a: self._stash_label())
        self._row(stf, 1, "Stash these items", "stash_items", kind="entry", width=40, hint="comma list (coins: ticks above)")
        ttk.Label(stf, text="Items you auto-get stay in your pack. Tick Auto-stash on the ones to hide here "
                            "(Game Data → Items, or '@stash <item>').", style="Muted.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w")
        hr = ttk.Frame(stf)
        hr.grid(row=3, column=0, columnspan=3, sticky="w")
        self._check(hr, "stash_hide", "Hide it after dropping:").pack(side="left")
        ttk.Entry(hr, textvariable=self._var("stash_hide_cmd"), width=14).pack(side="left", padx=4)
        ttk.Label(hr, text="drop with").pack(side="left", padx=(10, 2))
        ttk.Entry(hr, textvariable=self._var("stash_cmd"), width=16).pack(side="left", padx=4)
        lr = ttk.Frame(stf)
        lr.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._check(lr, "stash_each_lap", "If the loop doesn't pass its stash room, walk there at the end of each lap when carrying ≥").pack(side="left")
        ttk.Spinbox(lr, from_=0, to=10 ** 7, width=8, textvariable=self._var("stash_min_copper")).pack(side="left", padx=4)
        ttk.Label(lr, text="copper worth (or any stash item)").pack(side="left")
        fr2 = ttk.Frame(stf)
        fr2.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(fr2, text="…but never more than").pack(side="left")
        ttk.Spinbox(fr2, from_=0, to=999, width=5, textvariable=self._var("stash_max_steps")).pack(side="left", padx=4)
        ttk.Label(fr2, text="steps away (0 = no limit). Each loop can have its own stash: Paths tab → More → "
                            "Stash room for this loop.", style="Muted.TLabel").pack(side="left")
        ttk.Label(f, text="Defaults: copper stops at level 5, silver at 10; gold, platinum and runic are always picked up "
                          "and stashed. When MudPilot is in the stash room it drops (and hides) them, then carries on.",
                  style="Muted.TLabel", wraplength=860, justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        gu = ttk.LabelFrame(f, text="Gear upgrades", padding=8)
        gu.grid(row=4, column=0, columnspan=2, sticky="we", pady=(10, 0))
        g1 = ttk.Frame(gu)
        g1.pack(fill="x")
        self._check(g1, "gear_watch", "Tell me when I see or pick up armour better for").pack(side="left")
        from . import gearcalc as _G
        ttk.Combobox(g1, textvariable=self._var("gear_goal"), values=list(_G.GOALS), width=20,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(g1, text="by at least").pack(side="left")
        ttk.Spinbox(g1, from_=0.1, to=50, increment=0.5, width=5, textvariable=self._var("gear_min_gain")).pack(side="left", padx=4)
        g2 = ttk.Frame(gu)
        g2.pack(fill="x", pady=(4, 0))
        self._check(g2, "gear_grab_upgrades", "Pick upgrades up").pack(side="left")
        self._check(g2, "gear_auto_wear", "…and wear them").pack(side="left", padx=12)
        self._check(g2, "gear_watch_weapons", "Also tell me about harder-hitting weapons").pack(
            side="left", padx=12)
        ttk.Label(gu, text="Uses the inventory calculator's rules (class, race, level, strength). Weapons are never "
                           "swapped automatically. Shop 'list's are checked too. Tick \"Gear upgrade\" under Alerts "
                           "for a phone alert.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        g3 = ttk.Frame(gu)
        g3.pack(fill="x", pady=(6, 0))
        self._check(g3, "item_charges_on", "Count charged items' uses (wands, per-day items) and stop using one "
                                           "that's out · daily cleanup at").pack(side="left")
        ttk.Entry(g3, textvariable=self._var("cleanup_time"), width=6).pack(side="left", padx=4)
        ttk.Label(g3, text="(HH:MM, this PC's clock; blank = 24 h after it ran out)", style="Muted.TLabel").pack(
            side="left")
        gm = ttk.LabelFrame(f, text="Gear modes", padding=8)
        gm.grid(row=5, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self._check(gm, "gear_modes_on", "Swap gear by itself for walking, fighting, resting, meditating and PvP").grid(
            row=0, column=0, columnspan=4, sticky="w")
        from .gearmodes import MODES, LABEL
        self._gm_labels = {}
        for i, mode in enumerate(MODES, start=1):
            ttk.Label(gm, text=LABEL[mode], width=16).grid(row=i, column=0, sticky="w")
            lab = ttk.Label(gm, text="", style="Muted.TLabel", wraplength=520, justify="left")
            lab.grid(row=i, column=1, sticky="w", padx=6)
            self._gm_labels[mode] = lab
            ttk.Button(gm, text="Capture what I'm wearing", command=lambda m=mode: self._gm_capture(m)).grid(
                row=i, column=2, padx=2, pady=1)
            ttk.Button(gm, text="Clear", command=lambda m=mode: self._gm_clear(m)).grid(row=i, column=3, padx=2)
        ttk.Label(gm, text="Put the gear on in the game (and type i), then Capture. Slots a mode doesn't list keep "
                           "their Base item. Combat gear goes on as a fight starts (it costs a round).",
                  style="Muted.TLabel", wraplength=860, justify="left").grid(row=len(MODES) + 1, column=0,
                                                                            columnspan=4, sticky="w", pady=(4, 0))
        self._gm_show()
        tp = ttk.LabelFrame(f, text="Bank and shop trips (end of a lap, then back to the loop)", padding=8)
        tp.grid(row=1, column=0, columnspan=2, sticky="we", pady=(10, 0))
        t1 = ttk.Frame(tp)
        t1.pack(fill="x")
        self._check(t1, "auto_deposit_on", "Deposit at the bank when carrying").pack(side="left")
        ttk.Spinbox(t1, from_=0, to=10 ** 9, width=10, textvariable=self._var("deposit_at_copper")).pack(side="left", padx=4)
        ttk.Label(t1, text="copper worth at").pack(side="left")
        self._bank_dropdown(t1).pack(side="left", padx=4)
        ttk.Label(t1, text="· command").pack(side="left")
        ttk.Entry(t1, textvariable=self._var("deposit_cmd"), width=18).pack(side="left", padx=4)
        t2 = ttk.Frame(tp)
        t2.pack(fill="x", pady=(4, 0))
        self._check(t2, "auto_sell_on", "Sell these at the nearest shop that trades in them:").pack(side="left")
        ttk.Entry(t2, textvariable=self._var("auto_sell_items"), width=44).pack(side="left", padx=4)
        t2b = ttk.Frame(tp)
        t2b.pack(fill="x", pady=(4, 0))
        self._check(t2b, "loot_drop_cheap", "Drop cheap loot: leave or drop (chests too) what a shop pays under").pack(
            side="left")
        ttk.Spinbox(t2b, from_=1, to=10 ** 6, width=7, textvariable=self._var("loot_drop_below_gold")).pack(
            side="left", padx=4)
        ttk.Label(t2b, text="gold for; what's worth more from chests goes on the sell trip", style="Muted.TLabel").pack(
            side="left")
        t3 = ttk.Frame(tp)
        t3.pack(fill="x", pady=(4, 0))
        self._check(t3, "auto_buy_on", "Restock:").pack(side="left")
        ttk.Entry(t3, textvariable=self._var("auto_buy"), width=50).pack(side="left", padx=4)
        ttk.Label(t3, text="e.g. healing potion 3-10; torch 2-5 (keep 3, buy up to 10)", style="Muted.TLabel").pack(side="left")
        t4 = ttk.Frame(tp)
        t4.pack(fill="x", pady=(4, 0))
        ttk.Label(t4, text="Never more than").pack(side="left")
        ttk.Spinbox(t4, from_=5, to=400, width=5, textvariable=self._var("trip_max_steps")).pack(side="left", padx=4)
        ttk.Label(t4, text="steps away. Shops come from MME (the shops that sell an item also buy it).",
                  style="Muted.TLabel").pack(side="left")
        self._training_frame(f).grid(row=6, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self._stash_label()
        return f

    def _training_frame(self, f):
        """0.8.200 auto-train (training.py): every switch off until you tick it."""
        tf = ttk.LabelFrame(f, text="Training (end of a lap, then back to the loop)", padding=8)
        r1 = ttk.Frame(tf)
        r1.pack(fill="x")
        self._check(r1, "auto_train", "Train levels automatically at the nearest trainer").pack(side="left")
        ttk.Label(r1, text="· keep").pack(side="left", padx=(8, 0))
        ttk.Spinbox(r1, from_=0, to=50, width=4, textvariable=self._var("train_keep_levels")).pack(side="left", padx=4)
        ttk.Label(r1, text="levels banked · don't train above level").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=999, width=5, textvariable=self._var("train_max_level")).pack(side="left", padx=4)
        ttk.Label(r1, text="(0 = no cap)", style="Muted.TLabel").pack(side="left")
        r2 = ttk.Frame(tf)
        r2.pack(fill="x", pady=(4, 0))
        self._check(r2, "train_stats", "After training, spend CP by my CP plan (train stats):").pack(side="left")
        ttk.Entry(r2, textvariable=self._var("train_stats_plan"), width=40).pack(side="left", padx=4)
        ttk.Label(r2, text="e.g. 10: STR 60 AGL 50; 20: STR 70", style="Muted.TLabel").pack(side="left")
        r3 = ttk.Frame(tf)
        r3.pack(fill="x", pady=(4, 0))
        self._check(r3, "party_train", "Train together with my MudPilot party (I lead: I take everyone; I follow: "
                    "I wait for my leader's order)").pack(side="left")
        ttk.Label(tf, text="Trainers come from MME (class and level band). Short of the fee: the bank first. The CP plan "
                           "is typed into train stats and read back before saving — anything not exactly right and it "
                           "leaves with QUIT. Game Data → Exp/CP can save a plan row too.",
                  style="Muted.TLabel", wraplength=860, justify="left").pack(anchor="w", pady=(4, 0))
        return tf


    def _gm_show(self):
        sets = self.s.gearmodes.sets()
        one = lambda v: " + ".join(v) if isinstance(v, list) else (v or "")
        for mode, lab in getattr(self, "_gm_labels", {}).items():
            g = sets.get(mode) or {}
            if mode != "base" and g:
                base = sets.get("base") or {}
                g = {k: v for k, v in g.items() if one(base.get(k)) != one(v)}
                txt = (", ".join(f"{one(v)} ({k})" for k, v in g.items()) or "same as Base")
            else:
                txt = ", ".join(f"{one(v)} ({k})" for k, v in g.items()) if g else "not set"
            lab.configure(text=txt)

    def _gm_capture(self, mode):
        if not worn_list_of(self.s.state.carrying):
            messagebox.showinfo("Gear modes", "MudPilot hasn't seen what you're wearing yet — type i in the game "
                                              "first, then Capture.", parent=self.root)
            return
        self.s.gearmodes.capture(mode)
        self._gm_show()

    def _gm_clear(self, mode):
        self.s.gearmodes.clear(mode)
        self._gm_show()

    def _cash_save(self):
        st = self.s.settings
        st.stash_coins = []
        for k, (gv, sv, stv) in self.cash_vars.items():
            try:
                skip = int(sv.get() or 0)
            except ValueError:
                skip = 0
            st.cash_rules[k] = {"get": bool(gv.get()), "skip_at": skip}
            if stv.get():
                st.stash_coins.append(k)
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, st.save)

    def _stash_here(self):
        """Use the room you're standing in as a stash: pick which loop it's for (closest loops first),
        or make it the default for loops that don't have their own."""
        r = self.s.state.room
        if not r:
            messagebox.showinfo("MudPilot", "Your room isn't known yet — press Enter in the game first.")
            return
        w, cfg, x = self.s.world, self.s.settings, self.s.bot.x
        rm = w.room(r)
        # one walk outwards from here gives the distance to every room (up to 250 steps)
        from collections import deque
        dist_to, q = {r: 0}, deque([r])
        while q:
            k = q.popleft()
            if dist_to[k] >= 250:
                continue
            room = w.room(k)
            for ex in (room.exits.values() if room else ()):
                if ex.to not in dist_to and ex.to in w.rooms and ex.kind in w.PASSABLE_DEFAULT:
                    dist_to[ex.to] = dist_to[k] + 1
                    q.append(ex.to)
        rows = []
        for mp in self.s.paths:
            if not mp.is_loop or not mp.resolved:
                continue
            ds = [dist_to[st.room] for st in mp.steps if st.room in dist_to]
            if ds:
                rows.append((min(ds), mp))
        rows.sort(key=lambda t: (t[0], t[1].title.lower()))
        d = tk.Toplevel(self.root)
        d.title("Stash room - which loop?")
        d.transient(self.root)
        d.geometry("560x420")
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Stash in {r[0]}/{r[1]} {rm.name if rm else ''} — for which loop?",
                  style="Head.TLabel").pack(anchor="w")
        tv = ttk.Treeview(fr, columns=("dist", "now"), show="tree headings", height=12)
        tv.heading("#0", text="Loop")
        tv.heading("dist", text="Steps from here")
        tv.heading("now", text="Its stash now")
        tv.column("#0", width=250)
        tv.column("dist", width=100, anchor="e")
        tv.column("now", width=150)
        tv.pack(fill="both", expand=True, pady=6)
        for dist, mp in rows[:200]:
            cur = (cfg.loop_stash or {}).get(x.loop_key(mp), "") or "default"
            tv.insert("", "end", iid=mp.filename or mp.title, text=mp.title,
                      values=("on the loop" if dist == 0 else dist, cur))
        if rows:
            first = rows[0][1]
            tv.selection_set(first.filename or first.title)
        here_txt = f"{r[0]}/{r[1]}"

        def for_loop(e=None):
            sel = tv.selection()
            mp = next((p for p in self.s.paths if (p.filename or p.title) == (sel[0] if sel else None)), None)
            if not mp:
                return
            ls = dict(cfg.loop_stash or {})
            ls[x.loop_key(mp)] = here_txt
            cfg.loop_stash = ls
            cfg.save()
            self.add_log(f"Stash for '{mp.title}': {here_txt} {rm.name if rm else ''}")
            self._stash_label()
            d.destroy()

        def as_default():
            self._var("stash_room").set(here_txt)
            d.destroy()
        tv.bind("<Double-1>", for_loop)
        b = ttk.Frame(fr)
        b.pack(fill="x")
        ttk.Button(b, text="Use for this loop", style="Accent.TButton", command=for_loop).pack(side="right")
        ttk.Button(b, text="Default for every loop", command=as_default).pack(side="right", padx=6)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        if not rows:
            ttk.Label(fr, text="No loops near here — make it the default, or import/build a loop first.",
                      style="Muted.TLabel").pack(anchor="w")

    def _stash_label(self):
        key = room_text(self.s.settings.stash_room)      # the box itself, not this loop's own stash
        rm = self.s.world.room(key) if key else None
        if hasattr(self, "stash_name"):
            self.stash_name.configure(text=rm.name if rm else ("" if not (self.s.settings.stash_room or "").strip() else
                                      f"no room {key[0]}/{key[1]} in the map data" if key else
                                      "can't read that — type map/room, e.g. 14/6534"))

    def _party_tab(self, nb):
        """MegaMUD's Party tab."""
        f = ttk.Frame(nb, padding=10)
        left = ttk.Frame(f)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.LabelFrame(f, text="Options", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        f.columnconfigure(1, weight=1)
        rk = ttk.LabelFrame(left, text="Party rank (set whenever you're in a party)", padding=8)
        rk.pack(fill="x", pady=(0, 8))
        rv = self._var("party_rank")
        for val, lbl in (("", "Leave it"), ("front", "Front"), ("mid", "Mid"), ("back", "Back")):
            ttk.Radiobutton(rk, text=lbl, variable=rv, value=val).pack(side="left", padx=(0, 6))
        ttk.Label(rk, text="cmd").pack(side="left", padx=(8, 2))
        ttk.Entry(rk, textvariable=self._var("rank_cmd"), width=12).pack(side="left")
        ij = ttk.Frame(left)
        ij.pack(fill="x", pady=(0, 8))
        ttk.Label(ij, text="After inviting, send").pack(side="left")
        ttk.Entry(ij, textvariable=self._var("invite_join_cmd"), width=16).pack(side="left", padx=4)
        ttk.Label(ij, text="so they join right away (blank = off)", style="Muted.TLabel").pack(side="left")
        ph = ttk.LabelFrame(left, text="Party heal", padding=8)
        ph.pack(fill="x")
        self._check(ph, "party_heal", "Heal the party (Heal button on)").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(ph, text="spell", style="Muted.TLabel").grid(row=1, column=1, sticky="w")
        for i, (lbl, k, pk) in enumerate((("Minor", "party_heal_cmd", "party_heal_pct"),
                                          ("Major", "party_major_cmd", "party_major_pct")), start=2):
            ttk.Label(ph, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(ph, textvariable=self._var(k), width=12).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Label(ph, text="at").grid(row=i, column=2)
            ttk.Spinbox(ph, from_=1, to=100, width=4, textvariable=self._var(pk)).grid(row=i, column=3, sticky="w")
            ttk.Label(ph, text="%").grid(row=i, column=4, sticky="w")
        ttk.Label(ph, text="Area").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(ph, textvariable=self._var("party_area_cmd"), width=12).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(ph, text="@").grid(row=4, column=2)
        ar = ttk.Frame(ph)
        ar.grid(row=4, column=3, columnspan=3, sticky="w")
        ttk.Spinbox(ar, from_=2, to=9, width=3, textvariable=self._var("party_area_count")).pack(side="left")
        ttk.Label(ar, text=" < ").pack(side="left")
        ttk.Spinbox(ar, from_=1, to=100, width=4, textvariable=self._var("party_area_pct")).pack(side="left")
        ttk.Label(ar, text="%").pack(side="left")
        ttk.Label(ph, text="Request healing at").grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 2))
        ttk.Spinbox(ph, from_=0, to=100, width=4, textvariable=self._var("request_heal_pct")).grid(row=5, column=3, sticky="w")
        ttk.Label(ph, text="% (0 = off)").grid(row=5, column=4, columnspan=2, sticky="w")
        ttk.Label(ph, text="Minor/Major: {name} = who (blank Minor = your heal + name).",
                  style="Muted.TLabel", wraplength=300).grid(row=6, column=0, columnspan=6, sticky="w", pady=(4, 0))
        pr = ttk.LabelFrame(left, text="Priority", padding=8)
        pr.pack(fill="x", pady=(8, 0))
        self._row(pr, 0, "Heal these first", "party_heal_priority", kind="entry", width=20, hint="")
        self._row(pr, 1, "…as if this % lower", "party_priority_bonus", to=100, width=5)
        ttk.Label(pr, text="Attack which monster").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Combobox(pr, textvariable=self._var("target_priority"), values=("first", "second", "third", "last"),
                     width=8, state="readonly").grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(pr, text="in the room list — split a room between two bots", style="Muted.TLabel").grid(
            row=2, column=2, columnspan=4, sticky="w")
        ttk.Checkbutton(pr, text="Biggest threat first (most exp) — the list above counts from it",
                        variable=self._var("target_biggest")).grid(row=3, column=0, columnspan=6, sticky="w", pady=(2, 0))
        ttk.Label(left, text="Party blesses are on the Bless tab, next to your own.", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0))
        opts = (("party_check_on", None), ("heal_party_over_self", "Heal party over self, if lower"),
                ("rest_heal_party", "Rest healing applies to party"), ("area_over_major", "Area heal over major heal"),
                ("par_after_round", "Send PAR after combat"), ("attack_reverse", "Attack in reverse order"),
                ("attack_leaders_target", "Attack what the leader attacks"), ("attack_last", "Attack last (again after the party joins in)"),
                ("defend_party_pvp", "Defend party when PvP"), ("share_cash", "Auto-share collected cash"),
                ("help_bash", "Help leader bash doors"), ("say_panic", "Say @panic when leading"),
                ("ignore_panic_following", "Ignore @panic when following"),
                ("ignore_party_following", "Ignore @party when following"),
                ("ignore_wait_leading", "Ignore @wait when leading"),
                ("leader_watch", "Following: notice the leader dropping or me being left behind"),
                ("party_sync", "Party sync with other MudPilots (rest together)"),
                ("aid_party", "Aid a member who drops to the ground (bleeding)"),
                ("party_teleport_bring", "Leading through a portal / 'dive sinkhole': @party them through and wait"),
                ("party_comeback", "Comeback: wait for a dropped member and go get them; ask the leader to come back for me"))
        rr = 0
        for k, t in opts:
            if t is None:
                continue
            self._check(right, k, t).grid(row=rr, column=0, columnspan=3, sticky="w", pady=0)
            rr += 1
        nums = (("Max monsters when partying", "party_max_mobs", "0 = Combat tab"),
                ("Max monster experience", "party_max_mob_exp", "0 = no limit"),
                ("Wait if members below HP %", "party_wait_pct", "leading"),
                ("…until they're back to HP %", "party_wait_until_pct", "0 = the line above"),
                ("Wait if members below MA %", "party_wait_ma_pct", "0 = off"),
                ("…until they're back to MA %", "party_wait_ma_until", ""),
                ("If leading, wait only (min)", "party_wait_mins", ""),
                ("'par' frequency (seconds)", "party_check_secs", "0 = off"),
                ("Comeback: wait for a dropped member (min)", "comeback_wait_mins", "then carry on"))
        for i, (lbl, k, hint) in enumerate(nums):
            self._row(right, rr + i, lbl, k, to=10 ** 9 if k == "party_max_mob_exp" else 999, width=8, hint=hint)
        rr += len(nums)
        for i, (lbl, k) in enumerate((("Party wait", "party_wait_msg"), ("Party resume", "party_resume_msg"),
                                      ("Leader (blank = first in par)", "party_leader"),
                                      ("Share command", "share_cmd"), ("Request heal text", "request_heal_cmd"),
                                      ("Left behind: send", "leader_gone_wait_cmd"),
                                      ("New loop: send each member", "party_reset_cmd"))):
            self._row(right, rr + i, lbl, k, kind="entry", width=22)
        return f

    def _pb_save(self):
        rows = []
        for _pv, cv, sv in self.pb_vars:
            c = cv.get().strip()
            if c:
                try:
                    secs = int(sv.get() or 0)
                except ValueError:
                    secs = 0
                rows.append({"cast": c, "secs": secs, "enabled": True})
        self.s.settings.party_blesses = rows
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, self.s.settings.save)

    def _other_tab(self, nb):
        """MegaMUD's Other options."""
        f = ttk.Frame(nb, padding=12)
        left = ttk.LabelFrame(f, text="Options", padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.LabelFrame(f, text="Miscellaneous", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        opts = (("pick_locks", "Pick locks instead of bashing"), ("relog_instead_of_hang", "Relog instead of hanging"),
                ("allow_hangup_not_afk", "Allow @hangup when not AFK"), ("allow_hangup_all_off", "Allow @hangup in all-off mode"),
                ("hangup_if_naked", "Hang up if naked"), ("show_recover_password", "Show the recover password ('pro')"),
                ("record_sessions", "Record sessions for debugging (data\\traces, passwords removed)"),
                ("disarm_traps", "Disarm traps on the path before walking into them (thieves)"),
                ("start_maximized", "Open MudPilot full-screen (maximised)"),
                ("cp437_terminal", "BBS art (CP437): draw the MUD window in an IBM PC font so box lines and blocks "
                                   "line up"),
                ("recover_corpse", "Recover my corpse when I find it"),
                ("toll_bank_run", "Short for a toll: go to the bank and withdraw it first"), ("bless_while_resting", "Bless while resting"),
                ("bless_in_combat", "Bless during combat"), ("go_back_if_running", "Go backwards if running"),
                ("break_before_running", "Break combat before running"), ("light_dim_rooms", "Provide light in dimly lit rooms"),
                ("auto_light_items", "Ready a carried light (torch, lantern…) before dark rooms, put it away in lit "
                                     "ones; relight and buy more when it burns out"),
                ("dont_move_unless_sneaking", "Don't move unless sneaking"), ("afk", "Away from keyboard (Alt+K)"))
        for i, (k, t) in enumerate(opts):
            self._check(left, k, t).grid(row=i, column=0, sticky="w", pady=1)
        self._var("cp437_terminal").trace_add("write", lambda *a: self.root.after(0, self.apply_fonts))
        right.columnconfigure(1, weight=1)
        rows = (("Attempt bash", "attempt_bash", "times"), ("Attempt pick-lock", "attempt_pick", "times"),
                ("Search each room", "search_count", "times"), ("Run distance", "run_distance", "rooms"),
                ("Back-scroll", "scrollback_lines", "lines"), ("Delete players inactive", "delete_players_days", "days (0 = never)"))
        for i, (lbl, k, hint) in enumerate(rows):
            self._row(right, i, lbl, k, to=1000000 if k == "scrollback_lines" else 999, width=8, hint=hint)
        i = len(rows)
        for lbl, k, w, hint in (("Command splitter", "command_splitter", 4, "splits what you type"),
                                ("Bash command", "bash_cmd", 14, "{dir}"), ("Pick command", "pick_cmd", 14, "{dir}"),
                                ("Break command", "break_cmd", 8, ""), ("Game entry cmd", "game_entry_cmd", 18, "sent once you're in"),
                                ("Game exit cmd", "game_exit_cmd", 18, "before Disconnect / relog")):
            self._row(right, i, lbl, k, kind="entry", width=w, hint=hint)
            i += 1
        rt = ttk.LabelFrame(f, text="Routing (Go to, stash runs, events)", padding=8)
        rt.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        rt.columnconfigure(1, weight=1)
        ttk.Label(rt, text="Areas to avoid").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        ttk.Combobox(rt, textvariable=self._var("avoid_mode"), values=("ask", "avoid", "allow"), width=8,
                     state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(rt, text="ask = a prompt when you click Go to (unattended walks always take the scenic route)",
                  style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        self._row(rt, 1, "Room names containing", "avoid_names", kind="entry", width=40,
                  hint="comma list, e.g. Negative Power Plane")
        self._row(rt, 2, "Never walk through", "avoid_rooms", kind="entry", width=40, hint="map/room list, e.g. 3/606, 12/40")
        ttk.Label(rt, text="Level-restricted exits from MME (e.g. Level 10 to 999) are used only when your level fits.",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._check(rt, "check_needed_items", "Check for needed keys/items (rope and grapple, golden idol…) before "
                    "walking a path; Go to only uses those doors if you have them").grid(row=4, column=0, columnspan=3, sticky="w")
        self._check(rt, "auto_get_items", "Missing one? Go get it first — kill the monster that drops it or buy it "
                    "(e.g. Thrag's green metal key and large iron key)").grid(row=6, column=0, columnspan=3, sticky="w")
        self._check(rt, "bash_key_doors", "No key and none to fetch? Walk anyway and pick/bash the door "
                    "(Attempt bash / pick-lock above set how many tries)").grid(row=20, column=0, columnspan=3, sticky="w")
        self._check(rt, "route_pay_tolls", "Use toll exits I can afford").grid(row=21, column=0, columnspan=3, sticky="w")
        self._check(rt, "route_spell_traps", "Walk through spell-trap exits when the way round is 25+ steps longer").grid(
            row=22, column=0, columnspan=3, sticky="w")
        # 0.8.201: teleport tokens (tokens.py) and cheap counters for rooms that hurt (hazards.py) — both off by default
        self._check(rt, "route_tokens", "Go to: use a teleport token I carry (token of Silvermere…) when it saves a lot of "
                    "walking — solo, room clear, out of combat; walks if it fails").grid(row=40, column=0, columnspan=3,
                                                                                         sticky="w")
        self._row(rt, 41, "Token: saves at least", "route_token_min_save", to=999, width=6, hint="rooms of walking")
        self._check(rt, "hazard_counters", "Rooms that hurt on the way (cold, magma, swamp…): buy a cheap item that stops "
                    "it when the damage is worth it (one you carry comes first)").grid(row=42, column=0, columnspan=3,
                                                                                        sticky="w")
        self._row(rt, 43, "Hazard item: at most", "hazard_counter_cap", to=100000, width=6,
                  hint="gold (never more; dearer ones are only mentioned)")
        self._row(rt, 23, "My alignment", "char_alignment", kind="entry", width=10,
                  hint="for 'Alignment: Saint to Seedy' exits — blank = from the who list")
        ttk.Label(rt, text="Class, race and ability gates use your stat screen; when you lead, a class gate has to let "
                           "the whole party through. Traps cost extra so the way round is taken when it's close.",
                  style="Muted.TLabel", wraplength=640, justify="left").grid(row=24, column=0, columnspan=3, sticky="w")
        self._check(rt, "arrive_auto_on", "When a loop starts or a Go to arrives, turn combat, rest and heal back on (never Nuke)").grid(
            row=5, column=0, columnspan=3, sticky="w")
        self._timing_box(f).grid(row=3, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Label(f, text="Cures and ignore poison/blindness/confusion are on the Spells tab. Not in MudPilot yet: "
                          "auto-train, auto-cast at end of round, supernatural stealth, engage-auto-*, immunity "
                          "and message-processing switches.",
                  style="Muted.TLabel", wraplength=700, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        return f

    def _timing_box(self, f):
        """pMUD: Enter on Tick / Stop on Danger, commands timed to the tick, and rules for the bot's own info
        commands (Gather settings)."""
        cfg = self.s.settings
        box = ttk.LabelFrame(f, text="Timing, and the bot's own info commands", padding=8)
        self._check(box, "enter_on_tick", "Enter the realm just after the server tick (a whole round before "
                    "anything acts)").grid(row=0, column=0, columnspan=6, sticky="w")
        self._check(box, "stop_on_danger", "After a low-HP hang-up, don't relog by myself (even with Relog "
                    "instead of hanging)").grid(row=1, column=0, columnspan=6, sticky="w")
        self._check(box, "stop_on_typed_move", "When I move by hand while it's walking, stop until I click Rego"
                    ).grid(row=100, column=0, columnspan=6, sticky="w")
        self._check(box, "pilot_goto", "New Go to walker (plans every step from where you really are)"
                    ).grid(row=101, column=0, columnspan=6, sticky="w")
        ttk.Label(box, text="Commands timed to the tick — one per line: seconds-after-tick  mode  command  "
                            "(modes: any, combat, resting, idle, pvp — e.g.  0.3 resting look)",
                  style="Muted.TLabel", wraplength=700, justify="left").grid(row=2, column=0, columnspan=6, sticky="w",
                                                                           pady=(6, 2))
        tx = tk.Text(box, height=3, width=60, background="#0f1318", foreground=TEXT, insertbackground=TEXT,
                     borderwidth=0, font=("Consolas", 10))
        tx.insert("1.0", "\n".join(cfg.tick_cmds or []))
        tx.grid(row=3, column=0, columnspan=6, sticky="we")

        def save_tick(_e=None):
            from .tick import parse_cmds
            lines = [ln.strip() for ln in tx.get("1.0", "end").splitlines() if ln.strip()]
            bad = [ln for ln in lines if not parse_cmds([ln])]
            cfg.tick_cmds = [ln for ln in lines if parse_cmds([ln])]
            cfg.save()
            tick_note.configure(text=("Can't read: " + "; ".join(bad[:3])) if bad else
                                f"{len(cfg.tick_cmds)} timed command(s)")
        tx.bind("<FocusOut>", save_tick)
        tick_note = ttk.Label(box, text="", style="Muted.TLabel")
        tick_note.grid(row=4, column=0, columnspan=6, sticky="w")
        ttk.Label(box, text="Info commands the bot sends by itself (pMUD's Gather settings) — a held one waits and "
                            "goes out when it's allowed:", style="Muted.TLabel").grid(row=5, column=0, columnspan=6,
                                                                                      sticky="w", pady=(8, 2))
        for j, h in enumerate(("Command", "At most every (s)", "Not in combat", "Not while walking", "Sent / held")):
            ttk.Label(box, text=h, style="Muted.TLabel").grid(row=6, column=j, sticky="w", padx=4)
        self._info_labels = {}
        for i, c in enumerate(("par", "i", "stat", "exp", "abil"), start=7):
            rule = dict((cfg.info_cmd_rules or {}).get(c) or {})
            gv = tk.StringVar(value=str(rule.get("gap") or 0))
            cv = tk.BooleanVar(value=bool(rule.get("no_combat")))
            wv = tk.BooleanVar(value=bool(rule.get("no_walking")))

            def put(*_a, c=c, gv=gv, cv=cv, wv=wv):
                try:
                    gap = max(0.0, float(gv.get() or 0))
                except ValueError:
                    return
                rules = dict(cfg.info_cmd_rules or {})
                r = {"gap": gap, "no_combat": cv.get(), "no_walking": wv.get()}
                if gap or r["no_combat"] or r["no_walking"]:
                    rules[c] = r
                else:
                    rules.pop(c, None)
                cfg.info_cmd_rules = rules
                cfg.save()
            for v_ in (gv, cv, wv):
                v_.trace_add("write", put)
            ttk.Label(box, text=c).grid(row=i, column=0, sticky="w", padx=4)
            ttk.Spinbox(box, from_=0, to=600, width=6, textvariable=gv).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Checkbutton(box, variable=cv).grid(row=i, column=2, sticky="w", padx=4)
            ttk.Checkbutton(box, variable=wv).grid(row=i, column=3, sticky="w", padx=4)
            lb = ttk.Label(box, text="", style="Muted.TLabel")
            lb.grid(row=i, column=4, sticky="w", padx=4)
            self._info_labels[c] = lb

        def counts():
            try:
                if not box.winfo_exists():
                    return
            except tk.TclError:
                return
            stats = getattr(self.s.bot, "info_stats", {}) or {}
            for c, lb in self._info_labels.items():
                r = stats.get(c) or {}
                lb.configure(text=f"{r.get('sent', 0)} / {r.get('deferred', 0)}")
            box.after(3000, counts)
        counts()
        return box

    def _pvp_tab(self, nb):
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(1, weight=1)
        r = 0
        hang = ttk.LabelFrame(f, text="Hang up", padding=8)
        hang.grid(row=r, column=0, columnspan=3, sticky="we"); r += 1
        hang.columnconfigure(1, weight=1)
        self._check(hang, "hangup_on_pvp", "Hang up when a player attacks me or anyone in my party (@pvp off)").grid(
            row=0, column=0, sticky="w")
        self._check(hang, "pvp_realm", "This is a PvP realm (flash a reminder when this is off)").grid(
            row=0, column=1, columnspan=2, sticky="w", padx=(16, 0))
        ttk.Label(hang, text="Hang up below an HP % is on the Health tab.", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w")
        self._check(hang, "hangup_on_enemy", "Hang up when a player marked Enemy is seen (Game Data → Players)").grid(
            row=2, column=0, columnspan=3, sticky="w")
        self._check(hang, "hangup_on_player", "Hang up when any player is seen").grid(row=3, column=0, columnspan=3, sticky="w")
        self._check(hang, "pvp_tell_party", "Telepath the party '*Attacked*… hanging up!' first").grid(
            row=4, column=0, columnspan=3, sticky="w")
        self._row(hang, 5, "Hang up on monsters", "hangup_monsters", kind="entry", width=30,
                  hint="comma list (or right-click one on the screen)")
        self._row(hang, 6, "Safe rooms", "safe_rooms", kind="entry", width=30)
        self._check(hang, "banks_safe", "map/room list — and every bank").grid(row=6, column=2, sticky="w", padx=8)
        self._row(hang, 7, "Never for these players", "pvp_friends", kind="entry", width=36,
                  hint="comma list; your party, Friends and Talk-tab players are always ignored")
        self._row(hang, 8, "Stay offline (minutes)", "hangup_stay_offline", frm=0, to=1440,
                  hint="0 = stay off until you press Connect")
        self._row(hang, 9, "Party member killed: grab first", "pvp_loot_cmds", kind="entry", width=24,
                  hint="sent before hanging up — still gone before the next round (; between commands)")
        ttk.Label(hang, text="Last hang-up: none yet", style="Muted.TLabel").grid(row=10, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._pvp_last = hang.grid_slaves(row=10, column=0)[0]
        ttk.Label(hang, text="@pvp on (from a party member) = fight back and defend the party, no PvP hang-up; "
                  "the low-HP hang-up still works. Alt+H hangs up instantly, no questions. Grouped? Put the hang-ups off in another "
                  "config profile (Options → Config Profile 1–4, Alt+1…4) and switch with one key.",
                  style="Muted.TLabel", wraplength=640, justify="left").grid(row=11, column=0, columnspan=3, sticky="w", pady=(4, 0))
        hi = ttk.LabelFrame(f, text="Hang-up item pickup", padding=8)
        hi.grid(row=r, column=0, columnspan=3, sticky="we", pady=(10, 0)); r += 1
        hi.columnconfigure(1, weight=1)
        # 0.8.201 (Dan): off and 0 until set — only boards whose sysop made hang-ups drop items need it
        self._check(hi, "hangup_items_drop", "This board drops items when I hang up in a fight — pick them back up "
                    "after logging in").grid(row=0, column=0, columnspan=3, sticky="w")
        self._row(hi, 1, "Items it drops", "hangup_items_count", frm=0, to=100,
                  hint="the board's item count (option #60) — the most MudPilot will pick up")
        ttk.Label(hi, text="Paradigm doesn't drop items on a hang-up (only HP), so this does nothing there. On a board "
                  "that does: back in, the walk waits while MudPilot reads 'i', looks at the floor of the same room (not "
                  "dark, no monster) and gets back what's missing, then puts worn gear back on. A hang-up that killed "
                  "you (one life fewer) is left to death recovery.", style="Muted.TLabel", wraplength=640,
                  justify="left").grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        snd = ttk.LabelFrame(f, text="Listen", padding=8)
        snd.grid(row=r, column=0, columnspan=3, sticky="we", pady=(10, 0)); r += 1
        snd.columnconfigure(1, weight=1)
        self._check(snd, "look_on_sound", "Look toward movement I hear (e.g. heard to the northeast → look northeast)").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self._row(snd, 1, "Ignore same direction for", "look_ignore_secs", frm=0, to=60,
                  hint="seconds — stops a chasing pile of mobs causing five looks")
        ttk.Label(snd, text="Looking never moves you and never starts a fight; the next room is shown but "
                  "MudPilot keeps tracking the room you're in.", style="Muted.TLabel", wraplength=640).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        pv = ttk.LabelFrame(f, text="PvP spells (cast in order, one per round, at the player you're fighting)", padding=8)
        pv.grid(row=r, column=0, columnspan=3, sticky="we", pady=(10, 0)); r += 1
        ttk.Label(pv, text="spell", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(pv, text="recast every N rounds (0 = every round)", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        self.pvp_vars = []
        cur = list(self.s.settings.pvp_spells or [])
        for i in range(5):
            d = cur[i] if i < len(cur) else {}
            cv, rv = tk.StringVar(value=d.get("cast", "")), tk.StringVar(value=str(d.get("rounds", "")))
            ttk.Label(pv, text=f"{i + 1}.").grid(row=i + 1, column=0, sticky="w")
            ttk.Entry(pv, textvariable=cv, width=12).grid(row=i + 1, column=1, sticky="w", padx=4, pady=1)
            ttk.Entry(pv, textvariable=rv, width=6).grid(row=i + 1, column=2, sticky="w")
            for v in (cv, rv):
                v.trace_add("write", lambda *a: self._pvp_save())
            self.pvp_vars.append((cv, rv))
        ttk.Label(pv, text="e.g. 1. mist every 25 rounds, 2. slep every round. Then melee. Cast as '{cast} {name}'.",
                  style="Muted.TLabel").grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))
        fp = ttk.Frame(pv)
        fp.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._check(fp, "pvp_auto_fight", "Fight back when a player attacks me (only if PvP hang-up is off)").pack(side="left")
        fp2 = ttk.Frame(pv)
        fp2.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(fp2, text="Fight player").pack(side="left")
        self.pvp_name = tk.StringVar()
        ttk.Entry(fp2, textvariable=self.pvp_name, width=14).pack(side="left", padx=4)
        ttk.Button(fp2, text="Start", style="Accent.TButton",
                   command=lambda: self.pvp_name.get().strip() and self.s.bot.x.start_pvp(
                       self.pvp_name.get().strip().capitalize(), "you said so")).pack(side="left")
        ttk.Button(fp2, text="Stop", command=self.s.bot.x.stop_pvp).pack(side="left", padx=4)
        ttk.Label(f, text="Phone alerts (hang-ups, attacks, deaths…) are on the Phone alerts tab.",
                  style="Muted.TLabel").grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0)); r += 1
        return f

    def _alerts_tab(self, nb):
        """Everything that can buzz your phone, in one place: ntfy setup, which alerts, the stuck
        watchdog, the morning summary and boss timers."""
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(0, weight=1)
        self._ntfy_box(f).grid(row=0, column=0, sticky="we")
        pc = ttk.LabelFrame(f, text="Phone control", padding=8)
        pc.grid(row=1, column=0, sticky="we", pady=(10, 0))
        r0 = ttk.Frame(pc)
        r0.pack(fill="x")
        self._check(r0, "ntfy_control", "Let me send status / stop / hang up from the ntfy app").pack(side="left")
        pst = ttk.Label(r0, text="", style="Muted.TLabel")
        pst.pack(side="left", padx=10)

        def pc_state():
            try:
                pst.configure(text=f"({self.s.phone.state})")
                pst.after(3000, pc_state)
            except tk.TclError:
                pass
        pc_state()
        ttk.Label(pc, text="Type one of those words as a message on your topic in the ntfy app; MudPilot answers there. "
                           "Nothing else works from the phone. Anyone who knows your topic could send these, so keep it "
                           "secret.", style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))
        self._web_box(f).grid(row=2, column=0, sticky="we", pady=(10, 0))
        wd = ttk.LabelFrame(f, text="Stuck watchdog", padding=8)
        wd.grid(row=3, column=0, sticky="we", pady=(10, 0))
        r1 = ttk.Frame(wd)
        r1.pack(fill="x")
        self._check(r1, "watchdog_on", "If a loop makes no progress for").pack(side="left")
        ttk.Spinbox(r1, from_=1, to=120, textvariable=self._var("watchdog_mins"), width=4).pack(side="left", padx=4)
        ttk.Label(r1, text="min (or it stops itself lost / at a locked door), try to get going again").pack(side="left")
        ttk.Label(wd, text="It looks, then Regos back onto the loop. After 3 tries in 30 min it stops and sends a "
                           "Stuck alert. Never restarts after you stop it, a hang-up, a death or a missing key.",
                  style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))
        ms = ttk.LabelFrame(f, text="Morning summary", padding=8)
        ms.grid(row=4, column=0, sticky="we", pady=(10, 0))
        r2 = ttk.Frame(ms)
        r2.pack(fill="x")
        self._check(r2, "summary_on", "Send me how the night went at").pack(side="left")
        ttk.Entry(r2, textvariable=self._var("summary_time"), width=6).pack(side="left", padx=4)
        ttk.Label(r2, text="(24-hour, e.g. 07:00)").pack(side="left")

        def preview():
            from tkinter import messagebox as _mb
            _mb.showinfo("Morning summary", self.s.watchdog.summary_text(), parent=f)
        ttk.Button(r2, text="Preview", command=preview).pack(side="left", padx=8)
        ttk.Label(ms, text="Exp and exp/hr since the last summary, kills, deaths, rests and time resting, dropped "
                           "lines, bosses killed, and what it's doing now. Off unless ticked here.",
                  style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))
        bs = ttk.LabelFrame(f, text="Boss timers", padding=8)
        bs.grid(row=5, column=0, sticky="we", pady=(10, 0))
        r3 = ttk.Frame(bs)
        r3.pack(fill="x")
        ttk.Label(r3, text="With 'Boss due back' ticked above, warn me").pack(side="left")
        ttk.Spinbox(r3, from_=0, to=120, textvariable=self._var("boss_warn_mins"), width=4).pack(side="left", padx=4)
        ttk.Label(r3, text="min before a boss you've killed respawns, and again when it's due (0 = only when due)").pack(side="left")
        snd = ttk.LabelFrame(f, text="Sounds on this PC", padding=8)
        snd.grid(row=6, column=0, sticky="we", pady=(10, 0))
        self._check(snd, "sounds_on", "Play a sound for:").grid(row=0, column=0, columnspan=4, sticky="w")
        from .extrafeatures import SOUND_EVENTS
        self._snd_vars = {}
        for i, (ev, label) in enumerate(SOUND_EVENTS.items()):
            on = tk.BooleanVar(value=ev in (self.s.settings.sound_events or {}))
            path = tk.StringVar(value=(self.s.settings.sound_events or {}).get(ev, ""))
            self._snd_vars[ev] = (on, path)
            row, col = 1 + i // 2, (i % 2) * 3
            ttk.Checkbutton(snd, text=label, variable=on, command=self._snd_save).grid(row=row, column=col, sticky="w")
            e = ttk.Entry(snd, textvariable=path, width=22)
            e.grid(row=row, column=col + 1, sticky="w", padx=4)
            path.trace_add("write", lambda *a: self._snd_save())
            ttk.Button(snd, text="…", width=3, command=lambda p=path: self._snd_pick(p)).grid(row=row, column=col + 2, padx=(0, 12))
        ttk.Label(snd, text="Blank = the Windows ding; or pick a .wav file.", style="Muted.TLabel").grid(
            row=9, column=0, columnspan=6, sticky="w")
        ck = ttk.LabelFrame(f, text="Chat keywords", padding=8)          # 0.8.201, chatalerts.py
        ck.grid(row=7, column=0, sticky="we", pady=(10, 0))
        r4 = ttk.Frame(ck)
        r4.pack(fill="x")
        self._check(r4, "chat_alerts_on", "Flag chat lines with any of these words:").pack(side="left")
        ttk.Entry(r4, textvariable=self._var("chat_alert_words"), width=40).pack(side="left", padx=4, fill="x",
                                                                                 expand=True)
        ttk.Label(ck, text="Comma-separated, whole words, any case. Gossip / auction / telepath / gangpath / broadcast "
                           "/ say / yell from other players (never your own). Shown highlighted in the Log, and sent to "
                           "the phone if ntfy is set up above — at most one a minute, the same word from the same "
                           "player once per 10 min; the phone gets who, where and the word, not the message.",
                  style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))
        return f

    def _web_box(self, parent):
        """Phone page: watch every MudPilot on this PC from the phone's browser over Headscale/Tailscale."""
        box = ttk.LabelFrame(parent, text="Phone page (Headscale / Tailscale)", padding=8)
        r0 = ttk.Frame(box)
        r0.pack(fill="x")
        self._check(r0, "web_on", "Run the phone page").pack(side="left")
        ttk.Label(r0, text="   Address").pack(side="left")
        ttk.Entry(r0, textvariable=self._var("web_bind"), width=16).pack(side="left", padx=4)
        ttk.Label(r0, text="(blank = this PC's Headscale address)", style="Muted.TLabel").pack(side="left")
        st = ttk.Label(box, text="", style="Muted.TLabel")
        st.pack(anchor="w", pady=(4, 0))

        def state():
            try:
                st.configure(text=f"Now: {self.s.web.state}")
                st.after(2000, state)
            except tk.TclError:
                pass
        state()
        r1 = ttk.Frame(box)
        r1.pack(fill="x", pady=(6, 0))
        code_lbl = ttk.Label(r1, text="", font=("Segoe UI", 14, "bold"))

        def pair():
            if not self.s.web.server:
                from tkinter import messagebox as _mb
                _mb.showinfo("Phone page", "Tick 'Run the phone page' first and wait for it to say it's on.", parent=box)
                return
            c = self.s.web.pair_code()
            code_lbl.configure(text=f"{c[:3]} {c[3:]}   (open {self.s.web.url} on the phone; good for 5 min)")

            def gone():
                try:
                    if self.s.web.code is None or self.s.web.code.get("code") != c:
                        code_lbl.configure(text="")
                    else:
                        code_lbl.after(2000, gone)
                except tk.TclError:
                    pass
            code_lbl.after(2000, gone)

        def forget():
            from tkinter import messagebox as _mb
            if _mb.askyesno("Phone page", "Forget every paired phone? (Each MudPilot on this PC shares the pairing, "
                                          "so all of them forget it.)", parent=box):
                self.s.web.forget_phones()
                code_lbl.configure(text="")
        ttk.Button(r1, text="Pair a phone", command=pair).pack(side="left")
        ttk.Button(r1, text="Forget all phones", command=forget).pack(side="left", padx=8)
        code_lbl.pack(side="left", padx=8)
        ttk.Label(box, text="Watch-only: every character on this PC, its live screen, HP/MA, exp/hr, where it is and "
                            "its party. Nothing on the page can walk, type or change a setting. It only listens on your "
                            "tailnet address, and a phone needs the pairing code once. Tick it in each MudPilot you "
                            "want to open from the phone.", style="Muted.TLabel", wraplength=640,
                  justify="left").pack(anchor="w", pady=(6, 0))
        return box

    def _snd_save(self):
        ev = {k: p.get().strip() for k, (on, p) in self._snd_vars.items() if on.get()}
        self.s.settings.sound_events = ev
        self.s.settings.save()

    def _snd_pick(self, var):
        from tkinter import filedialog
        p = filedialog.askopenfilename(parent=self.root, filetypes=[("Sounds", "*.wav")])
        if p:
            var.set(p)

    def _ntfy_box(self, parent):
        """Phone alerts (ntfy). The topic is a secret, so it lives in Credential Manager."""
        from . import notify as N
        box = ttk.LabelFrame(parent, text="Phone alerts (ntfy app)", padding=8)
        top = ttk.Frame(box)
        top.pack(fill="x")
        self._check(top, "ntfy_on", "Send alerts to my phone").pack(side="left")
        ttk.Label(top, text="   Topic").pack(side="left")
        tv = tk.StringVar(value=N.get_topic())
        te = ttk.Entry(top, textvariable=tv, width=24, show="•")
        te.pack(side="left", padx=4)
        shown = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="show", variable=shown,
                        command=lambda: te.configure(show="" if shown.get() else "•")).pack(side="left")
        res = ttk.Label(box, text="", style="Muted.TLabel")

        def save(*a):
            ok = N.set_topic(tv.get())
            where = "Windows Credential Manager" if sys.platform == "win32" else "the system keyring"
            res.configure(text=f"topic saved in {where}" if ok else "couldn't save the topic")
        te.bind("<FocusOut>", save)
        te.bind("<Return>", save)

        def test():
            save()
            if self.s.notify.send("test", "Test alert from MudPilot", force=True):
                res.configure(text="test sent…")
                self.root.after(3000, lambda: res.configure(text=f"test {self.s.notify.last_result or 'sent'}"))
            else:
                res.configure(text="put your topic in first")
        ttk.Button(top, text="Send test", command=test).pack(side="left", padx=6)
        ttk.Label(top, text="Server").pack(side="left", padx=(8, 2))
        ttk.Entry(top, textvariable=self._var("ntfy_server"), width=20).pack(side="left")
        kf = ttk.Frame(box)
        kf.pack(fill="x", pady=(4, 0))
        cur = set(self.s.settings.ntfy_kinds or [])
        kv = {}

        def kinds(*a):
            self.s.settings.ntfy_kinds = [k for k, v in kv.items() if v.get()]
            self._save_soon() if hasattr(self, "_save_soon") else self.s.settings.save()
        ttk.Label(kf, text="Alert me about:").grid(row=0, column=0, columnspan=3, sticky="w")
        for i, (k, lbl) in enumerate(N.KINDS.items()):
            kv[k] = tk.BooleanVar(value=k in cur)
            ttk.Checkbutton(kf, text=lbl, variable=kv[k], command=kinds).grid(row=1 + i // 3, column=i % 3,
                                                                                 sticky="w", padx=(0, 16), pady=1)
        res.pack(anchor="w", pady=(4, 0))
        ttk.Label(box, text="Pick a topic nobody would guess (anyone with it can read your alerts) and subscribe to "
                            "it in the ntfy phone app.", style="Muted.TLabel").pack(anchor="w")
        return box

    def _pvp_save(self):
        rows = []
        for cv, rv in self.pvp_vars:
            c = cv.get().strip()
            if c:
                try:
                    rounds = int(rv.get() or 0)
                except ValueError:
                    rounds = 0
                rows.append({"cast": c, "rounds": rounds, "enabled": True})
        self.s.settings.pvp_spells = rows
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, self.s.settings.save)

    # ------------------------------------------------------------------ layout / fonts
    def _apply_layout(self):
        """MegaMUD layout: MUD window left (2/3), conversations top-right, map bottom-right (half height)."""
        st = self.s.settings
        try:
            self.root.update_idletasks()
            W = self.main_pane.winfo_width()
            H = self.right_pane.winfo_height()
            if W > 100:
                self.main_pane.sashpos(0, int(W * min(max(st.layout_main, 0.3), 0.9)))
            if H > 100 and st.dock_chat and len(self.right_pane.panes()) > 1:
                # conversations never open squeezed to a couple of lines (Dan: map ~60%, conversations ~40%)
                self.right_pane.sashpos(0, int(H * min(max(st.layout_right, 0.3), 0.8)))
            if st.map_minimized:
                self.toggle_map_min(force=True)
        except tk.TclError:
            pass

    def _early_settings(self):
        """Settings before the session exists (window size at start-up)."""
        s = getattr(self, "s", None)
        if s is not None:
            return s.settings
        from . import config
        if not hasattr(self, "_pre_settings"):
            self._pre_settings = config.Settings.load() if hasattr(config.Settings, "load") else config.Settings()
        return self._pre_settings

    def _reopen_windows(self):
        """Bring back the pop-outs that were open last time, where they were."""
        openers = {"Map": self.open_map_window, "Party": self.open_party, "Conversations": self.open_chat_window}
        for key in list(self.s.settings.open_windows or []):
            fn = openers.get(key)
            if fn:
                try:
                    fn()
                except Exception as ex:
                    self.add_log(f"Couldn't reopen {key}: {ex}")

    def _remember_layout(self):
        st = self.s.settings
        try:
            W = self.main_pane.winfo_width()
            if W > 100:
                st.layout_main = round(self.main_pane.sashpos(0) / W, 3)
            H = self.right_pane.winfo_height()
            if H > 100 and len(self.right_pane.panes()) > 1 and not st.map_minimized and \
                    getattr(self, "_layout_dragged", False):
                # only when you moved it: closing (a restart, minimised, half-drawn) saved squeezed splits
                st.layout_right = round(self.right_pane.sashpos(0) / H, 3)
            st.save()
        except tk.TclError:
            pass

    def toggle_map_min(self, force=False):
        """Shrink the map/tools panel to a thin bar (conversations get the room) or bring it back."""
        st = self.s.settings
        if not force:
            st.map_minimized = not st.map_minimized
            st.save()
        rp = self.right_pane
        if st.map_minimized:
            self.tools_nb.pack_forget()
            self.tools_min_btn.configure(text="▔ Restore")
            if len(rp.panes()) > 1:
                self.root.update_idletasks()
                rp.sashpos(0, rp.winfo_height() - 34)
        else:
            self.tools_nb.pack(fill="both", expand=True)
            self.tools_min_btn.configure(text="▁ Minimize")
            if len(rp.panes()) > 1:
                self.root.update_idletasks()
                rp.sashpos(0, int(rp.winfo_height() * st.layout_right))

    def record_route(self, mode, walk):
        """Paths → More → Record a loop / path by walking it, or Draw one: opens the map window and starts its
        recorder (Dan, 2026-11-12: he opened 'Build a loop from the map' — the lair-chain finder — and found no map)."""
        self.open_map_window()

        def go(tries=10):
            bar = getattr(self, "_record_bar", None)
            try:
                alive = bar is not None and bar.f.winfo_exists()
            except tk.TclError:
                alive = False
            if not alive:
                if tries:
                    self.root.after(200, lambda: go(tries - 1))
                return
            bar._start(mode, walk=walk)
        go()

    def open_map_window(self):
        """A second map of its own: look around anywhere (right-click a room to centre there) while the
        built-in map keeps following you. Show 20×20, 30×30 or 50×50 rooms."""
        def make(w):
            from .roominfo import RoomPanel, RecordBar
            fr = ttk.Frame(w)
            bar = ttk.Frame(fr, padding=(6, 4))
            bar.pack(fill="x")
            bar2 = ttk.Frame(fr, padding=(6, 0, 6, 4))
            bar2.pack(fill="x")
            body = ttk.PanedWindow(fr, orient="horizontal")
            m = MapView(body, self.s, on_goto=self.goto_room, follow=False)
            panel = RoomPanel(body, self, m)
            m.on_click = panel.show
            size = tk.StringVar(value=str(self.s.settings.map_window_rooms or "Zoom"))

            def set_size(*a):
                v = size.get()
                m.grid_n = int(v.split("×")[0]) if v[0].isdigit() else 0
                self.s.settings.map_window_rooms = v
                self.s.settings.save()
                m.redraw()
            ttk.Label(bar, text="Rooms").pack(side="left")
            cb = ttk.Combobox(bar, textvariable=size, values=("Zoom", "20×20", "30×30", "50×50"), width=7, state="readonly")
            cb.pack(side="left", padx=4)
            cb.bind("<<ComboboxSelected>>", set_size)

            def me():
                m.scout = None
                m.redraw()
            ttk.Button(bar, text="⌖ Me", command=me).pack(side="left", padx=6)
            MapSearch(bar, m)
            RecordBar(bar2, self, m)
            ttk.Label(bar2, text="Find room: '17 1626', a name or a monster, Enter — shows it, doesn't walk · "
                                 "click a room for what's there · right-click to look from it · double-click to walk",
                      style="Muted.TLabel").pack(side="left", padx=10)
            body.add(m, weight=3)
            body.add(panel, weight=1)
            body.pack(fill="both", expand=True)
            self.extra_maps.append(m)
            set_size()
            self.root.after(100, m.redraw)
            return fr
        popout(self, "Map", make, "900x600")

    def reset_layout(self):
        st = self.s.settings
        st.layout_main, st.layout_right, st.map_minimized = 0.667, 0.4, False
        if not st.dock_chat:
            self.toggle_dock()
        self.toggle_map_min(force=True)
        self._apply_layout()
        st.save()

    def font_dialog(self):
        FontDialog(self.root, self)

    def zoom_font(self, d):
        """A− / A+ (or Ctrl+mouse wheel, Ctrl+= / Ctrl+-): change the MUD window's font size."""
        st = self.s.settings
        st.term_font_size = max(6, min(int(st.term_font_size or 12) + d, 40))
        self.apply_fonts()
        st.save()
        self.add_log(f"MUD window font: {st.term_font} {st.term_font_size}")

    def _term_font(self):
        """The MUD window's font. Settings → Other → BBS art (CP437) on: one that draws the IBM PC box / block
        glyphs at letter width (cp437.pick_font); off (default): exactly the font picked in Font…."""
        st = self.s.settings
        fam, size = st.term_font or "Consolas", int(st.term_font_size or 10)
        if getattr(st, "cp437_terminal", False):
            try:
                from . import cp437
                fam = cp437.pick_font(self.root, fam, size)
            except Exception:
                pass
        return (fam, size)

    def apply_fonts(self):
        from .windows import CHAT_PANES
        st = self.s.settings
        self.term.configure(font=self._term_font())
        if getattr(self, "scr", None) is not None:
            try:
                self.scr.configure(font=self._term_font())
            except tk.TclError:
                pass
        self.entry.configure(font=(st.term_font, int(st.term_font_size) + 1))
        for cp in list(CHAT_PANES):
            try:
                cp.box.configure(font=(st.chat_font, int(st.chat_font_size)))
            except tk.TclError:
                pass

    def toggle_dock(self):
        st = self.s.settings
        st.dock_chat = not st.dock_chat
        nb = self.map.master.master          # (the notebook; see show_tab)
        if st.dock_chat:
            self.right_pane.insert(0, self.dock_frame, weight=2)
            nb.hide(self.chat_tab)
        else:
            self.right_pane.forget(self.dock_frame)
            nb.add(self.chat_tab)
            nb.insert(6, self.chat_tab, text="Chat")
        st.save()

    def open_exp_chart(self):
        popout(self, "Experience", lambda w: ExpChartPane(w, self), "820x520")

    def open_stats_window(self):
        popout(self, "Session statistics", lambda w: StatsPane(w, self), "640x640")

    def open_chat_window(self):
        popout(self, "Conversations", lambda w: ChatPane(w, self), "720x480")

    def open_calc(self):
        popout(self, "Inventory calculator", lambda w: CalcWindowPane(w, self), "1020x700")

    def open_guides(self, gid=None):
        """Help → Step-by-step guides (0.8.201): a floating step panel + a flashing border round what to click."""
        from . import guides
        return guides.start(self, gid) if gid else guides.chooser(self)

    def open_guide(self):
        """The setup guide ships next to MudPilot.bat as a PDF (and an editable Word copy)."""
        root = config.APP_DIR
        for name in ("MudPilot Setup Guide.pdf", "MudPilot Setup Guide.docx"):
            path = os.path.join(root, name)
            if os.path.exists(path):
                if not config.open_path(path):          # (the PDF viewer / Word)
                    import webbrowser
                    webbrowser.open("file:///" + path.replace("\\", "/"))
                return
        messagebox.showinfo("MudPilot", "The setup guide (MudPilot Setup Guide.pdf) should be in the MudPilot folder, "
                                        "next to MudPilot.")

    def about(self):
        from . import __version__
        d = tk.Toplevel(self.root)
        d.title("About MudPilot")
        d.configure(background=PANEL)
        d.resizable(False, False)
        f = ttk.Frame(d, padding=20)
        f.pack()
        if getattr(self, "_logo_big", None):
            ttk.Label(f, image=self._logo_big).pack()
        ttk.Label(f, text=f"MudPilot {__version__}", style="Head.TLabel").pack(pady=(10, 2))
        ttk.Label(f, text="A MegaMUD-style client for MajorMUD with MME built in.", style="Muted.TLabel").pack()
        ttk.Label(f, text="Thanks to syntax53 for MajorMUD Explorer (MME): MudPilot's map, monster, item and spell data, "
                          "and many of its game calculations, come from MME.", style="Muted.TLabel",
                  justify="center", wraplength=420).pack(pady=(10, 0))
        lk = ttk.Label(f, text="github.com/syntax53/MMUD-Explorer", style="Muted.TLabel", cursor="hand2")
        lk.pack()
        lk.bind("<Button-1>", lambda e: __import__("webbrowser").open("https://github.com/syntax53/MMUD-Explorer"))
        ttk.Label(f, text="Thanks also to Phrixas for pMUD: several of MudPilot's features were designed after studying "
                          "how pMUD does them, and its MegaMUD messages import comes straight from pMUD.",
                  style="Muted.TLabel", justify="center", wraplength=420).pack(pady=(8, 0))
        ttk.Label(f, text="Free software under the GNU GPL v3.0 — github.com/MudPilot/MudPilot", style="Muted.TLabel",
                  justify="center", wraplength=420).pack(pady=(8, 0))
        ttk.Button(f, text="OK", style="Accent.TButton", command=d.destroy).pack(pady=(14, 0))
        d.transient(self.root)

    # ------------------------------------------------------------------ profiles
    def switch_profile(self, name, save_current=True):
        if save_current:
            self.s.settings.save()
        if self.s.bot.walking:
            self.s.bot.stop("Stopped: switched character")
        new = config.Settings.load(name)
        new.profile = name
        old_board = self.s.settings.board
        self.s.settings = new
        self.s.macros.settings = new
        self.s.chat.settings = new
        for key, var in self._vars.items():
            val = getattr(new, key)
            var.set(", ".join(val) if isinstance(val, list) else val)
        self.s.state.max_hp = self.s.state.max_ma = 0
        new.save()
        self.profile_box.configure(values=config.Settings.list_profiles())
        self.profile_var.set(name)
        self._sp_key = None
        if new.board != old_board:
            self.s.switch_board()
            self._after_board_change()
        self.board_var.set(new.board)
        self.refresh_buffs()
        self.refresh_remote()
        for c, v in getattr(self, "rc_vars", {}).items():
            v.set(new.remote_channels.get(c, False))
        self._refresh_config_title()
        self.add_log(f"Character profile: {name}")

    def set_board(self, board, announce=True):
        """Point the current character at a board and load that board's MME data/paths/timers."""
        st = self.s.settings
        if self.s.bot.walking:
            self.s.bot.stop("Stopped: switched board")
        st.board = board
        st.save()
        self.s.switch_board()
        self.board_var.set(board)
        self._after_board_change()
        if announce:
            self.add_log(f"{st.profile} now plays on board '{board}'")

    def ask_board_first_run(self):
        """(0.8.201, Dan — stock_routing #7: a fresh install routed on Paradigm's map without saying so.) Ask once
        which board this is: Paradigm, Stock, or import your own MME file. Closing it keeps Paradigm."""
        win = tk.Toplevel(self.root)
        win.title("Which board do you play on?")
        win.configure(background=PANEL)
        win.resizable(False, False)
        win.transient(self.root)
        fr = ttk.Frame(win, padding=16)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="MudPilot's maps and routes come from MME data for your BBS.\n"
                           "Which board do you play on? (File → Import MME database changes it later.)",
                  justify="left").pack(anchor="w", pady=(0, 12))

        def pick(board):
            win.destroy()
            if board is None:
                self.import_mme()
            else:
                self.set_board(board)
        row = ttk.Frame(fr)
        row.pack(anchor="w")
        for label, board in (("Paradigm", "Paradigm"), ("Stock MajorMUD", "Stock")):
            if os.path.exists(config.world_path(board)):
                ttk.Button(row, text=label, command=lambda b=board: pick(b)).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Import my own MME file…", command=lambda: pick(None)).pack(side="left")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        try:
            win.grab_set()
        except tk.TclError:
            pass

    def _after_board_change(self):
        self._sp_key = None
        self._map_seq = -1
        self.refresh_paths()
        self.refresh_bosses()
        self.map.redraw()
        w = self.s.world
        self.add_log(f"Board '{self.s.settings.board}': " + (
            f"{len(w.rooms):,} rooms from {getattr(w, 'source', 'MME')}, {len(self.s.paths)} path(s)"
            if w.loaded else "no MME data yet — File → Import MME database"))

    def new_profile(self, copy=False):
        name = simpledialog.askstring("New profile", "Character name:", parent=self.root)
        if not name:
            return
        self.s.settings.save()
        if copy:
            self.s.settings.profile = name
        else:
            keep = self.s.settings
            fresh = config.Settings()
            fresh.host, fresh.port, fresh.triggers = keep.host, keep.port, keep.triggers
            fresh.board = keep.board
            fresh.profile = name
            self.s.settings = fresh
        self.s.settings.save()
        self.switch_profile(name, save_current=False)

    def import_megamud_char(self):
        f = filedialog.askopenfilename(title="Select MegaMUD character file (in MegaMUD\\Chars)",
                                       filetypes=[("MegaMUD character", "*.ini"), ("All files", "*.*")])
        if f:
            ImportCharDialog(self.root, self, f)

    def _bless_tab(self, nb):
        """Like MegaMUD's Bless Spells box: type (or pick) the spell's short command; Secs 0 = recast at
        the spell's MME duration minus the margin. Priority = cast even with monsters around / in combat."""
        f = ttk.Frame(nb, padding=10)
        cfg = self.s.settings
        top = ttk.Frame(f)
        top.grid(row=0, column=0, columnspan=2, sticky="w")
        self._check(top, "auto_bless", "Keep blesses up").pack(side="left")
        ttk.Label(top, text="   recast").pack(side="left")
        ttk.Spinbox(top, from_=0, to=300, width=4, textvariable=self._var("bless_margin_secs")).pack(side="left", padx=4)
        ttk.Label(top, text="s before they wear off", style="Muted.TLabel").pack(side="left")
        self._check(top, "bless_while_resting", "Also while resting / meditating").pack(side="left", padx=(16, 0))
        names = self._bless_choices()

        def grid(parent, title, rows, prio):
            box = ttk.LabelFrame(parent, text=title, padding=8)
            hdr = (("Priority", 0), ("Bless spells", 2), ("Secs", 3)) if prio else (("Bless spells", 2), ("Secs", 3))
            for t, c in hdr:
                ttk.Label(box, text=t, style="Muted.TLabel").grid(row=0, column=c, sticky="w")
            out = []
            for i in range(10):
                d = rows[i] if i < len(rows) else {}
                pv = tk.BooleanVar(value=bool(d.get("in_combat") or d.get("priority")))
                cv = tk.StringVar(value=d.get("cast", ""))
                sv = tk.StringVar(value=str(d.get("every", d.get("secs", 0)) or 0))
                if prio:
                    ttk.Checkbutton(box, variable=pv).grid(row=i + 1, column=0)
                ttk.Label(box, text=f"{i + 1}").grid(row=i + 1, column=1, padx=(2, 4))
                ttk.Combobox(box, textvariable=cv, values=names, width=10).grid(row=i + 1, column=2, pady=1)
                ttk.Entry(box, textvariable=sv, width=5).grid(row=i + 1, column=3, padx=(4, 0))
                if prio:
                    ttk.Button(box, text="⚙", width=2, command=lambda cv=cv: self._bless_more(cv.get())).grid(
                        row=i + 1, column=4, padx=(4, 0))
                out.append((pv, cv, sv))
            return box, out

        simple = [bf for bf in (cfg.buffs or []) if not self._buff_advanced(bf)]
        sbox, self.sb_vars = grid(f, "Bless spells", simple, True)
        sbox.grid(row=1, column=0, sticky="nw", pady=(8, 0))
        pbox, self.pb_vars = grid(f, "Party bless spells (in a party)", list(cfg.party_blesses or []), False)
        pbox.grid(row=1, column=1, sticky="nw", pady=(8, 0), padx=(12, 0))
        for pv, cv, sv in self.sb_vars:
            for v in (pv, cv, sv):
                v.trace_add("write", lambda *a: self._sb_save())
        for _pv, cv, sv in self.pb_vars:
            for v in (cv, sv):
                v.trace_add("write", lambda *a: self._pb_save())
        bb = ttk.Frame(sbox)
        bb.grid(row=11, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(bb, text="Reset", command=lambda: [cv.set("") or sv.set("0") or pv.set(False)
                                                      for pv, cv, sv in self.sb_vars]).pack(side="left")
        ttk.Label(pbox, text="'gpro' casts once; 'prot {name}' blesses each member.", style="Muted.TLabel",
                  wraplength=220).grid(row=11, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.sb_status = []
        stf = ttk.Frame(f)
        stf.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.bless_status_lbl = ttk.Label(stf, text="", style="Muted.TLabel", justify="left")
        self.bless_status_lbl.pack(anchor="w")
        bb2 = ttk.Frame(f)
        bb2.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(bb2, text="Ability-check rules…", command=self.open_bless_rules).pack(side="left")
        ttk.Button(bb2, text="Add a bless from one of my items…", command=self.add_item_bless).pack(side="left", padx=6)
        self.refresh_buffs()
        return f

    def _bless_choices(self):
        """Short commands of the non-attack spells you know (or can learn), for the drop-downs."""
        from .spells import spell_kind
        try:
            sps = list(self.s.known_spell_dicts())
            if not sps:
                from .spells import class_spells
                w = self.s.world
                cls = next((k for k, v in w.classes.items()
                            if v.get("Name", "").lower() == (self.s.state.char_class or self.s.settings.char_class or "").lower()), 0)
                sps = class_spells(w, cls, self.s.settings.char_level or self.s.state.level) if cls else []
            return sorted({(sp.get("Short") or "").strip() for sp in sps if sp.get("Short") and spell_kind(sp) is None})
        except Exception:
            return []

    def open_bless_rules(self):
        """The ability-check rules (keep Spellcasting at +100 …) and the status of every bless."""
        d = tk.Toplevel(self.root)
        d.title("Bless rules - MudPilot")
        d.geometry("760x360")
        af = ttk.Frame(d, padding=10)
        af.pack(fill="both", expand=True)
        r0 = ttk.Frame(af)
        r0.pack(fill="x")
        ttk.Label(r0, text="General ability command").pack(side="left")
        ttk.Entry(r0, textvariable=self._var("abil_check_cmd"), width=12).pack(side="left", padx=4)
        ttk.Label(r0, text="every").pack(side="left")
        ttk.Spinbox(r0, from_=10, to=3600, width=5, textvariable=self._var("abil_check_secs")).pack(side="left", padx=4)
        ttk.Label(r0, text="s", style="Muted.TLabel").pack(side="left")
        cols = ("cast", "rule", "now")
        self.bl_tree = ttk.Treeview(af, columns=cols, show="tree headings", height=8)
        self.bl_tree.heading("#0", text="Bless")
        self.bl_tree.column("#0", width=120)
        for c, w, t in zip(cols, (70, 220, 220), ("Cast", "Rule", "Status")):
            self.bl_tree.heading(c, text=t)
            self.bl_tree.column(c, width=w)
        self.bl_tree.tag_configure("need", foreground="#ffb347")
        self.bl_tree.tag_configure("ok", foreground="#5cff7a")
        self.bl_tree.tag_configure("off", foreground=MUTED)
        self.bl_tree.pack(fill="both", expand=True, pady=6)
        self.bl_tree.bind("<Double-1>", lambda e: self.edit_buff())
        self.bl_tree.bind("<<TreeviewSelect>>", lambda e: self._bless_selected())
        b = ttk.Frame(af)
        b.pack(fill="x")
        ttk.Button(b, text="Add ability rule…", command=lambda: self.edit_buff(new=True)).pack(side="left")
        mb = ttk.Menubutton(b, text="Mana regen ▾")
        pm = tk.Menu(mb, tearoff=0)
        for short, lbl in (("flux", "Mana flux (flux)"), ("ntap", "Nature tap (ntap) — druid"),
                           ("nity", "Serenity (nity) — priest")):
            pm.add_command(label=lbl, command=lambda sh=short: self.edit_buff(new=True, preset=sh))
        mb["menu"] = pm
        mb.pack(side="left", padx=4)
        ttk.Button(b, text="Edit…", command=self.edit_buff).pack(side="left", padx=4)
        ttk.Button(b, text="On/Off", command=self.toggle_buff).pack(side="left")
        ttk.Button(b, text="Remove", command=self.remove_buff).pack(side="left", padx=4)
        ttk.Button(b, text="Check now", command=self.check_buffs_now).pack(side="left")
        self.bl_sel_lbl = ttk.Label(b, text="", style="Muted.TLabel")
        self.bl_sel_lbl.pack(side="left", padx=(12, 4))
        self.bl_target = tk.StringVar()
        sp = ttk.Spinbox(b, from_=-500, to=999, increment=5, textvariable=self.bl_target, width=6)
        sp.pack(side="left")
        sp.bind("<Return>", lambda e: self._bless_set_target())
        ttk.Button(b, text="Set target", command=self._bless_set_target).pack(side="left", padx=4)
        self.refresh_buffs()

    def add_item_bless(self):
        """Items you carry that cast a spell (MME 'CastsSp'), e.g. the emerald-tipped crozier's divine
        intervention. Pick one: MudPilot equips it, uses it, and puts your weapon back — no responses to set up."""
        from .gamestate import worn_list, parse_item_list
        from .spells import spell_duration
        w, st = self.s.world, self.s.state
        if not st.carrying:
            if self.s.telnet.connected:
                self.s.send("i")
                self.root.after(2000, self.add_item_bless)
            else:
                messagebox.showinfo("Bless", "Type 'i' in the game first so MudPilot knows what you carry.")
            return
        worn = {n.lower() for n, _slot in worn_list(st.carrying)}
        names = {re.sub(r"\s*\([^)]*\)\s*$", "", n).strip().lower() for _q, n in parse_item_list(st.carrying)}
        rows = []
        for g in (getattr(w, "gear", {}) or {}).values():
            nm = (g.get("name") or "").lower()
            if nm in names and 43 in (g.get("abils") or {}):
                sp = w.spells.get(int(g["abils"][43]))
                if sp:
                    rows.append((g["name"], sp, nm in worn))
        if not rows:
            messagebox.showinfo("Bless", "None of the items you carry cast a spell (per MME).")
            return
        d = tk.Toplevel(self.root)
        d.title("Bless from an item")
        d.transient(self.root)
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        tv = ttk.Treeview(fr, columns=("spell", "lasts", "worn"), show="tree headings", height=min(10, len(rows)))
        tv.heading("#0", text="Item")
        tv.column("#0", width=200)
        for c, t, wd in (("spell", "Spell", 160), ("lasts", "Lasts", 70), ("worn", "Wearing it", 80)):
            tv.heading(c, text=t)
            tv.column(c, width=wd)
        tv.pack(fill="both", expand=True)
        for i, (item, sp, on) in enumerate(rows):
            dur = spell_duration(sp, self.s.settings.char_level or st.level)
            tv.insert("", "end", iid=str(i), text=item, values=(sp["Name"], f"{dur // 60}m {dur % 60}s" if dur else "?",
                                                               "yes" if on else "no"))
        tv.selection_set("0")

        def add():
            sel = tv.selection()
            if not sel:
                return
            item, sp, on = rows[int(sel[0])]
            word = item.split()[-1]
            bf = {"name": f"{sp['Name']} ({item})", "cast": f"use {word}", "every": 0, "enabled": True,
                  "op": ">=", "value": 0, "equip_cmd": "" if on else f"eq {item}"}
            cfg = self.s.settings
            cfg.buffs = [b for b in (cfg.buffs or []) if (b.get("cast") or "").lower() != bf["cast"]] + [bf]
            cfg.save()
            self.add_log(f"Bless added: {bf['name']} — " + ("used while worn" if on else
                         f"equips the {item}, uses it, then puts your weapon back"))
            d.destroy()
            if getattr(self, "settings_win", None) is not None:
                try:
                    self.settings_win.destroy()
                except tk.TclError:
                    pass
                self.open_settings("Bless")
        ttk.Button(fr, text="Add as a bless", style="Accent.TButton", command=add).pack(anchor="e", pady=(8, 0))

    def _bless_more(self, cast):
        """More for one bless: equip an item to cast its spell (emerald-tipped crozier), start/wear-off text…"""
        cast = (cast or "").strip()
        bl = self.s.settings.buffs or []
        i = next((k for k, b in enumerate(bl) if (b.get("cast") or "").strip().lower() == cast.lower()), None)
        if not cast or i is None:
            messagebox.showinfo("Bless", "Type the spell in that slot first.")
            return
        BuffDialog(self.root, self, i)

    @staticmethod
    def _buff_advanced(bf) -> bool:
        return bool(str(bf.get("ability") or "").strip() or (bf.get("check_cmd") or "").strip())

    def _sb_save(self):
        """Self-bless slots ↔ the simple (timer / wear-off) rules in settings.buffs; ability rules are kept."""
        cfg = self.s.settings
        old = {b.get("cast", "").lower(): b for b in (cfg.buffs or []) if not self._buff_advanced(b)}
        rows = []
        for pv, cv, ev in self.sb_vars:
            c = cv.get().strip()
            if not c:
                continue
            try:
                every = int(ev.get() or 0)
            except ValueError:
                every = 0
            b = dict(old.get(c.lower()) or {"name": c, "op": ">=", "value": 0, "enabled": True})
            b.update({"cast": c, "every": every, "in_combat": bool(pv.get()), "priority": bool(pv.get())})
            b.setdefault("name", c)
            rows.append(b)
        cfg.buffs = rows + [b for b in (cfg.buffs or []) if self._buff_advanced(b)]
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(600, cfg.save)

    def _buff_rule_text(self, bf):
        if str(bf.get("ability") or "").strip():
            r = f"{bf['ability']} [{bf.get('source', 'spells')}] {bf.get('op', '>=')} {int(bf.get('value', 0)):+d}"
            if (bf.get("check_cmd") or "").strip():
                r += f" via '{bf['check_cmd']}'"
        elif (bf.get("check_cmd") or "").strip():
            r = f"'{bf['check_cmd']}' {bf.get('op', '>=')} {int(bf.get('value', 0)):+d}"
        elif bf.get("ability"):
            r = f"{bf['ability']} {bf.get('op', '>=')} {int(bf.get('value', 0)):+d}"
        elif bf.get("every"):
            r = f"every {bf['every']}s"
        else:
            auto = self.s.bot.auto_recast(bf)
            r = f"every {auto}s (lasts {auto + int(self.s.settings.bless_margin_secs or 15)}s)" if auto else "on wear-off only"
        if bf.get("off_msg"):
            r += " / wear-off text"
        return r

    def _bless_live(self, bf):
        return self.s.bot.x.bless_state(bf)

    def refresh_buffs(self):
        self._bless_status_refresh()
        try:
            if not hasattr(self, "bl_tree") or not self.bl_tree.winfo_exists():
                return
        except tk.TclError:
            return
        sel = self.bl_tree.selection()
        self.bl_tree.delete(*self.bl_tree.get_children())
        for i, bf in enumerate(self.s.settings.buffs or []):
            if not bf.get("enabled", True):
                status, tag = "off", "off"
            else:
                need, why = self.s.bot.buff_status(bf)
                note = self.s.bot.buff_note.get(bf.get("cast", ""))
                tries = self.s.bot._rerolls.get(bf.get("cast", ""), 0)
                status = note or (why + (f" · cast {tries}x" if tries > 1 else ""))
                live = self._bless_live(bf)
                if live and not note:
                    status = f"{live} · {status}" if why not in ("due",) else status
                tag = "need" if need else "ok"
            self.bl_tree.insert("", "end", iid=str(i), text=bf.get("name") or bf.get("cast"),
                                values=(bf.get("cast", ""), self._buff_rule_text(bf), status), tags=(tag,))
        if sel and self.bl_tree.exists(sel[0]):
            self.bl_tree.selection_set(sel)

    def _bless_status_refresh(self):
        lab = getattr(self, "bless_status_lbl", None)
        if lab is not None:
            try:
                parts = []
                for bf in self.s.settings.buffs or []:
                    if not bf.get("enabled", True) or self._buff_advanced(bf):
                        continue
                    _need, why = self.s.bot.buff_status(bf)
                    live = self._bless_live(bf)
                    parts.append(f"{bf.get('cast')}: {live + ' · ' if live else ''}{why}")
                lab.configure(text="   ".join(parts))
            except tk.TclError:
                pass

    def _sel_buff(self):
        sel = self.bl_tree.selection()
        return int(sel[0]) if sel else None

    def _regen_preset(self) -> str:
        """The mana regen spell for this class (Dan, 2026-11-18: 'Keep mana flux up' gave Revolution, a druid, the
        mage's flux — druids cast nature tap, priests serenity)."""
        cls = (getattr(self.s.state, "char_class", "") or self.s.settings.char_class or "").strip().lower()
        return "ntap" if cls.startswith("druid") else "nity" if cls.startswith("priest") else "flux"

    def edit_buff(self, new=False, preset=None):
        i = None if new else self._sel_buff()
        if not new and i is None:
            return
        BuffDialog(self.root, self, i, preset)

    def toggle_buff(self):
        i = self._sel_buff()
        if i is not None:
            bf = self.s.settings.buffs[i]
            bf["enabled"] = not bf.get("enabled", True)
            self.s.settings.save()
            self.refresh_buffs()

    def remove_buff(self):
        i = self._sel_buff()
        if i is not None:
            del self.s.settings.buffs[i]
            self.s.settings.save()
            self.refresh_buffs()

    def _bless_selected(self):
        i = self._sel_buff()
        if i is None or i >= len(self.s.settings.buffs):
            return
        bf = self.s.settings.buffs[i]
        self.bl_sel_lbl.configure(text=f"{bf.get('name') or bf.get('cast')} target ({bf.get('op', '>=')}):")
        self.bl_target.set(str(int(bf.get("value", 0) or 0)))

    def _bless_set_target(self):
        i = self._sel_buff()
        if i is None:
            return
        try:
            val = int(self.bl_target.get())
        except ValueError:
            return
        bf = self.s.settings.buffs[i]
        bf["value"] = val
        self.s.bot._rerolls.pop(bf.get("cast", ""), None)
        self.s.settings.save()
        self.refresh_buffs()
        self.add_log(f"{bf.get('name') or bf.get('cast')} target set to {val:+d}")

    # ------------------------------------------------------------------ events
    def _events_tab(self, nb):
        from .events import describe
        f = ttk.Frame(nb, padding=10)
        ttk.Label(f, text="Run things on a timer, when text appears, or when a boss is due. A boss hunt walks "
                          "to the boss, kills it, then goes back to the loop or path you were on.",
                  style="Muted.TLabel", wraplength=460).pack(anchor="w")
        cols = ("when", "do", "status")
        self.ev_tree = ttk.Treeview(f, columns=cols, show="tree headings", height=12)
        self.ev_tree.heading("#0", text="Event")
        self.ev_tree.column("#0", width=130)
        for c, w, t in zip(cols, (130, 160, 120), ("When", "Does", "Next")):
            self.ev_tree.heading(c, text=t)
            self.ev_tree.column(c, width=w)
        self.ev_tree.tag_configure("off", foreground=MUTED)
        self.ev_tree.tag_configure("run", foreground="#5cff7a")
        self.ev_tree.pack(fill="both", expand=True, pady=8)
        self.ev_tree.bind("<Double-1>", lambda e: self.edit_event())
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Add…", style="Accent.TButton", command=lambda: self.edit_event(new=True)).pack(side="left")
        ttk.Button(b, text="Edit…", command=self.edit_event).pack(side="left", padx=4)
        ttk.Button(b, text="On/Off", command=self.toggle_event).pack(side="left")
        ttk.Button(b, text="Run now", command=self.run_event_now).pack(side="left", padx=4)
        ttk.Button(b, text="Remove", command=self.remove_event).pack(side="right")
        self.s.events.on_change = lambda: self.root.after(0, self.refresh_events)
        self.refresh_events()
        return f

    def refresh_events(self):
        from .events import describe
        if not hasattr(self, "ev_tree"):
            return
        sel = self.ev_tree.selection()
        self.ev_tree.delete(*self.ev_tree.get_children())
        for i, ev in enumerate(self.s.settings.events or []):
            when, do = describe(ev)
            stt = self.s.events.status(ev)
            tag = "off" if stt == "off" else ("run" if stt.startswith(("running", "waiting", "due")) else "")
            self.ev_tree.insert("", "end", iid=str(i), text=ev.get("name") or "(unnamed)",
                                values=(when, do, stt), tags=(tag,))
        if sel and self.ev_tree.exists(sel[0]):
            self.ev_tree.selection_set(sel)

    def _sel_event(self):
        sel = self.ev_tree.selection()
        return int(sel[0]) if sel else None

    def edit_event(self, new=False):
        i = None if new else self._sel_event()
        if not new and i is None:
            return
        EventDialog(self.root, self, i)

    def toggle_event(self):
        i = self._sel_event()
        if i is not None:
            ev = self.s.settings.events[i]
            ev["enabled"] = not ev.get("enabled", True)
            ev.pop("armed_at", None)
            self.s.settings.save()
            self.refresh_events()

    def run_event_now(self):
        i = self._sel_event()
        if i is not None:
            self.s.events.fire(self.s.settings.events[i], "run now")

    def remove_event(self):
        i = self._sel_event()
        if i is not None and messagebox.askyesno("Events", "Remove this event?"):
            del self.s.settings.events[i]
            self.s.settings.save()
            self.refresh_events()

    # ------------------------------------------------------------------ chat
    def _chat_tab(self, nb):
        return ChatPane(nb, self)

    # ------------------------------------------------------------------ bosses
    def _boss_tab(self, nb):
        f = ttk.Frame(nb, padding=8)
        intro = ttk.Label(f, text="Bosses show up here once you kill them (kills are detected automatically), so "
                                  "you can see when they're due back. Only bosses worth exp or that drop items are "
                                  "listed. Respawn times come from MME.", style="Muted.TLabel", wraplength=440)
        intro.pack(anchor="w", fill="x")
        intro.bind("<Configure>", lambda ev: intro.configure(wraplength=max(200, ev.width - 4)))
        # short lines, each box on its own line under its checkbox: nothing runs off a narrow panel's right side
        c = self._check(f, "stop_before_boss", "Stop before walking into a boss room (Alt+R goes in)")
        c.pack(anchor="w")
        Tip(c, "Only bosses expected to do 40%+ of your HP (Settings: boss_stop_pct). A boss's Stop box below "
               "turns it off for that one.")
        c = self._check(f, "boss_route_round", "Walk round boss rooms when there's a way about as short")
        c.pack(anchor="w")
        Tip(c, "Go to, bank and shop trips and the way back to a loop go round any boss you aren't hunting — even "
               "an easy one — when the way round is at most a quarter longer (or 20 rooms). Going to the boss "
               "itself still goes straight there.")
        c = self._check(f, "boss_hunt_on", "Hunt: go kill a ticked boss when it's due, then carry on")
        c.pack(anchor="w")
        Tip(c, "Leaves the loop or path to kill a boss whose Hunt box is ticked once its respawn time comes, then "
               "goes back to it.")
        hf = ttk.Frame(f)
        hf.pack(anchor="w", padx=(22, 0))
        ttk.Label(hf, text="up to").pack(side="left")
        ttk.Spinbox(hf, from_=5, to=400, width=5, textvariable=self._var("boss_hunt_max_steps")).pack(side="left", padx=4)
        ttk.Label(hf, text="steps away").pack(side="left")
        c = self._check(f, "boss_farm_on", "Also when I'm standing somewhere (boss farm)")
        c.pack(anchor="w")
        Tip(c, "Not looping: still go for a due boss, then come back here.")
        ff = ttk.Frame(f)
        ff.pack(anchor="w", padx=(22, 0))
        ttk.Label(ff, text="after a kill send").pack(side="left")
        ttk.Entry(ff, textvariable=self._var("boss_loot_cmd"), width=12).pack(side="left", padx=4)
        self.boss_next = ttk.Label(f, text="", style="Muted.TLabel")
        self.boss_next.pack(anchor="w")
        cols = ("stop", "hunt", "kills", "status", "next", "regen", "last", "room")
        self.boss_tree = ttk.Treeview(f, columns=cols, show="tree headings", height=12)
        self.boss_tree.heading("#0", text="Boss")
        self.boss_tree.column("#0", width=150)
        self.boss_tree.bind("<Button-1>", self._boss_click, add="+")
        for c, w, t in zip(cols, (40, 40, 44, 160, 110, 50, 150, 70),
                           ("Stop", "Hunt", "Kills", "Status", "Next spawn", "Regen", "Last kill", "Room")):
            self.boss_tree.heading(c, text=t)
            self.boss_tree.column(c, width=w)
        self.boss_tree.tag_configure("dead", foreground="#ff8a8a")
        self.boss_tree.tag_configure("up", foreground="#5cff7a")
        self.boss_tree.tag_configure("unk", foreground=MUTED)
        # the rows under the list go in first, from the bottom up: the list takes what height is left, so a short
        # or narrow window squeezes the list, never the buttons or the Track box
        a = ttk.Frame(f)
        a.pack(side="bottom", fill="x", pady=(8, 0))
        bb = FlowRow(f)
        bb.pack(side="bottom", fill="x", pady=(4, 0))
        for text, cmd, style in (("Killed now", self._boss_killed, None), ("Seen alive", self._boss_alive, None),
                                 ("Go to spawn", self._boss_goto, "Accent.TButton"),
                                 ("Hunt now", self._boss_hunt_now, "Accent.TButton"),
                                 ("Set kill time…", lambda: self._boss_set_time("kill"), None),
                                 ("Set next spawn…", lambda: self._boss_set_time("next"), None),
                                 ("Respawn time…", self._boss_set_respawn, None),
                                 ("Ask the party (@spawn)", self._boss_ask_party, None),
                                 ("Remove", self._boss_forget, None)):
            bb.add(ttk.Button(bb, text=text, command=cmd, **({"style": style} if style else {})))
        self.boss_tree.pack(fill="both", expand=True, pady=6)
        ttk.Label(a, text="Track a boss or any monster:").pack(anchor="w")
        ttk.Button(a, text="Add", command=self._boss_track).pack(side="right")
        self.boss_add = tk.StringVar()
        e = ttk.Entry(a, textvariable=self.boss_add, width=12)
        e.pack(side="left", padx=4, fill="x", expand=True)
        e.bind("<Return>", lambda ev: self._boss_track())
        self.s.bosses.on_change = lambda: self.root.after(0, self.refresh_bosses)
        self.s.on_alert = lambda msg: self.root.after(0, self._alert, msg)
        self.s.on_no_route = lambda msg: self.root.after(0, lambda: messagebox.showinfo(
            "No route", msg.replace(" — blocked by ", "\n\nBlocked by:\n• ").replace("; the ", "\n• the "),
            parent=self.root))
        self.s.on_paths_changed = lambda: self.root.after(0, self._paths_changed)
        self.refresh_bosses()
        return f

    def _alert(self, msg):
        self.root.bell()
        self.add_log("⚑ " + msg)
        if msg.startswith("Hung up") and getattr(self, "_pvp_last", None):
            self._pvp_last.configure(text=f"Last hang-up: {time.strftime('%H:%M:%S')} — {msg[9:]}")
        try:
            self._alert_title = f"{msg} — MudPilot"
            self.root.title(self._alert_title)
            self.root.after(15000, self._clear_alert_title)
        except tk.TclError:
            pass

    def refresh_bosses(self):
        if not hasattr(self, "boss_tree"):
            return
        sel = self.boss_tree.selection()
        from .bosses import fmt_dur as _bfmt
        self.boss_tree.delete(*self.boss_tree.get_children())
        b = self.s.bosses
        rows = []
        for mon in b.tracked():
            text, left = b.status(mon["num"])
            rows.append((left is None, left or 0, mon, text))
        rows.sort(key=lambda r: (r[0], r[1]))
        for _n, left, mon, text in rows:
            r = b.data.get(str(mon["num"]), {})
            last = (time.strftime("%b %d %H:%M", time.localtime(r["last_kill"])) + f" ({_bfmt(time.time() - r['last_kill'])} ago)"
                    if r.get("last_kill") else "—")
            room = r.get("seen_room") or (list(mon["spawn_rooms"][0]) if mon.get("spawn_rooms") else None)
            tag = "dead" if text.startswith("dead") else ("up" if ("up" in text or "alive" in text) else "unk")
            stop = "☐" if mon["name"].lower() in {n.lower() for n in (self.s.settings.boss_no_stop or [])} else "☑"
            hunt = "☑" if r.get("hunt") else "☐"
            regen = b.respawn_secs(mon["num"])
            nxt = (time.strftime("%b %d %I:%M %p", time.localtime(r["dead_since"] + regen))
                   if r.get("dead_since") and regen else "—")
            rg = (f"{regen / 3600:g}h" if regen >= 3600 else f"{regen / 60:g}m") if regen else "—"
            self.boss_tree.insert("", "end", iid=str(mon["num"]), text=mon["name"],
                                  values=(stop, hunt, len(r.get("kills") or []), text, nxt, rg, last,
                                          f"{room[0]}/{room[1]}" if room else "—"), tags=(tag,))
        if sel and self.boss_tree.exists(sel[0]):
            self.boss_tree.selection_set(sel)
        try:
            nd = self.s.bosshunt.next_due()
            if nd:
                name, left = nd
                self.boss_next.configure(text=f"Next ticked boss: {name} — " + (
                    f"due in {_bfmt(left)}" if left > 0 else f"due now ({_bfmt(-left)} ago)"))
            else:
                self.boss_next.configure(text="Tick Hunt on a boss to have MudPilot go kill it when it's back up.")
        except Exception:
            pass

    def _boss_click(self, e):
        """Tick/untick 'Stop' — unticked bosses are walked in on and fought (small ones you can AFK)."""
        t = self.boss_tree
        col = t.column(t.identify_column(e.x), "id") if t.identify_region(e.x, e.y) == "cell" else None
        if col not in ("stop", "hunt"):
            return None
        iid = t.identify_row(e.y)
        mon = self.s.world.monsters.get(int(iid)) if iid and iid.isdigit() else None
        if not mon:
            return None
        if col == "hunt":
            r = self.s.bosses.rec(mon)
            r["hunt"] = not r.get("hunt")
            self.s.bosses.save()
            self.s.log(f"Boss hunt: {mon['name']} {'on' if r['hunt'] else 'off'}")
            self.refresh_bosses()
            return "break"
        cfg = self.s.settings
        lst = [n for n in (cfg.boss_no_stop or []) if n.lower() != mon["name"].lower()]
        if len(lst) == len(cfg.boss_no_stop or []):
            lst.append(mon["name"])
        cfg.boss_no_stop = lst
        cfg.save()
        self.refresh_bosses()
        return "break"

    def _sel_boss(self):
        sel = self.boss_tree.selection()
        return self.s.world.monsters.get(int(sel[0])) if sel else None

    def _boss_killed(self):
        m = self._sel_boss()
        if m:
            self.s.bosses.record_kill(m, by="marked")

    def _boss_alive(self):
        m = self._sel_boss()
        if m:
            self.s.bosses.mark_alive(m)

    def _boss_forget(self):
        m = self._sel_boss()
        if m:
            self.s.bosses.forget(m["num"])

    def _boss_goto(self):
        m = self._sel_boss()
        if not m or not m.get("spawn_rooms"):
            return
        here = self.s.state.room
        rooms = m["spawn_rooms"]
        target = rooms[0]
        if here and len(rooms) > 1:
            best = None
            for rm in rooms:
                rt = self.s.world.route(here, tuple(rm), level=self.s.state.level or None)
                if rt is not None and (best is None or len(rt) < best[0]):
                    best = (len(rt), tuple(rm))
            target = best[1] if best else target
        self.goto_room(tuple(target))

    def _boss_track(self):
        q = self.boss_add.get().strip().lower()
        if not q:
            return
        hits = [m for m in self.s.world.monsters.values()
                if m.get("boss") and q in m["name"].lower() and self.s.bosses.killable(m)]
        if not hits:
            # pMUD: any monster can have a timer — exact name first, else everything that matches
            mons = [m for m in self.s.world.monsters.values() if m.get("in_game") and self.s.bosses.killable(m)]
            hits = [m for m in mons if m["name"].lower() == q] or [m for m in mons if q in m["name"].lower()]
            if not hits:
                messagebox.showinfo("MudPilot", f"No monster in MME matching '{q}'.")
                return
            # same name, one with a respawn time (the 300k crimson mist, 7 h) and one without (an 11k crimson
            # mist): the one with the timer — not a second row asking for minutes MME already has
            timed = {m["name"].lower() for m in hits if m.get("regen_h")}
            hits = [m for m in hits if m.get("regen_h") or m["name"].lower() not in timed]
            names = {m["name"] for m in hits}
            if len(names) > 3:
                messagebox.showinfo("MudPilot", f"{len(names)} monsters match '{q}' — type more of the name.")
                return
        from tkinter import simpledialog
        for m in hits[:10]:
            mins = None
            if not m.get("regen_h") and not (self.s.bosses.data.get(str(m["num"])) or {}).get("respawn_min"):
                mins = simpledialog.askfloat("Respawn time", f"How many minutes does {m['name']} take to come back?\n"
                                             "(MME doesn't say — leave empty to just count kills)",
                                             parent=self.root, minvalue=0.5, maxvalue=100000)
            self.s.bosses.track(m, respawn_min=mins)
        self.boss_add.set("")
        self.refresh_bosses()

    def _boss_hunt_now(self):
        """Go for the picked boss now, every lair it can be in — no waiting for its clock."""
        m = self._sel_boss()
        if not m:
            messagebox.showinfo("MudPilot", "Pick a monster in the list first.")
            return
        self.plan_route(lambda a: self.s.log(self.s.bosshunt.hunt_now(m)) or True, f"to {m['name']}")

    def _boss_set_time(self, which):
        """Set a kill you missed (someone else got it), or when it's next due."""
        from tkinter import simpledialog
        from .bosses import _parse_hm
        m = self._sel_boss()
        if not m:
            messagebox.showinfo("MudPilot", "Pick a monster in the list first.")
            return
        q = ("How long ago was it killed? (e.g. 2h 15m, 40m, now)" if which == "kill"
             else "How long until it's back? (e.g. 1h 30m, 20m)")
        ans = simpledialog.askstring(m["name"], q, parent=self.root)
        if not ans:
            return
        secs = _parse_hm(ans)
        if secs is None:
            messagebox.showinfo("MudPilot", f"Couldn't read '{ans}' — try something like 2h 15m.")
            return
        if which == "kill":
            self.s.bosses.set_kill_time(m, time.time() - secs)
        elif not self.s.bosses.set_next_spawn(m, time.time() + secs):
            messagebox.showinfo("MudPilot", f"Set {m['name']}'s respawn time first (Respawn time…).")
        self.refresh_bosses()

    def _boss_set_respawn(self):
        from tkinter import simpledialog
        m = self._sel_boss()
        if not m:
            return
        cur = self.s.bosses.respawn_secs(m["num"]) / 60
        mins = simpledialog.askfloat("Respawn time", f"{m['name']} comes back after how many minutes?"
                                     + (f"\n(now {cur:g} min)" if cur else ""), parent=self.root,
                                     minvalue=0.5, maxvalue=100000)
        if mins:
            self.s.bosses.track(m, respawn_min=mins)
            self.refresh_bosses()

    def _boss_ask_party(self):
        """pMUD's shared timers: ask the party's bots; their answers fill in the times."""
        m = self._sel_boss()
        if not m or not self.s.telnet.connected:
            return
        me = (self.s.settings.my_name or "").lower()
        names = [n for n in self.s.state.party if n.lower() != me]
        for n in names[:6]:
            self.s.send(f"/{n} @spawn {m['name']}", from_bot=True)
        self.add_log(f"Asked {', '.join(names) or 'nobody (not in a party)'} about {m['name']}")

    # ------------------------------------------------------------------ remote
    def _remote_tab(self, nb):
        from .remote import CATEGORIES
        f = ttk.Frame(nb, padding=8)
        top = ttk.Frame(f)
        top.pack(fill="x")
        self._check(top, "remote_enabled", "Allow remote @commands").pack(side="left")
        self._check(top, "remote_warn_denied", "Reply when refused").pack(side="left", padx=10)
        self._check(top, "eightball_on", "Magic 8-Ball: answer \"(8) question\" on gossip").pack(side="left", padx=10)
        ch = ttk.Frame(f)
        ch.pack(fill="x", pady=4)
        ttk.Label(ch, text="Listen on:").pack(side="left")
        self.rc_vars = {}
        for c in ("telepath", "say", "gangpath", "broadcast"):
            v = tk.BooleanVar(value=self.s.settings.remote_channels.get(c, False))
            v.trace_add("write", lambda *a, c=c, v=v: self._rc_set(c, v))
            self.rc_vars[c] = v
            ttk.Checkbutton(ch, text=c.title(), variable=v).pack(side="left", padx=4)
        ttk.Label(f, text="Nobody can control you unless they're listed here. Party members can always use "
                          "@wait / @ok / @comeback. Commands containing 'suicide' or 'reroll' are always ignored.",
                  style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(2, 6))
        cols = tuple(CATEGORIES)
        self.rp_tree = ttk.Treeview(f, columns=cols, show="tree headings", height=8)
        self.rp_tree.heading("#0", text="Player")
        self.rp_tree.column("#0", width=100)
        short = {"query": "Status", "location": "Where", "inventory": "Inv", "invite": "Invite", "move": "Move",
                 "execute": "@do", "settings": "Settings", "hangup": "Hangup", "divert": "Divert"}
        for c in cols:
            self.rp_tree.heading(c, text=short[c])
            self.rp_tree.column(c, width=48, anchor="center")
        self.rp_tree.pack(fill="both", expand=True)
        self.rp_tree.bind("<ButtonRelease-1>", self._rp_click)
        ttk.Label(f, text="Click a cell to allow/deny.", style="Muted.TLabel").pack(anchor="w")
        a = ttk.Frame(f)
        a.pack(fill="x", pady=6)
        self.rp_name = tk.StringVar()
        ttk.Entry(a, textvariable=self.rp_name, width=16).pack(side="left")
        ttk.Button(a, text="Add player", command=lambda: self._rp_add("query")).pack(side="left", padx=4)
        ttk.Button(a, text="Add as trusted (all)", command=lambda: self._rp_add("all")).pack(side="left")
        ttk.Button(a, text="Remove", command=self._rp_remove).pack(side="right")
        self._row_divert = ttk.Label(f, text="", style="Muted.TLabel")
        self._row_divert.pack(anchor="w")
        ob = ttk.LabelFrame(f, text="Options", padding=6)
        ob.pack(fill="x", pady=(4, 0))
        for i, (k, t) in enumerate((("log_chat", "Log conversations (data\\chat)"), ("greet_players", "Greet players when first met"),
                                    ("learn_players", "Look at players (learn their gear, once a day)"),
                                    ("disallow_remote", "Disallow all remote control commands"),
                                    ("disallow_gangpath_remote", "Disallow remote control from gangpaths"))):
            self._check(ob, k, t).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        rowx = ttk.Frame(ob)
        rowx.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(rowx, text="Greeting").pack(side="left")
        ttk.Entry(rowx, textvariable=self._var("greet_cmd"), width=14).pack(side="left", padx=4)
        ttk.Label(rowx, text="Keep last").pack(side="left", padx=(10, 0))
        ttk.Spinbox(rowx, from_=50, to=5000, width=6, textvariable=self._var("chat_keep_lines")).pack(side="left", padx=4)
        ttk.Label(rowx, text="conversation lines").pack(side="left")
        afk = ttk.LabelFrame(f, text="AFK mode", padding=6)
        afk.pack(fill="x", pady=(6, 0))
        r1 = ttk.Frame(afk)
        r1.pack(fill="x")
        ttk.Label(r1, text="Auto-AFK after").pack(side="left")
        ttk.Spinbox(r1, from_=0, to=240, width=5, textvariable=self._var("auto_afk_mins")).pack(side="left", padx=4)
        ttk.Label(r1, text="minutes idle (0 = never)").pack(side="left")
        self._check(r1, "afk_when_minimized", "Auto-AFK when minimized").pack(side="left", padx=10)
        self._check(r1, "input_cancels_afk", "Typing cancels AFK").pack(side="left")
        r2 = ttk.Frame(afk)
        r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="AFK reply").pack(side="left")
        ttk.Entry(r2, textvariable=self._var("afk_message"), width=16).pack(side="left", padx=4)
        ttk.Label(r2, text="Refused-command reply").pack(side="left", padx=(10, 0))
        ttk.Entry(r2, textvariable=self._var("remote_fail_msg"), width=30).pack(side="left", padx=4)
        self.refresh_remote()
        return f

    def _rc_set(self, c, v):
        self.s.settings.remote_channels[c] = bool(v.get())
        self.s.settings.save()

    def refresh_remote(self):
        from .remote import CATEGORIES
        if not hasattr(self, "rp_tree"):
            return
        self.rp_tree.delete(*self.rp_tree.get_children())
        for name, perms in sorted((self.s.settings.remote_players or {}).items()):
            self.rp_tree.insert("", "end", iid=name, text=name,
                                values=tuple("✓" if c in perms else "·" for c in CATEGORIES))
        d = self.s.settings.divert_to
        self._row_divert.configure(text=f"Diverting telepaths to {d}" if d else "")

    def _rp_click(self, e):
        from .remote import CATEGORIES
        row, col = self.rp_tree.identify_row(e.y), self.rp_tree.identify_column(e.x)
        if not row or col in ("#0", ""):
            return
        cat = list(CATEGORIES)[int(col[1:]) - 1]
        perms = self.s.settings.remote_players.setdefault(row, [])
        if cat in perms:
            perms.remove(cat)
        else:
            if cat in ("execute", "hangup") and not messagebox.askyesno(
                    "Remote control", f"Let {row} {'run any command as you (@do)' if cat == 'execute' else 'disconnect you'}?"):
                return
            perms.append(cat)
        self.s.settings.save()
        self.refresh_remote()

    def _rp_add(self, level):
        from .remote import CATEGORIES
        name = self.rp_name.get().strip().split(" ")[0]
        if not name:
            return
        name = name[:1].upper() + name[1:]
        if level == "all":
            if not messagebox.askyesno("Remote control", f"Give {name} full control, including @do (run any "
                                                         "command as you) and @hangup?"):
                return
            perms = list(CATEGORIES)
        else:
            perms = ["query", "location"]
        self.s.settings.remote_players[name] = perms
        self.s.settings.save()
        self.rp_name.set("")
        self.refresh_remote()

    def _rp_remove(self):
        sel = self.rp_tree.selection()
        if sel:
            self.s.settings.remote_players.pop(sel[0], None)
            self.s.settings.save()
            self.refresh_remote()

    def check_buffs_now(self):
        self.s.bot._abil_checked_at = 0
        self.s.bot._rule_checked.clear()

    def _stats_tab(self, nb):
        return StatsPane(nb, self)

    # ------------------------------------------------------------------ terminal
    def _insert_segs(self, segs, index="end"):
        for t, st in segs:
            self.term.insert(index, t, (st.tag,))

    @staticmethod
    def _collapse_prompts(segs):
        """'[HP=514]: (Resting) [HP=512]: (Resting) [HP=517]: (Resting) Revolution casts mend…' →
        keep only the newest prompt, so the text always starts in the same place (like MegaMUD)."""
        from .gamestate import PROMPT_RE
        text = "".join(t for t, _st in segs)
        pos, cut, n = 0, 0, 0
        while True:
            m = PROMPT_RE.match(text, pos)
            if not m:
                break
            n += 1
            cut = m.start()
            pos = m.end()
            while pos < len(text) and text[pos] == " ":
                pos += 1
        if n < 2:
            return segs
        out, skip = [], cut
        for t, st in segs:
            if skip >= len(t):
                skip -= len(t)
                continue
            out.append((t[skip:], st))
            skip = 0
        return out

    REFLOW_START = ("You are carrying", "You have the following keys", "You notice", "Also here:")

    def _reflow(self, segs) -> bool:
        """The board breaks long lists at 80 columns. Join those pieces back into one line and let the
        window wrap it at its own width — inventory and room lists read evenly instead of ragged."""
        from .gamestate import PROMPT_RE
        text = "".join(t for t, _st in segs)
        open_ = getattr(self, "_reflow_open", False)
        if PROMPT_RE.search(text) or not text.strip() or text.startswith(("Wealth:", "Encumbrance:", "Obvious exit")):
            self._reflow_open = False
            return False
        if text.startswith(self.REFLOW_START):
            self._reflow_open = not text.rstrip().endswith(".")
            return False
        if open_:
            self._reflow_open = not text.rstrip().endswith(".")
            return True
        return False

    def add_line(self, segs):
        segs = self._collapse_prompts(segs)
        follow = self._following()
        self.term.configure(state="normal")
        self.term.delete("partial", "end-1c")
        if self._reflow(segs) and self.term.get("end-2c", "end-1c") == "\n":
            self.term.delete("end-2c", "end-1c")      # continue the previous line
            prev = self.term.get("end-2c", "end-1c")
            if prev not in (" ", "-"):
                self.term.insert("end-1c", " ")
        self._insert_segs(segs, "end-1c")
        self.term.insert("end-1c", "\n")
        self.term.mark_set("partial", "end-1c")
        lines = int(self.term.index("end-1c").split(".")[0])
        keep = max(int(self.s.settings.scrollback_lines or 5000), 500)
        # while you're scrolled back, don't trim under you (up to 3× the back-scroll), so the view stays put
        if lines > keep + keep // 5 and (follow or lines > keep * 3):
            self.term.delete("1.0", f"{lines - keep}.0")
        self.term.configure(state="disabled")
        self._autoscroll(follow, new=1)

    def add_banner(self, text, kind="down"):
        """A big coloured line on the MUD screen: connected / disconnected / hung up."""
        self.term.configure(state="normal")
        self.term.delete("partial", "end-1c")
        tag = "banner_down" if kind == "down" else "banner_up"
        self.term.tag_configure("banner_down", foreground="#ffffff", background="#a01818",
                                font=(self.s.settings.term_font, int(self.s.settings.term_font_size) + 2, "bold"))
        self.term.tag_configure("banner_up", foreground="#0b0d10", background="#2fbf71",
                                font=(self.s.settings.term_font, int(self.s.settings.term_font_size), "bold"))
        self.term.insert("end-1c", "\n" + text + "\n", (tag,))
        self.term.mark_set("partial", "end-1c")
        self.term.configure(state="disabled")
        self.term.see("end")

    def set_partial(self, segs):
        segs = self._collapse_prompts(segs)
        follow = self._following()
        self.term.configure(state="normal")
        self.term.delete("partial", "end-1c")
        for t, st in segs:
            self.term.insert("end-1c", t, (st.tag,))
        self.term.configure(state="disabled")
        self._autoscroll(follow)

    def echo_sent(self, cmd, from_bot):
        if getattr(self.s, "server_echoes", False) and cmd:
            if not from_bot:
                self.scroll_bottom()          # typing still takes you back down
            return                            # the board shows it already
        follow = self._following() or not from_bot     # typing a command takes you back down
        self.term.configure(state="normal")
        self.term.insert("end-1c", (cmd or "⏎") + "\n", ("botsent" if from_bot else "sent",))
        self.term.mark_set("partial", "end-1c")
        self.term.configure(state="disabled")
        self._autoscroll(follow, new=1)

    # ---------------------------------------------------------------- back-scroll
    def _following(self) -> bool:
        """True when the MUD screen is showing the newest line (not scrolled back). A follow already queued
        counts: the lines in between haven't been scrolled to yet, but the screen is following."""
        if getattr(self, "_see_pending", False):
            return True
        at_end = self.term.yview()[1] >= 0.9995
        if time.time() - getattr(self, "_user_scroll_at", 0) < 2:
            # 0.8.226 (Dan: "his backscroll was fighting me"): you just scrolled, and Tk tells us only when it's idle —
            # a line before that found _scrolled_back still False, queued a follow and snapped you back down
            return at_end
        return at_end or not getattr(self, "_scrolled_back", False)

    def _autoscroll(self, follow=True, new=0):
        if follow:
            # one scroll per batch of lines, not one per line (bug hunt #26): queue it for when Tk is idle
            if not getattr(self, "_see_pending", False):
                self._see_pending = True
                try:
                    self.root.after_idle(self._see_end)
                except Exception:
                    self._see_end()
            if getattr(self, "_scrolled_back", False):
                self._scroll_done()
            return
        self._backlog = getattr(self, "_backlog", 0) + new
        self._scroll_show()

    def _see_end(self):
        if not getattr(self, "_see_pending", False):
            return                       # you scrolled in the meantime: stay where you are
        self._see_pending = False
        try:
            self.term.see("end")
        except tk.TclError:
            pass

    def _see_cancel(self):
        self._see_pending = False
        self._user_scroll_at = time.time()

    def _on_term_scroll(self, first, last):
        self._term_sb.set(first, last)
        back = float(last) < 0.9995
        if back and getattr(self, "_see_pending", False):
            return                       # new lines below a queued follow — not a back-scroll (no banner flicker)
        if back != getattr(self, "_scrolled_back", False):
            self._scrolled_back = back
            if back:
                self._backlog = 0
                self._scroll_show()
            else:
                self._scroll_done()

    def _scroll_show(self):
        lab = getattr(self, "_scroll_lab", None)
        if lab is None:
            lab = self._scroll_lab = tk.Label(self.term, cursor="hand2", font=("Segoe UI", 9, "bold"),
                                              background="#b8860b", foreground="#0b0d10", padx=10, pady=3)
            lab.bind("<Button-1>", lambda e: self._bar_click())
        n = getattr(self, "_backlog", 0)
        lab.configure(text=f"▼ Back-scroll — {n} new line{'s' if n != 1 else ''} below · click, Ctrl+End or Enter to jump down"
                      if n else "▼ Back-scroll — the bot keeps running · click or Ctrl+End to jump down")
        lab.place(relx=0.5, rely=1.0, anchor="s", y=-4)

    def _scroll_done(self):
        self._scrolled_back, self._backlog = False, 0
        if getattr(self, "_scroll_lab", None) is not None:
            self._scroll_lab.place_forget()

    def scroll_bottom(self, e=None):
        self._see_pending = False
        self._user_scroll_at = 0
        self.term.see("end")
        self._scroll_done()
        return "break"

    def _bar_click(self):
        """The back-scroll bar: down to the newest line, and the command line gets the keys (0.8.226, Dan)."""
        self.scroll_bottom()
        try:
            self.entry.focus_set()
        except Exception:
            pass

    def scroll_page(self, d):
        self._see_cancel()
        self.term.yview_scroll(d, "pages")
        return "break"

    def open_backscroll(self, e=None):
        """Everything still in the MUD screen's back-scroll, in its own window, with Find."""
        d = tk.Toplevel(self.root)
        d.title("Back-scroll - MudPilot")
        d.geometry("980x640")
        bar = ttk.Frame(d, padding=6)
        bar.pack(fill="x")
        q = tk.StringVar()
        ttk.Label(bar, text="Find").pack(side="left")
        ent = ttk.Entry(bar, textvariable=q, width=30)
        ent.pack(side="left", padx=4)
        info = ttk.Label(bar, text="", style="Muted.TLabel")
        stf = self.s.settings
        txt = tk.Text(d, background=BG, foreground=FG[None][0], wrap="char", borderwidth=0, padx=6, pady=4,
                      font=(stf.term_font or "Consolas", int(stf.term_font_size or 10)))
        sb = ttk.Scrollbar(d, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        for tag in self.term.tag_names():
            try:
                txt.tag_configure(tag, foreground=self.term.tag_cget(tag, "foreground"),
                                  background=self.term.tag_cget(tag, "background"))
            except tk.TclError:
                pass
        for key, val, idx in self.term.dump("1.0", "end-1c", text=True, tag=True):
            if key == "tagon":
                txt.mark_set(f"on_{val}", "end-1c")
                txt.mark_gravity(f"on_{val}", "left")
            elif key == "tagoff":
                try:
                    txt.tag_add(val, f"on_{val}", "end-1c")
                except tk.TclError:
                    pass
            elif key == "text":
                txt.insert("end-1c", val)
        txt.tag_configure("hit", background="#e6b450", foreground="#0b0d10")
        txt.configure(state="disabled")
        txt.see("end")
        st = {"at": "end"}

        def find(back=True):
            txt.tag_remove("hit", "1.0", "end")
            k = q.get()
            if not k:
                return
            pos = txt.search(k, st["at"], "1.0" if back else "end", backwards=back, nocase=True)
            if not pos:
                pos = txt.search(k, "end" if back else "1.0", backwards=back, nocase=True)
            if not pos:
                info.configure(text="not found")
                return
            end = f"{pos}+{len(k)}c"
            txt.tag_add("hit", pos, end)
            txt.see(pos)
            st["at"] = pos if back else end
            info.configure(text=f"line {pos.split('.')[0]}")
        ent.bind("<Return>", lambda e: find(True))
        ent.bind("<Shift-Return>", lambda e: find(False))
        ttk.Button(bar, text="▲ Older", command=lambda: find(True)).pack(side="left")
        ttk.Button(bar, text="▼ Newer", command=lambda: find(False)).pack(side="left", padx=4)
        info.pack(side="left", padx=8)
        ttk.Label(bar, text=f"keeps the last {int(stf.scrollback_lines or 5000):,} lines (Settings → Other → Back-scroll)",
                  style="Muted.TLabel").pack(side="right")
        ent.focus_set()

    def add_log(self, msg):
        at_bottom = getattr(self, "_log_follow", True)     # only your scrolling changes it (yview lags a redraw)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n", ("chatkw",) if "★ Chat keyword" in msg else ())
        if at_bottom:
            self.logbox.see("end")
        self.logbox.configure(state="disabled")
        if not at_bottom:
            self._log_new += 1
            self.log_jump.configure(text=f"▼ {self._log_new} new line{'s' if self._log_new != 1 else ''} below — "
                                         "click to jump to the bottom")
            if not self.log_jump.winfo_ismapped():
                self.log_jump.pack(side="bottom", fill="x", before=self.logbox)

    def _log_bottom(self):
        self.logbox.see("end")
        self._log_follow, self._log_new = True, 0
        if self.log_jump.winfo_ismapped():
            self.log_jump.pack_forget()

    def _log_at_bottom_check(self):
        self._log_follow = self.logbox.yview()[1] >= 0.999
        if self._log_follow:
            self._log_new = 0
            if self.log_jump.winfo_ismapped():
                self.log_jump.pack_forget()

    def _afk_tick(self):
        st = self.s.settings
        now = time.time()
        last = getattr(self, "_last_input", None) or now
        self._last_input = last
        try:
            minimized = self.root.state() == "iconic"
        except tk.TclError:
            minimized = False
        if not st.afk and ((st.auto_afk_mins and now - last > float(st.auto_afk_mins) * 60)
                           or (st.afk_when_minimized and minimized)):
            self._var("afk").set(True)
            self._auto_afk = True
            self.add_log("Away from keyboard (auto)")

    def _term_menu(self, e):
        """Right-click on the game screen: copy, go to a room the line names, never attack a monster it names."""
        idx = self.term.index(f"@{e.x},{e.y}")
        line = self.term.get(f"{idx} linestart", f"{idx} lineend").strip()
        try:
            sel = self.term.get("sel.first", "sel.last")
        except tk.TclError:
            sel = ""
        m = tk.Menu(self.root, tearoff=0)
        if sel:
            m.add_command(label="Copy", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append(sel)))
        m.add_command(label="Copy this line", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append(line)))
        mr = re.search(r"\b(\d{1,2})\s*[/,]\s*(\d{1,5})\b", sel or line)
        if mr and (int(mr.group(1)), int(mr.group(2))) in self.s.world.rooms:
            k = (int(mr.group(1)), int(mr.group(2)))
            r = self.s.world.room(k)
            m.add_command(label=f"Go to {k[0]}/{k[1]} {r.name if r else ''}", command=lambda: self.goto_room(k))
        mons = []
        for sh, rec in (self.s.state.view.monsters if self.s.state.view else []):
            nm = (rec or {}).get("name") or sh
            if nm and nm.lower() in (sel or line).lower() and nm not in mons:
                mons.append(nm)
        for nm in mons[:3]:
            m.add_command(label=f"Never attack {nm}", command=lambda nm=nm: self._never_attack(nm))
            m.add_command(label=f"Hang up whenever {nm} shows up", command=lambda nm=nm: self._hang_on_monster(nm))
        here = self.s.state.room
        if here:
            key = f"{here[0]}/{here[1]}"
            safe = key in (self.s.settings.safe_rooms or [])
            m.add_command(label=("This room isn't safe any more" if safe else "Safe room: never start a fight here"),
                          command=lambda: self._toggle_safe(key))
        pl = self.s.players
        me = (self.s.settings.my_name or "").lower()
        names = []
        for w_ in re.findall(r"\b([A-Z][a-z]{2,})\b", sel or line):
            if w_.lower() != me and w_.lower() in pl.data and w_ not in names:
                names.append(w_)
        for nm in names[:3]:
            if pl.relationship(nm) == "Enemy":
                m.add_command(label=f"{nm}: not an enemy any more", command=lambda nm=nm: self._mark(nm, "Unknown"))
            else:
                m.add_command(label=f"{nm}: Enemy (hang up when they show up)", command=lambda nm=nm: self._mark(nm, "Enemy"))
            if pl.relationship(nm) != "Friend":
                m.add_command(label=f"{nm}: Friend (never a PvP target)", command=lambda nm=nm: self._mark(nm, "Friend"))
        # items lying here that the line names: always pick them up (Settings → Loot → Grab these) — Evolution,
        # 2026-11-01: "add option to set items to auto-collect"
        st_ = self.s.settings
        grab = [x.strip().lower() for x in (st_.loot_items or []) if x.strip()]
        for _q, it in (self.s.state.view.items if self.s.state.view else [])[:40]:
            if it and it.lower() in (sel or line).lower() and not re.search(r"\b(copper|silver|gold|platinum|runic)\b", it.lower()):
                if it.lower() in grab:
                    m.add_command(label=f"Stop picking up {it}", command=lambda it=it: self._auto_collect(it, False))
                else:
                    m.add_command(label=f"Always pick up {it}", command=lambda it=it: self._auto_collect(it, True))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _auto_collect(self, item, on):
        st = self.s.settings
        cur = [x for x in (st.loot_items or []) if x.strip() and x.strip().lower() != item.lower()]
        st.loot_items = cur + ([item] if on else [])
        if on:
            st.auto_loot = True
        st.save()
        self.add_log(f"{'Always picking up' if on else 'Not picking up'} {item} (Settings → Loot → Grab these)")

    def _mark(self, nm, rel):
        pl = self.s.players
        p = pl.get(nm) if hasattr(pl, "get") else None
        if p is None:
            pl.data.setdefault(nm.lower(), {"name": nm})
            p = pl.data[nm.lower()]
        p["relationship"] = rel
        try:
            pl.save()
        except Exception:
            pass
        self.add_log(f"{nm} marked {rel}" + (" — MudPilot hangs up when they show up" if rel == "Enemy" else ""))

    def _hang_on_monster(self, nm):
        cfg = self.s.settings
        if nm.lower() not in [x.lower() for x in cfg.hangup_monsters or []]:
            cfg.hangup_monsters = list(cfg.hangup_monsters or []) + [nm]
            cfg.save()
        self.add_log(f"MudPilot hangs up whenever {nm} shows up (PvP tab → Hang up on monsters)")

    def _toggle_safe(self, key):
        cfg = self.s.settings
        rooms = list(cfg.safe_rooms or [])
        if key in rooms:
            rooms.remove(key)
            self.add_log(f"{key} isn't a safe room any more")
        else:
            rooms.append(key)
            self.add_log(f"{key} is a safe room — MudPilot won't start fights here (it still fights back)")
        cfg.safe_rooms = rooms
        cfg.save()

    def _never_attack(self, nm):
        cfg = self.s.settings
        if nm.lower() not in [x.lower() for x in cfg.ignore_mobs or []]:
            cfg.ignore_mobs = list(cfg.ignore_mobs or []) + [nm]
            cfg.save()
            self.add_log(f"Won't attack {nm} any more (Combat tab → Never attack)")

    PASTE_CHANNELS = (("Say (room)", "."), ("Gossip", "gos "), ("Gangpath", "bg "), ("Broadcast", "br "),
                      ("Commands (as typed)", ""))

    def _paste_lines(self, e=None):
        """pMUD's paste box: pasting several lines asks where they go, then sends one line at a time,
        split at the game's 127-character limit with the channel on every piece."""
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return None
        lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
        if len(lines) < 2:
            return None                              # one line: the normal paste
        d = tk.Toplevel(self.root)
        d.title("Paste - MudPilot")
        d.configure(background=PANEL)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Send these {len(lines)} lines as…", style="Head.TLabel").pack(anchor="w")
        pv = tk.Text(fr, width=70, height=min(10, len(lines) + 1), background="#0e1319", foreground=TEXT)
        pv.insert("1.0", "\n".join(lines))
        pv.pack(fill="both", expand=True, pady=6)
        ch = tk.StringVar(value=self.PASTE_CHANNELS[0][1])
        for label, pre in self.PASTE_CHANNELS:
            ttk.Radiobutton(fr, text=label, value=pre, variable=ch).pack(anchor="w")

        def go():
            pre = ch.get()
            body = [ln for ln in pv.get("1.0", "end").splitlines() if ln.strip()]
            out = []
            room = 127 - len(pre)
            for ln in body:
                while len(ln) > room:
                    cut = ln.rfind(" ", 0, room)
                    cut = cut if cut > room // 2 else room
                    out.append(pre + ln[:cut].rstrip())
                    ln = ln[cut:].lstrip()
                out.append(pre + ln)
            d.destroy()
            for i, c in enumerate(out):
                self.root.after(600 * i, lambda c=c: self.s.send(c))
        ttk.Button(fr, text="Send", style="Accent.TButton", command=go).pack(anchor="e", pady=(8, 0))
        return "break"

    def on_enter(self, e=None):
        self._last_input = time.time()
        if self.s.settings.afk and self.s.settings.input_cancels_afk:
            self._var("afk").set(False)
            self.add_log("Back at the keyboard")
        cmd = self.entry.get()
        self.entry.delete(0, "end")
        if cmd:
            self.history.append(cmd)
            self.history = self.history[-200:]
        self.hist_i = len(self.history)
        if not self.s.telnet.connected:
            self.add_log("Not connected.")
            return
        for c in split_commands(cmd, self.s.settings.command_splitter):
            self.send_typed(c)

    def send_typed(self, cmd):
        """A command YOU typed (or a macro key sent): aliases expand here (Game Data → Aliases), and only here —
        remote commands from other players go straight to s.send() and never expand."""
        from .aliases import expand
        st = self.s.settings
        for c in expand(cmd, getattr(st, "aliases", None), st.command_splitter or ";"):
            self.s.send(c)

    def _stray_key(self, e):
        """A key pressed on the MUD screen, map or anywhere that isn't a text box goes into the
        command line instead. Nothing is ever sent half-typed, and nothing stops the bot or the
        game output — a cat on the keyboard just fills the command line."""
        w = e.widget
        try:
            if w.winfo_toplevel() is not self.root:
                return None
        except (tk.TclError, AttributeError):
            return None
        if w is self.entry or isinstance(w, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return None
        if isinstance(w, tk.Text) and str(w.cget("state")) == "normal":
            return None
        if e.state & 0x4 or e.state & 0x40000 and e.keysym in ("Up", "Down", "Left", "Right"):   # (0x40000: Tk's "extended key" on Windows — the arrow keys, not the number pad)
            return None             # Ctrl+C to copy from the MUD screen etc.
        if e.keysym in ("Return", "KP_Enter"):
            self.entry.focus_set()
            if self.entry.get():
                self.on_enter()
            return "break"
        if e.keysym == "BackSpace":
            self.entry.focus_set()
            self.entry.delete(len(self.entry.get()) - 1, "end") if self.entry.get() else None
            return "break"
        ch = e.char if (e.char and len(e.char) == 1 and e.char.isprintable()) else \
            (e.keysym if len(e.keysym) == 1 else " " if e.keysym == "space" else "")
        if ch:
            self.entry.focus_set()
            self.entry.insert("end", ch)
            self.entry.icursor("end")
            return "break"
        return None

    def _macro_key(self, e):
        """F-keys and the number pad run macros (Options → Game Data → Macros). The number pad walks from any
        MudPilot window — the Map window too, so you can walk a loop while recording it there (Dan, 2026-11-01) —
        except while you're typing in a box."""
        import sys
        from .macros import key_name, split
        win = sys.platform.startswith("win")
        name = key_name(e.keysym, e.keycode, e.state, win, extended=bool(e.state & 0x40000) if win else True)
        if not name:
            return None
        try:
            if e.widget.winfo_toplevel() is not self.root:
                typing = isinstance(e.widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox))
                if not name.startswith("Keypad") or typing:
                    return None
        except (tk.TclError, AttributeError):
            return None
        if name.startswith("Keypad") and (not self.s.settings.keypad_macros or
                                          (e.widget is self.entry and self.entry.get())):
            return None
        text = self.s.macros.get(name)
        if text is None:
            return None
        if name.startswith("Keypad"):
            # one move per press, as MegaMUD does: a held key's auto-repeat (Windows sends KeyPress over and over)
            # sent 30 'w's while the game sat a round on 'dig treasure', then walked into a wall 19 times
            import time as _t
            held = self.__dict__.setdefault("_held_keys", {})
            now = _t.time()
            if now - held.get(e.keycode, 0) < 5:
                held[e.keycode] = now
                return "break"
            held[e.keycode] = now
        self.run_macro(text)
        return "break"

    def _key_up(self, e):
        getattr(self, "_held_keys", {}).pop(e.keycode, None)

    def run_macro(self, text):
        from .macros import split
        sends, rest = split(text)
        if sends and not self.s.telnet.connected:
            self.add_log("Not connected.")
        for cmd in sends:
            self.send_typed(cmd)                 # (a macro key can send an alias: "bs^M")
        if rest:
            self.entry.delete(0, "end")
            self.entry.insert(0, rest)
            self.entry.icursor("end")
            self.entry.focus_set()

    def hangup_now(self):
        """Alt+H — hang up immediately. No prompt."""
        self.s.hangup_now()
        self._alert("Hung up (Alt+H)")

    def switch_config(self, slot):
        st = self.s.settings
        if st.switch_config(slot):
            self._sync_vars()
            self.refresh_buffs()
            st.save()
            self.add_log(f"Switched to {st.config_name(slot)}")
        self.config_var.set(st.active_config)
        self._refresh_config_title()

    def rename_config(self):
        st = self.s.settings
        name = simpledialog.askstring("Rename config profile", f"Name for config profile {st.active_config}:",
                                      initialvalue=st.config_name(st.active_config), parent=self.root)
        if name and name.strip():
            st.rename_config(st.active_config, name)
            st.save()
            self._refresh_config_title()

    def _refresh_config_title(self):
        st = self.s.settings
        for slot, idx in zip("1234", self._config_idx):
            self.config_menu.entryconfigure(idx, label=st.config_name(slot))
        self.config_var.set(st.active_config)

    def open_game_data(self, tab=None):
        from .gamedata import GameData
        w = popout(self, "Game Data", lambda w: GameData(w, self, tab), "900x560")
        if tab:
            for c in w.winfo_children():
                if isinstance(c, GameData):
                    c.select(tab)

    def import_rooms_md(self):
        f = filedialog.askopenfilename(title="MegaMUD Rooms.md", filetypes=[("Rooms.md", "Rooms.md *.md"), ("All", "*.*")])
        if f:
            n = self.s.import_rooms_md(f)
            messagebox.showinfo("MudPilot", f"{n} rooms imported for the Goto window." if n else "No rooms found in that file.")

    def open_picker(self, mode):
        from .gotodlg import Picker
        Picker(self, mode)

    def open_pathbuilder(self):
        from .pathbuilder import PathBuilder
        popout(self, "Path builder", lambda w: PathBuilder(w, self), "900x600")

    def open_party(self):
        w = popout(self, "Party", lambda w: PartyPane(w, self), "340x150")
        try:
            w.title(f"MudPilot — Party ({self.s.settings.my_name or 'you'})")   # whose: several can share a screen
        except Exception:
            pass

    def open_spellbook(self):
        from .gamedata import SpellBookPane
        popout(self, "Spell book", lambda w: SpellBookPane(w, self), "900x560")

    def open_combatcalc(self, mon_num=None):
        from .combatcalc import CombatCalc

        def make(w):
            self._combatcalc = CombatCalc(w, self)
            return self._combatcalc
        popout(self, "Combat calculator", make, "1080x720")
        cc = getattr(self, "_combatcalc", None)
        if mon_num is not None and cc is not None and cc.winfo_exists():
            cc.show(mon_num)

    def open_help(self):
        from .help_text import make_pane
        popout(self, "MudPilot help", lambda w: make_pane(w, self), "980x640")

    def open_statbreaks(self):
        from .statbreaks import make_pane
        popout(self, "Stat & mana-regen breakpoints", lambda w: make_pane(w, self), "880x520")

    def open_expcalc(self):
        from .gamedata import ExpCalcPane
        popout(self, "CP / Exp calculator", lambda w: ExpCalcPane(w, self), "720x560")

    def hist(self, d):
        if not self.history:
            return "break"
        self.hist_i = max(0, min(len(self.history), self.hist_i + d))
        self.entry.delete(0, "end")
        if self.hist_i < len(self.history):
            self.entry.insert(0, self.history[self.hist_i])
        return "break"

    # ------------------------------------------------------------------ loop
    def _loop(self):
        try:
            self.s.poll()
            self._refresh_status()
            self._screen_tick()
        except Exception as ex:  # keep the UI alive; surface the problem
            self.add_log(f"Error: {ex!r}")
        self.root.after(50, self._loop)

    SCREEN_KEYS = {"Return": b"\r", "KP_Enter": b"\r", "BackSpace": b"\x08", "Tab": b"\t", "Escape": b"\x1b",
                   "Up": b"\x1b[A", "Down": b"\x1b[B", "Right": b"\x1b[C", "Left": b"\x1b[D", "Delete": b"\x7f"}

    def _screen_key(self, e):
        """While a full-screen page is up, keys go straight to the game one at a time (like a terminal):
        Space toggles a choice, arrows / Tab / Enter move between fields, Backspace fixes a typo."""
        sc = getattr(self.s.ansi, "screen", None)
        if sc is None or not sc.active or not self.s.telnet.connected:
            return None
        if e.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock"):
            return "break"
        data = self.SCREEN_KEYS.get(e.keysym)
        if data is None and e.char and (e.char >= " " or e.char == "\t"):
            data = e.char.encode("cp437", errors="replace")
        if data is None:
            return None
        self.s.telnet.send_raw(data)
        self.s._user_sent_at = time.time()
        return "break"

    def _screen_tick(self):
        """Full-screen pages (train stats, the character editor, ANSI menus) are drawn with cursor moves:
        show them as the 80×25 screen they are, over the MUD window, until you're back in the realm."""
        sc = getattr(self.s.ansi, "screen", None)
        if sc is None:
            return
        w = getattr(self, "scr", None)
        if not sc.active:
            if w is not None and w.winfo_ismapped():
                w.place_forget()
            return
        if w is None:
            stf = self.s.settings
            w = self.scr = tk.Text(self.term.master, background=BG, foreground=FG[None][0], borderwidth=0,
                                   font=self._term_font(), wrap="none",
                                   padx=6, pady=4, state="disabled", cursor="arrow")
            for k, (n, b) in FG.items():
                ks = "x" if k is None else k
                w.tag_configure(f"c{ks}", foreground=n)
                w.tag_configure(f"c{ks}b", foreground=b)
                w.tag_configure(f"r{ks}", foreground=BG, background=n)
                w.tag_configure(f"r{ks}b", foreground=BG, background=b)
            w.bind("<Button-1>", lambda e: (self.entry.focus_set(), "break")[1])
            self._scr_seq = None
        if not w.winfo_ismapped():
            w.place(in_=self.term, relx=0, rely=0, relwidth=1, relheight=1)
            w.lift()
        if self._scr_seq == sc.seq:
            return
        self._scr_seq = sc.seq
        w.configure(state="normal")
        w.delete("1.0", "end")
        for ri, row in enumerate(sc.cells):
            last = max((i for i, c in enumerate(row) if c[0] != " " or c[3]), default=-1)
            run, tag = "", None
            for ch, fg, bold, rev in row[:last + 1]:
                t = ("r" if rev else "c") + ("x" if fg is None else str(fg)) + ("b" if bold else "")
                if t != tag and run:
                    w.insert("end", run, (tag,))
                    run = ""
                tag = t
                run += ch
            if run:
                w.insert("end", run, (tag,))
            if ri < len(sc.cells) - 1:
                w.insert("end", "\n")
        w.configure(state="disabled")

    # ------------------------------------------------------------------ status bar (MegaMUD-style)
    def _build_statusbar(self):
        sb = tk.Frame(self.root, background="#0f1318")
        sb.pack(side="bottom", fill="x")
        def cell(width=None, anchor="w", side="left", fg=TEXT):
            f = tk.Frame(sb, background="#0f1318", highlightthickness=1, highlightbackground="#232b36")
            f.pack(side=side, fill="y", padx=(0, 1))
            lbl = tk.Label(f, text="", background="#0f1318", foreground=fg, font=("Segoe UI", 9), anchor=anchor,
                           width=width, padx=6, pady=2)
            lbl.pack(side="left", fill="both")
            return f, lbl
        f, self.sb_dot = cell(2, "center")
        self.sb_dot.configure(text="●", foreground="#ff5c5c", font=("Segoe UI", 10))
        _f, self.sb_path = cell(12)
        _f, self.sb_step = cell(4, "e")
        lf, self.sb_lag = cell(4, "e")
        self.sb_lagbar = tk.Canvas(lf, width=60, height=10, background="#0f1318", highlightthickness=1,
                                   highlightbackground="#3a4556")
        self.sb_lagbar.pack(side="left", padx=(0, 6))
        rf, self.sb_round = cell(5, "e")
        self.sb_roundbar = tk.Canvas(rf, width=70, height=10, background="#0f1318", highlightthickness=1,
                                     highlightbackground="#3a4556")
        self.sb_roundbar.pack(side="left", padx=(0, 6))
        Tip(self.sb_round, "Next combat round (learned from when the hits land)")
        self.root.after(200, self._round_tick)
        _f, self.sb_state = cell(26)
        _f, self.sb_mode = cell(None)
        _f, self.sb_mana = cell(7, "e", side="right")
        self.sb_busy_f, self.sb_busy = cell(None, "e", side="right")
        self.sb_busy_bar = ttk.Progressbar(self.sb_busy_f, length=140, maximum=100, style="MA.Horizontal.TProgressbar")
        self.sb_busy_f.pack_forget()
        _f, self.sb_exp = cell(12, "e", side="right")
        for w, tip in ((self.sb_path, "Path / loop file"), (self.sb_step, "Step"), (self.sb_lag, "Seconds the game took to answer (Stats shows the 10-minute average and worst)"),
                       (self.sb_state, "What MudPilot is doing"), (self.sb_exp, "Experience per hour"),
                       (self.sb_mana, "Mana per regen tick")):
            Tip(w, tip)

    def _round_tick(self):
        """Reverse bar counting down to the next combat round (10x a second)."""
        try:
            c = self.s.clock
            r = c.left()
            cv = self.sb_roundbar
            cv.delete("all")
            if r:
                rem, frac = r
                col = "#ff5c5c" if rem < 0.6 else "#e6b450" if rem < 1.5 else "#3d7eff"
                cv.create_rectangle(1, 1, 1 + int(68 * frac), 10, fill=col, outline="")
                self.sb_round.configure(text=f"{rem:.1f}s")
            else:
                self.sb_round.configure(text="")
        except (tk.TclError, AttributeError):
            pass
        self.root.after(100, self._round_tick)

    def _refresh_statusbar(self):
        import os as _os
        s, st, bot = self.s, self.s.state, self.s.bot
        x = bot.x
        self.sb_dot.configure(foreground="#2fbf71" if s.telnet.connected else "#ff5c5c")
        mp = bot.path if bot.walking else None
        if mp and mp.title.startswith("Go to ") and bot.after_goto:
            name = "→ " + (_os.path.splitext(_os.path.basename(bot.after_goto.filename or ""))[0] or bot.after_goto.title)
        elif mp:
            name = _os.path.splitext(_os.path.basename(mp.filename or ""))[0] or mp.title
        else:
            name = ""
        self.sb_path.configure(text=name[:12])
        # rooms left to go, counting down (a loop: left this lap)
        self.sb_step.configure(text=str(max(0, len(mp.steps) - bot.idx)) if mp else "")
        lag = st.lag or 0
        self.sb_lag.configure(text=f"{lag:.1f}" if lag else "")
        self.sb_lagbar.delete("all")
        segs = min(int(lag / 0.5) + 1, 10) if lag else 0
        for i in range(segs):
            col = "#2fbf71" if lag < 2 else "#e6b450" if lag < 4 else "#ff5c5c"
            self.sb_lagbar.create_rectangle(2 + i * 6, 2, 6 + i * 6, 9, fill=col, outline="")
        cfg = s.settings
        if st.resting:
            what = ("Medi." if st.meditating else "Resting") + " to full"
        elif x.waiting_on and bot.walking:      # (stopped: that wait is over — Buddy showed it for minutes)
            what = "Waiting for " + ", ".join(x.waiting_on)
        elif s.remote.holding():
            what = f"Waiting ({s.remote.hold_text()})"
        elif x.pvp_target:
            what = f"PvP: {x.pvp_target}"
        elif st.in_combat:
            what = "Fighting"
        elif not s.telnet.connected:
            what = "Offline"
        else:
            what = bot.status.split("(")[0].strip()[:26] or "Idle"
        self.sb_state.configure(text=what)
        if mp and bot.loop and not mp.title.startswith("Go to "):
            mode = f"Looping ... (Lap {bot.laps + 1}, {max(0, len(mp.steps) - bot.idx)} left)"
        elif mp and mp.title.startswith("Go to "):
            mode = f"Going to {mp.title[6:]} — {max(0, len(mp.steps) - bot.idx)} rooms to go"
        elif mp:
            mode = f"Walking path ({len(mp.steps) - bot.idx} steps left)"
        elif x.roaming:
            mode = "Auto-roaming"
        else:
            mode = "AUTO" if cfg.auto_combat else "MANUAL"
        why_not = bot.status if (not mp and str(bot.status).startswith(("Not walking", "Stopped:", "Stopped —"))) else ""
        rn = getattr(bot, "route_note", None)
        if not why_not and mp and rn and time.time() - rn[1] < 180:
            why_not = rn[0]                         # walking the long way round: why
        if why_not:
            # why it isn't doing what you asked, in full, till you ask for something else (Dan, 2026-11-01: Buddy
            # refused the Iceforge for want of a dragon key and the bar only said 'Waiting for Evolution')
            mode = f"{mode} · {why_not}"
            if len(mode) > 120:
                mode = mode[:119] + "…"
        self.sb_mode.configure(text=mode, foreground="#ffb347" if why_not else TEXT)
        rate = s.stats.exp_rate()
        self.sb_exp.configure(text=f"{rate / 1000:,.0f} k/hr" if rate >= 1000 else f"{rate:,.0f} /hr")
        self.sb_mana.configure(text=f"M:{st.mana_tick}" if st.mana_tick else "M:—")
        busy = s.paths_busy
        if busy:
            done, total, label = busy
            if not self.sb_busy_f.winfo_ismapped():
                self.sb_busy_f.pack(side="right", fill="y", padx=(0, 1), before=self.sb_exp.master)
                self.sb_busy_bar.pack(side="left", padx=(0, 6))
            self.sb_busy.configure(text=f"{label}: {done:,}/{total:,}")
            self.sb_busy_bar["value"] = 100 * done / max(total, 1)
        elif self.sb_busy_f.winfo_ismapped():
            self.sb_busy_f.pack_forget()

    def _set_icon(self, root):
        """MudPilot's logo on the window, taskbar and every pop-up window."""
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        try:
            if os.name == "nt":
                from . import winshell
                winshell.set_process_id()          # own taskbar button/icon instead of Python's
                root.iconbitmap(os.path.join(here, "mudpilot.ico"))
                root.iconbitmap(default=os.path.join(here, "mudpilot.ico"))
        except Exception:
            pass
        try:
            self._icons = [tk.PhotoImage(file=os.path.join(here, f"logo_{n}.png")) for n in (256, 64, 32, 16)]
            root.iconphoto(True, *self._icons)
            self._logo_small = tk.PhotoImage(file=os.path.join(here, "logo_24.png"))
            self._logo_big = tk.PhotoImage(file=os.path.join(here, "logo_128.png"))
        except (tk.TclError, OSError):
            self._logo_small = self._logo_big = None

    def _clear_alert_title(self):
        self._alert_title = None
        self._update_title()

    def _update_title(self):
        """MegaMUD-style: 'Miserable (Mage) [Solo] - MudPilot 0.6'."""
        if self._alert_title:
            return
        from . import __version__
        st, cfg = self.s.state, self.s.settings
        who = cfg.my_name or cfg.profile
        cls = st.char_class or cfg.char_class
        tag = cfg.profile
        if (cfg.config_profiles.get(cfg.active_config) or {}).get("name"):
            tag += f" · {cfg.config_name(cfg.active_config)}"
        t = f"{who}{f' ({cls})' if cls else ''} [{tag}] - MudPilot v{__version__}"
        if self.root.title() != t:
            self.root.title(t)
            from .windows import retitle
            self._tied_windows = [w for w in getattr(self, "_tied_windows", []) if w.winfo_exists()]
            for w in self._tied_windows:
                retitle(self, w)

    def _refresh_status(self):
        self._update_title()
        try:
            self._refresh_statusbar()
        except (tk.TclError, AttributeError):
            pass
        self._afk_tick()
        st, bot = self.s.state, self.s.bot
        self.lbl_room.configure(text=f"Room: {st.room_label}")
        if st.max_hp:
            self.pb_hp["value"] = st.hp_pct()
            self.lbl_hp.configure(text=f"{st.hp}/{st.max_hp}")
        if st.max_ma:
            self.pb_ma["value"] = st.ma_pct()
            self.lbl_ma.configure(text=f"{st.ma}/{st.max_ma}")
        mobs = bot.attackable() if st.view else []
        self.lbl_mobs.configure(text=f"Mobs: {len(mobs)}" + (" ⚔" if st.in_combat else ""))
        conn = "Connected" if self.s.telnet.connected else "Offline"
        self.lbl_status.configure(text=f"{bot.status}   •   {conn}")
        self._connect_btn_refresh()
        self._stop_btn_refresh()
        if getattr(self, "_pct_labels", None) and time.time() - getattr(self, "_pct_at", 0) > 2:
            self._pct_at = time.time()
            self._pct_refresh()
        if st.view_seq != self._map_seq:
            self._map_seq = st.view_seq
            self.map.redraw()
            for m in list(self.extra_maps):
                try:
                    m.redraw()
                except tk.TclError:
                    self.extra_maps.remove(m)
            self.refresh_spell_table()
        now = time.time()
        if now - getattr(self, "_slow_t", 0) > 1:
            self._slow_t = now
            self._refresh_stats()
            self.refresh_buffs()
            self.refresh_bosses()
            self.refresh_events()

    def _refresh_stats(self):
        alive = []
        for p in self.live_panes:
            try:
                if p.winfo_exists():
                    if p.winfo_viewable():
                        p.refresh()      # (a Stats / exp chart tab you're not looking at, or a minimized window: not
                    alive.append(p)      #  rebuilt every second — Miserable PVE's window stuck in it 14 times)
            except tk.TclError:
                pass
        self.live_panes = alive

    def look_for_scrolls(self):
        """Spells tab: run the spell-scroll errand as soon as MudPilot is free (scrolls.py)."""
        if self.s.scrolls.want_now("you asked"):
            self.s.log("Spell scrolls: will look as soon as MudPilot is free (not walking, not fighting)")
        else:
            self.s.log("Spell scrolls: already on it")

    def reread_spells(self):
        self.s.bot._spells_asked = False
        self.s.state.known_spells = None
        if self.s.telnet.connected:
            self.s.bot.maybe_read_spells() or self.s.send("spells")

    def refresh_spell_table(self):
        from .spells import auto_pick, spell_kind, ELEMENT_NAME
        cfg, st = self.s.settings, self.s.state
        cands = self.s.spell_candidates() if self.s.world.loaded else []
        known = self.s.known_spell_dicts()
        if known:
            atk = sorted((sp for sp in known if self.s._is_attack(sp)), key=lambda x: -int(x.get("ReqLevel") or 0))
            when = time.strftime("%b %d %H:%M", time.localtime(cfg.known_spells_at)) if cfg.known_spells_at else ""
            self.sp_known.configure(text=f"{len(known)} spells from the game ({when}); attack: "
                                         + ", ".join(sp["Short"] for sp in atk))
        elif cands:
            self.sp_known.configure(text="Spell list not read yet — using what your class can learn at your level. "
                                         "It reads `spells` automatically after you log in.")
        else:
            self.sp_known.configure(text="Spell list not read yet. Log in (it types `spells` for you), or set your "
                                         "class with `stat` / Character level above.")
        mobs = [m for m in (st.view.monsters if st.view else []) if m[1]]
        key = (tuple(sp["Number"] for sp in cands), tuple(m[1]["num"] for m in mobs), cfg.char_level,
               cfg.spell_min_pct, cfg.auto_spells, cfg.spell_pick)
        self.sp_info.configure(text=self.s.bot.spell_info)
        if key == self._sp_key:
            return
        self._sp_key = key
        self.sp_tree.delete(*self.sp_tree.get_children())
        lvl = cfg.char_level or st.level
        if not cands:
            self.sp_tree.insert("", "end", values=("(no attack spells known yet)", "", "", "", "", ""))
            return
        thr = cfg.spell_min_pct / 100
        recs = [m[1] for m in mobs]
        if recs:
            pick = auto_pick(self.s.spellbook, cands, recs, lvl, 10 ** 6, thr, self.s.bot.spellcasting(), cfg.spell_dmg_bonus,
                             "damage" if cfg.spell_pick == "damage" else "mana")
            pick_no = pick[0]["Number"] if pick else None
            title = f"vs {recs[0]['name']}" + (f" + {len(recs) - 1} more" if len(recs) > 1 else "")
            self.sp_tree.insert("", "end", values=(title, "", "", "", "", ""))
            rows = []
            for sp in cands:
                one = auto_pick(self.s.spellbook, [sp], recs, lvl, 10 ** 6, 0, self.s.bot.spellcasting(), cfg.spell_dmg_bonus)
                rated = calc(sp, lvl, None, self.s.bot.spellcasting(), cfg.spell_dmg_bonus).round_dmg
                if not one:
                    continue
                _sp, eff, ratio, kind, note = one
                rows.append((eff, sp, rated, ratio, note))
            for eff, sp, rated, ratio, note in sorted(rows, key=lambda r: -r[0])[:14]:
                el = ELEMENT_NAME.get(int(sp.get("AttType") or 0), "—")
                tag = "pick" if sp["Number"] == pick_no else ("bad" if ratio < thr else "good")
                self.sp_tree.insert("", "end", tags=(tag,),
                                    values=(("▶ " if tag == "pick" else "  ") + sp["Name"], el, rated, eff,
                                            f"{ratio:.0%}", note))
        else:
            for sp in sorted(cands, key=lambda x: -int(x.get("ReqLevel") or 0))[:14]:
                c = calc(sp, lvl, None, self.s.bot.spellcasting(), cfg.spell_dmg_bonus)
                self.sp_tree.insert("", "end", values=(sp["Name"], ELEMENT_NAME.get(int(sp.get("AttType") or 0), "—"),
                                                       c.round_dmg, "—", "", spell_kind(sp) or ""))

    # ------------------------------------------------------------------ actions
    def _pvp_press(self, e):
        self._pvp_down = time.time()

    def _pvp_release(self, e):
        held = time.time() - getattr(self, "_pvp_down", time.time())
        if held >= 0.9:
            self._pvp_snoozed = True
            self.add_log("PvP reminder off for this session")
        else:
            self._var("hangup_on_pvp").set(True)
            self.add_log("Hang up when a player attacks me: ON")

    def _pvp_flash(self):
        cfg = self.s.settings
        try:
            show = cfg.pvp_realm and not cfg.hangup_on_pvp and not self._pvp_snoozed
            if self.btn_pvp is None:
                pass
            elif show:
                if not self.btn_pvp.winfo_manager():
                    self.btn_pvp.pack(side="left", padx=(12, 0))
                on = int(time.time() * 2) % 2 == 0
                self.btn_pvp.configure(background="#d62020" if on else "#5a0c0c")
            elif self.btn_pvp.winfo_manager():
                self.btn_pvp.pack_forget()
            nh = getattr(self, "btn_nohang", None)
            if nh is not None:
                if cfg.no_hang:
                    if not nh.winfo_manager():
                        nh.pack(side="left", padx=(12, 0))
                    if cfg.pvp_realm:
                        nh.configure(background="#d62020" if int(time.time() * 2) % 2 == 0 else "#5a0c0c")
                    else:
                        nh.configure(background="#5a3c00")   # PVE: dying costs nothing to a player — no flashing
                elif nh.winfo_manager():
                    nh.pack_forget()
            bm = getattr(self, "btn_manual", None)
            if bm is not None:
                if self.s.bot.manual.active:
                    bm.configure(text="⚔ " + self.s.bot.manual.label())
                    if not bm.winfo_manager():
                        bm.pack(side="left", padx=(12, 0))
                elif bm.winfo_manager():
                    bm.pack_forget()
            for btn, on_, c1, c2 in ((getattr(self, "btn_nowait", None), cfg.no_wait, "#d62020", "#5a0c0c"),
                                     (getattr(self, "btn_handsoff", None), cfg.hands_off, "#d08a00", "#5a3c00")):
                if btn is None:
                    continue
                if on_:
                    if not btn.winfo_manager():
                        btn.pack(side="left", padx=(12, 0))
                    btn.configure(background=c1 if int(time.time() * 2) % 2 == 0 else c2)
                elif btn.winfo_manager():
                    btn.pack_forget()
        except tk.TclError:
            pass
        self.root.after(500, self._pvp_flash)

    def report_problem(self):
        """Say what went wrong; the MUD screen, logs and errors go with it so it can be fixed."""
        from . import report as R
        d = tk.Toplevel(self.root)
        d.title("Report a problem - MudPilot")
        d.geometry("620x440")
        d.transient(self.root)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="What went wrong? What were you doing, and what did you expect to happen?",
                  style="Head.TLabel").pack(anchor="w")
        txt = tk.Text(fr, height=10, wrap="word", background="#0f1318", foreground=TEXT, insertbackground=TEXT,
                      borderwidth=0, padx=6, pady=6, font=("Segoe UI", 10))
        txt.pack(fill="both", expand=True, pady=(6, 6))
        inc = tk.BooleanVar(value=True)
        ttk.Checkbutton(fr, text="Include the MUD screen back-scroll (helps a lot — it has the game text and chat)",
                        variable=inc).pack(anchor="w")
        ttk.Label(fr, text="Also sent: MudPilot's log, any errors, and this character's settings with passwords, "
                           "user name and other secrets removed. A copy is saved in MudPilot\\data\\reports.",
                  style="Muted.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=(4, 0))
        res = ttk.Label(fr, text="", style="Muted.TLabel", wraplength=580)
        res.pack(anchor="w", pady=(6, 0))
        bb = ttk.Frame(fr)
        bb.pack(fill="x", pady=(8, 0))

        def go():
            what = txt.get("1.0", "end").strip()
            if not what:
                res.configure(text="Type a line or two about what happened first.")
                return
            if time.time() - getattr(self, "_report_at", 0) < 60:
                res.configure(text="You just sent one — give it a minute.")
                return
            self._report_at = time.time()
            screen = self.term.get("1.0", "end-1c") if inc.get() else ""
            try:
                path = R.build(self.s, what, screen, inc.get())
            except Exception as ex:
                res.configure(text=f"Couldn't build the report: {ex}")
                return
            send_b.configure(state="disabled")
            res.configure(text=f"Saved {os.path.basename(path)} — sending…")

            def done(ok, msg):
                def ui():
                    try:
                        res.configure(text=f"{'✓ ' if ok else ''}{msg}\n{path}")
                        if ok:
                            d.after(2500, d.destroy)
                        else:
                            send_b.configure(state="normal")
                    except tk.TclError:
                        pass
                self.root.after(0, ui)
            R.send(path, what, self.s.settings.my_name, done)
        send_b = ttk.Button(bb, text="Send report", style="Accent.TButton", command=go)
        send_b.pack(side="right")
        ttk.Button(bb, text="Open reports folder", command=lambda: self._open(R.REPORTS_DIR)).pack(side="left")
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right", padx=6)
        txt.focus_set()

    def resume_boss(self):
        if not self.s.bot.resume_boss():
            self.add_log("Nothing to resume — not stopped before a boss")

    def stop_or_rego(self):
        bot = self.s.bot
        if bot.walking or not getattr(bot, "resume", None):
            self.stop_bot()
        else:
            if getattr(self.s.settings, "hands_off", False):
                # Rego is you saying 'go': Hands off would leave it standing there (Dan, 2026-11-02: "i rego'd
                # this thing it wont move")
                self._var("hands_off").set(False)
                self.s.settings.hands_off = False
                self.s.log("You clicked Rego — Hands off is off again")
            bot.rego()

    def _stop_btn_refresh(self):
        bot = self.s.bot
        # "Stop" only while it's going somewhere: on a stopped character it looked like he was about to walk off
        # (Dan, 2026-11-03)
        want = ("■ Stop (Esc)", "Stop.TButton") if bot.walking else ("▶ Rego", "Accent.TButton") \
            if getattr(bot, "resume", None) else ("Stopped", "TButton")
        if getattr(self, "_stop_btn_state", None) != want:
            self._stop_btn_state = want
            try:
                self.btn_stop.configure(text=want[0], style=want[1])
            except (tk.TclError, AttributeError):
                pass

    def stop_bot(self):
        self.s.bot.stop("Stopped by you")
        self.s.state.pending.clear()

    def connect_dialog(self):
        ConnectDialog(self.root, self)

    def connect_toggle(self):
        """MegaMUD's phone button: connect when offline, hang up when online."""
        if self.s.telnet.connected:
            self.s.hold_realm = True            # you hung up: next connect waits at the MajorMUD menu
            self.s.disconnect()
            self.s.show_down("DISCONNECTED (☎)")
            return
        st = self.s.settings
        saved = config.get_password(st.username, st.host) if (st.host and st.username and st.save_password) else None
        if saved:
            # Dan: the board, user and saved password are all known — connect, no Connect dialog to OK
            self._do_connect(st.host, int(st.port or 23), st.username, saved, True)
        else:
            self.connect_dialog()                    # first time (or nothing saved): ask

    def _connect_btn_refresh(self):
        on = self.s.telnet.connected
        want = ("☎ Hang up", "Stop.TButton") if on else ("☎ Connect", "Accent.TButton")
        if getattr(self, "_conn_btn_state", None) != want:
            self._conn_btn_state = want
            try:
                self.btn_connect.configure(text=want[0], style=want[1])
            except (tk.TclError, AttributeError):
                pass

    def start_practice(self):
        if not self.s.world.loaded:
            messagebox.showinfo("MudPilot", "Import an MME database first (File → Import MME database).")
            return
        from . import simserver
        import asyncio

        def run():
            try:
                asyncio.run(simserver.main_async(2323, int(time.time()), 0.15, self.s.world_path))
            except Exception as ex:
                self.add_log(f"Practice server: {ex}")
        threading.Thread(target=run, daemon=True).start()
        self.add_log("Practice server running on 127.0.0.1:2323 (any user/password).")
        # the practice server never changes your real BBS address or login
        self._practice_tries = 0
        self.root.after(800, self._practice_connect)

    def _practice_connect(self):
        """The practice server needs a few seconds to load the MME data; keep trying quietly."""
        import socket
        try:
            socket.create_connection(("127.0.0.1", 2323), timeout=0.3).close()
        except OSError:
            self._practice_tries += 1
            if self._practice_tries < 60:
                self.root.after(500, self._practice_connect)
            else:
                self.add_log("Practice server didn't start.")
            return
        self.s.practice = True
        self.s.password = "practice"
        try:
            self.s.connect("127.0.0.1", 2323)
        except OSError as ex:
            self.add_log(f"Practice server: {ex}")

    def _do_connect(self, host, port, user, pw, save, auto=False):
        st = self.s.settings
        st.host, st.port, st.username = host, int(port), user
        if pw:
            self.s.password = pw
            if save and host not in ("127.0.0.1", "localhost"):
                if not config.set_password(user, pw, host):
                    where = "Windows Credential Manager" if sys.platform == "win32" else "the system keyring"
                    self.add_log(f"Couldn't save password to {where} (keyring missing).")
        st.save_password = save
        st.save()
        try:
            self.s.connect(host, port)
        except OSError as ex:
            if auto and st.auto_reconnect:
                # opening by itself (a restart, auto-connect): no dialog nobody's there to click — keep trying like
                # after a dropped line (Buddy sat on 'Couldn't connect' after a restart, 2026-10-30)
                self.s._want_connected, self.s._closed_at = True, time.time()
                self.s.log(f"Couldn't connect to {host}:{port} ({ex}) — trying again every "
                           f"{self.s._retry_delay()} s")
                return
            messagebox.showerror("MudPilot", f"Couldn't connect to {host}:{port}\n\n{ex}")

    def _load_world_status(self):
        if not self.s.world.loaded:
            self.add_log("No MME data yet — use File → Import MME database (.mdb).")
        else:
            self.add_log(f"MME data loaded: {len(self.s.world.rooms):,} rooms, "
                         f"{len(self.s.world.monsters):,} monsters, {len(self.s.world.spells):,} spells.")
            n = sum(1 for p in self.s.paths if p.resolved)
            if self.s.paths:
                self.add_log(f"{len(self.s.paths)} saved path(s), {n} matched to MME rooms.")

    def import_mme(self):
        f = filedialog.askopenfilename(title="Select MME database", filetypes=[("MME data", "*.mdb"), ("All", "*.*")])
        if not f:
            return
        board = BoardDialog.ask(self.root, self.s.settings.board, config.list_boards(),
                                self.s.settings.profile)
        if not board:
            return
        target = config.world_path(board)
        if os.path.exists(target) and not messagebox.askyesno(
                "Import MME", f"Replace the MME data for board '{board}' with {os.path.basename(f)}?"):
            return
        os.makedirs(config.board_dir(board), exist_ok=True)
        win = tk.Toplevel(self.root)
        win.title("Importing")
        win.configure(background=PANEL)
        lbl = ttk.Label(win, text="Starting…", padding=20)
        lbl.pack()
        pb = ttk.Progressbar(win, mode="indeterminate", length=280)
        pb.pack(padx=20, pady=(0, 20))
        pb.start(12)
        result = {}

        def work():
            try:
                WorldDB.import_mdb(f, target, progress=lambda m: self.root.after(0, lbl.configure, {"text": m}))
            except Exception as ex:
                result["err"] = ex

        def done():
            if t.is_alive():
                self.root.after(200, done)
                return
            win.destroy()
            if "err" in result:
                messagebox.showerror("Import failed", str(result["err"]))
                return
            self.board_box.configure(values=config.list_boards())
            self.set_board(board, announce=False)
            self._load_world_status()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        self.root.after(200, done)

    def import_mp_files(self):
        files = filedialog.askopenfilenames(title="Select MegaMUD paths", filetypes=[("MegaMUD path", "*.mp")])
        if files:
            self._import(list(files))

    def import_mp_folder(self):
        d = filedialog.askdirectory(title="Select MegaMUD folder (e.g. C:\\Megamud\\Default)")
        if d:
            files = find_mp_files(d)
            rooms_md = None
            for root_, _ds, fs in os.walk(d):
                for fn in fs:
                    if fn.lower() == "rooms.md":
                        rooms_md = os.path.join(root_, fn)
                        break
                if rooms_md:
                    break
            if rooms_md:
                n = self.s.import_rooms_md(rooms_md)
                self.add_log(f"Imported {n} MegaMUD rooms (Rooms.md) for the Goto window")
            if not files:
                messagebox.showinfo("MudPilot", "No .mp files found in that folder.")
                return
            self._import(files)

    def _import(self, files):
        if not self.s.world.loaded:
            if not messagebox.askyesno("MudPilot", "No MME data imported yet, so paths can't be matched to "
                                                   "room numbers. Import the paths anyway?"):
                return
        if self.s.paths_busy:
            messagebox.showinfo("MudPilot", "Paths are still being imported — wait for the progress bar at the "
                                            "bottom to finish, then try again.")
            return
        self.add_log(f"Importing {len(files)} path file(s) in the background…")

        def done(ok, res, errs):
            msg = f"Imported {ok} path(s).\n{res} matched step-by-step to MME map/room numbers."
            if errs:
                msg += f"\n\nSkipped {len(errs)}:\n" + "\n".join(errs[:10]) + ("\n…" if len(errs) > 10 else "")
            messagebox.showinfo("Paths imported", msg)
        self.s.import_paths(files, on_done=done)

    def _paths_changed(self):
        self.refresh_paths()
        if hasattr(self, "task_loop"):
            self.task_loop.configure(values=sorted(p.title for p in self.s.paths if p.is_loop))

    def refresh_paths(self):
        if not hasattr(self, "tree"):
            return
        mode = self.paths_mode.get() if hasattr(self, "paths_mode") else "loop"
        q = self.paths_q.get().strip().lower() if hasattr(self, "paths_q") else ""
        self.tree.delete(*self.tree.get_children())
        other = 0
        if mode == "loop":
            self._refresh_loops(q)
        for mp in sorted(self.s.paths, key=lambda p: p.title.lower()):
            start = mp.steps[0].room if mp.steps and mp.steps[0].room else None
            label = (f"{start[0]}/{start[1]} " if start else "") + (mp.start_label or "") +                 (f"  [{mp.start_group}]" if mp.start_group else "")
            if q and q not in mp.title.lower() and q not in label.lower() and \
                    q not in os.path.basename(mp.filename or "").lower():
                continue
            if mode == "loop" and not mp.is_loop or mode == "path" and mp.is_loop:
                other += 1
                continue
            if mode == "loop":
                continue                             # (listed by _refresh_loops, by area folder)
            sm = self.s.loopstats.summary(self.s.bot.x.loop_key(mp)) if mp.is_loop else None
            eh = f"{sm['exp_hr'] / 1000:,.0f}k" if sm else ""
            self.tree.insert("", "end", iid=mp.filename, text=mp.title,
                             values=(len(mp.steps), eh, "✓" if mp.resolved else "hash only", label))
        if hasattr(self, "paths_hint") and mode in ("loop", "path"):
            if q and other:
                self.paths_hint.configure(text=f"{other} more match{'es' if other != 1 else ''} under "
                                               + ("Paths (they don't end where they start)" if mode == "loop" else "Loops"))
            else:
                self.paths_hint.configure(text=("Pick a loop and Run (double-click). If you're not on it, MudPilot "
                                                "walks to its start first." if mode == "loop" else
                                                "Pick a path and Run. MudPilot walks to its start first if needed."))

    def _loop_values(self, mp):
        start = mp.steps[0].room if mp.steps and mp.steps[0].room else None
        label = (f"{start[0]}/{start[1]} " if start else "") + (mp.start_label or "")
        sm = self.s.loopstats.summary(self.s.bot.x.loop_key(mp))
        eh = f"{sm['exp_hr'] / 1000:,.0f}k" if sm else ""
        return len(mp.steps), eh, "✓" if mp.resolved else "hash only", label

    def _refresh_loops(self, q):
        """The Loops list: the same loops as the toolbar's Run a loop…, grouped by the same area folders
        (Dan, 2026-11-04: 'the paths/loops window should be mirror image'). Folders open while searching."""
        from .gotodlg import loop_entries, loop_matches
        groups = {}
        for grp, label, item in sorted(loop_entries(self.s), key=lambda x: (x[0].lower(), x[1].lower())):
            if not loop_matches(q, grp, label, item):
                continue
            gid = groups.get(grp)
            if gid is None:
                gid = groups[grp] = self.tree.insert("", "end", iid=f"folder:{grp}", text=f"📁 {grp}", open=bool(q))
            kind, val = item
            if kind == "routine":
                self.tree.insert(gid, "end", iid=PERUSE_IID, text=label, values=("", "", "routine", "12/2248"))
            else:
                self.tree.insert(gid, "end", iid=val.filename, text=label, values=self._loop_values(val))

    def send_path_dialog(self):
        """Send the selected path / loop to another MudPilot by telepath (Dan, 2026-11-01: so Evolution can lead on
        the loop I just drew). They need to be in your party, or allow you to move them."""
        mp = self._selected_path()
        if not mp:
            return
        st = self.s.state
        me = (self.s.settings.my_name or "").lower()
        mates = [n for n in (st.party or {}) if n.lower() != me]
        who = simpledialog.askstring("Send path", f"Send '{mp.title}' ({len(mp.steps)} steps) to who?"
                                     + (f"\nIn your party: {', '.join(mates)}" if mates else ""),
                                     initialvalue=mates[0] if len(mates) == 1 else "", parent=self.root)
        if not who or not who.strip():
            return
        err = self.s.pathshare.send(mp, who.strip().split()[0].capitalize())
        if err:
            messagebox.showinfo("Send path", err, parent=self.root)

    def move_path_folder(self):
        """Put a saved path/loop in another area folder (the Loops picker groups them by it)."""
        from .areafolder import folder_for, set_folder
        from .pathbuilder import ask_folder
        mp = self._selected_path()
        if not mp:
            return
        start = mp.steps[0].room if mp.steps else None
        guess = folder_for(self.s, start) or ""
        f = ask_folder(self.root, self.s, "Move to area folder",
                       f"Move '{mp.title}' (now in {mp.start_group or 'no folder'}) to which area folder?"
                       + (f"\nAround its start, your other paths use: {guess}" if guess else ""), initial=guess)
        if not f or f == mp.start_group:
            return
        old = mp.start_group
        if set_folder(mp, f):
            self.add_log(f"Moved '{mp.title}' from {old or 'no folder'} to {f}")
            self.refresh_paths()
        else:
            messagebox.showinfo("MudPilot", f"Couldn't rewrite {mp.filename or 'that file'}.")

    def _selected_path(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("MudPilot", "Select a path first.")
            return None
        if sel[0] == PERUSE_IID:
            return None
        return next((p for p in self.s.paths if p.filename == sel[0]), None)

    def walk_selected(self, loop):
        if self.tree.selection() and self.tree.selection()[0] == PERUSE_IID:
            self.add_log(self.s.bot.peruse.start())
            return
        mp = self._selected_path()
        if mp:
            self.s.bot.start_path(mp, loop=True if loop else None)

    def goto_then_run(self):
        mp = self._selected_path()
        if not mp:
            return
        if not mp.resolved or not mp.steps[0].room:
            messagebox.showinfo("MudPilot", "This path isn't matched to MME rooms, so I can't route to its start.")
            return
        self.plan_route(lambda ask: self.s.bot.goto(mp.steps[0].room, then=mp, ask=ask), "to the path's start")

    def open_loop_stats(self):
        """Every loop you've run, best exp/hr first, from its last 10 laps."""
        d = tk.Toplevel(self.root)
        d.title("Loop stats - MudPilot")
        d.geometry("860x420")
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Last 10 laps of each loop for {self.s.settings.my_name or 'this character'} — "
                           "empty lairs high = you're lapping faster than it respawns", style="Muted.TLabel").pack(anchor="w")
        adv = self.s.advisor.advise(build=True) if getattr(self.s.bot, "_lap_path", None) else []
        if adv:
            af = ttk.LabelFrame(fr, text="Advice for the loop you're on", padding=6)
            af.pack(fill="x", pady=(6, 0))
            for line in adv:
                ttk.Label(af, text="• " + line, wraplength=800, justify="left").pack(anchor="w")
        cols = ("exphr", "lap", "rests", "empty", "deaths", "level", "laps", "when")
        tv = ttk.Treeview(fr, columns=cols, show="tree headings", height=14)
        tv.heading("#0", text="Loop")
        tv.column("#0", width=220)
        for c, t, w in (("exphr", "Exp/hr", 80), ("lap", "Min/lap", 65), ("rests", "Rests/lap", 70),
                        ("empty", "Empty lairs", 80), ("deaths", "Deaths", 55), ("level", "Level", 50),
                        ("laps", "Laps", 45), ("when", "Last run", 120)):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="e" if c != "when" else "w")
        tv.pack(fill="both", expand=True, pady=6)
        rows = self.s.loopstats.all_summaries()
        for key, sm in rows:
            tv.insert("", "end", text=sm["title"], values=(
                f"{sm['exp_hr'] / 1000:,.0f}k", f"{sm['lap_min']:.1f}", f"{sm['rests']:.1f}",
                "" if sm["empty_lairs"] is None else f"{sm['empty_lairs']:.0%}", sm["deaths"], sm["level"] or "",
                sm["laps"], time.strftime("%a %b %d %H:%M", time.localtime(sm["when"]))))
        if not rows:
            ttk.Label(fr, text="No laps recorded yet — run a loop for a lap or two.", style="Muted.TLabel").pack(anchor="w")

    def autotune_dialog(self):
        """Try a few rest settings on the loop you're running and keep the one that pays best."""
        at, cfg = self.s.autotune, self.s.settings
        d = tk.Toplevel(self.root)
        d.title("Auto-tune resting - MudPilot")
        d.transient(self.root)
        d.configure(background=PANEL)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Runs each of these on the loop you're on, then keeps whichever made the most exp/hr.",
                  style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text="Each trial starts from full HP and mana (that top-up isn't counted), and whatever it "
                           "ends short of full is charged as the resting it would take — so no setting wins by leaving "
                           "the next one empty. Only time actually looping counts. HP never goes under a safe floor; "
                           "a death puts your own settings back and stops the test.", style="Muted.TLabel", wraplength=620,
                  justify="left").pack(anchor="w", pady=(2, 8))
        cols = ("hp", "ma", "mins", "rests", "eph")
        tv = ttk.Treeview(fr, columns=cols, show="tree headings", height=5)
        tv.heading("#0", text="Setting")
        tv.column("#0", width=150)
        for c, t, w in (("hp", "Rest HP below → until", 175), ("ma", "Mana below → until", 160),
                        ("mins", "Minutes", 65), ("rests", "Rests", 55), ("eph", "Exp/hr", 80)):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="e" if c in ("mins", "rests", "eph") else "w")
        tv.pack(fill="x")
        prog = ttk.Label(fr, text="", style="Muted.TLabel")
        prog.pack(anchor="w", pady=(6, 0))
        opt = ttk.Frame(fr)
        opt.pack(anchor="w", pady=(8, 0))
        mins = tk.StringVar(value=str(cfg.tune_mins or 30))
        rounds = tk.StringVar(value=str(cfg.tune_rounds or 1))
        ttk.Label(opt, text="Minutes each").pack(side="left")
        ttk.Spinbox(opt, from_=10, to=180, width=5, textvariable=mins).pack(side="left", padx=4)
        ttk.Label(opt, text="   Rounds").pack(side="left")
        ttk.Spinbox(opt, from_=1, to=3, width=3, textvariable=rounds).pack(side="left", padx=4)
        ttk.Label(opt, text="(2 rounds evens out lucky spawns)", style="Muted.TLabel").pack(side="left", padx=6)

        def fill():
            try:
                tv.delete(*tv.get_children())
            except tk.TclError:
                return
            if at.active:
                rows = [(v, at.results[i]["secs"] / 60, at.results[i]["rests"], at.rate(i) if at.results[i]["secs"] > 60 else None)
                        for i, v in enumerate(at.variants)]
            else:
                last = at.last_results()
                rows = [(v, v.get("mins", 0), v.get("rests", 0), v.get("exp_hr")) for v in last["variants"]] if last \
                    else [(v, 0, 0, None) for v in at.make_variants()]
            for v, m, r, e in rows:
                tv.insert("", "end", text=v["name"], values=(
                    f"{v['rest_below_hp']}% → {v['rest_until_hp']}%",
                    f"{v['rest_below_ma']}% → {v['rest_until_ma']}%" if v["rest_below_ma"] else "(not used)",
                    f"{m:.0f}", r or "", f"{e / 1000:,.0f}k" if e else "—"))
            last = at.last_results()
            prog.configure(text=at.progress() or (f"Last test: {time.strftime('%a %b %d %H:%M', time.localtime(last['t']))}"
                                                   f" on {last['loop']} — kept '{last['variants'][last['best']]['name']}'"
                                                   if last else "Not run yet."))
            btn.configure(text="Stop test" if at.active else "Start test")
            d.after(3000, fill) if d.winfo_exists() else None

        def go():
            if at.active:
                at.abort("you stopped it")
            else:
                try:
                    m, r = int(mins.get()), int(rounds.get())
                except ValueError:
                    m, r = 30, 1
                msg = at.start(m, r)
                self.add_log(f"Auto-tune: {msg}")
                if not at.active:
                    messagebox.showinfo("Auto-tune resting", msg.capitalize(), parent=d)
            fill()
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(10, 0))
        btn = ttk.Button(b, text="Start test", style="Accent.TButton", command=go)
        btn.pack(side="right")
        ttk.Button(b, text="Close", command=d.destroy).pack(side="right", padx=6)
        fill()

    def item_rules_dialog(self):
        """Per-item loot rules (pMUD): one per line."""
        cfg = self.s.settings
        d = tk.Toplevel(self.root)
        d.title("Item rules - MudPilot")
        d.configure(background=PANEL)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="One item a line — name: what to do. Picks up only what fits your encumbrance.",
                  style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text="rope and grapple: max 1\nsilver dagger: get, max 3\nbroadsword: drop\n"
                           "iron key: keep 1\nrusty dagger: never", style="Muted.TLabel", justify="left").pack(anchor="w", pady=4)
        tx = tk.Text(fr, width=60, height=14, background="#0e1319", foreground=TEXT, insertbackground=TEXT)
        tx.pack(fill="both", expand=True)
        tx.insert("1.0", "\n".join(cfg.item_rules or []))

        def save():
            cfg.item_rules = [ln.strip() for ln in tx.get("1.0", "end").splitlines() if ln.strip()]
            cfg.save()
            d.destroy()
        ttk.Button(fr, text="Save", style="Accent.TButton", command=save).pack(anchor="e", pady=(8, 0))

    def save_debug_bundle(self):
        from .diagnose import save_bundle
        try:
            p = save_bundle(self)
        except Exception as ex:
            messagebox.showerror("Debug bundle", f"Couldn't make it: {ex}")
            return
        self.add_log(f"Debug bundle saved: {p}")
        messagebox.showinfo("Debug bundle", f"Saved:\n{p}\n\nAttach that zip in the chat with Claude. It has the "
                            "session recording, today's log and your settings — passwords, tokens and your user name "
                            "are taken out.")
        self._open_folder(os.path.dirname(p))

    def open_traces(self):
        from .recorder import trace_dir
        os.makedirs(trace_dir(), exist_ok=True)
        self._open_folder(trace_dir())

    def _open_folder(self, d):
        config.open_path(d)                           # an Explorer (or Linux file manager) window on that folder

    def copy_diagnostics(self, e=None):
        """Everything needed to see what's going on, on the clipboard — paste it into the chat."""
        from .diagnose import snapshot
        try:
            text = snapshot(self)
        except Exception as ex:
            import traceback
            text = f"(diagnostics failed: {ex})\n{traceback.format_exc()}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if sys.platform != "darwin":
            self.root.update()                # (macOS: a full update() can hang; the clipboard keeps it anyway)
        self.add_log("Diagnostics copied to the clipboard — paste them into the chat")
        messagebox.showinfo("Copy diagnostics", "Copied to the clipboard.\n\nPaste it (Ctrl+V) into the chat with "
                            "Claude.\nPasswords are never included.", parent=self.root)
        return "break"

    def remote_help(self):
        """Every @ command another player can send this MudPilot, with an example of each."""
        from .remote import HELP, CATEGORIES
        d = tk.Toplevel(self.root)
        d.title("Remote @ commands - MudPilot")
        d.configure(background=PANEL)
        d.geometry("980x640")
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        me = self.s.settings.my_name or "YourName"
        ttk.Label(fr, text="Remote @ commands", style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text=f"Other players send these to you by telepath, e.g. /{me} @health. Party members can always use "
                           "the party ones; everything else only works for players you've ticked for it on "
                           "Settings → Talk. Answers come back in {braces}, MegaMUD-style. ★ = MudPilot only "
                           "(MegaMUD ignores those).", style="Muted.TLabel", wraplength=940, justify="left").pack(
            anchor="w", pady=(2, 8))
        box = ttk.Frame(fr)
        box.pack(fill="both", expand=True)
        tv = ttk.Treeview(box, columns=("what", "ex"), show="tree headings")
        tv.heading("#0", text="Command")
        tv.column("#0", width=230)
        tv.heading("what", text="What it does")
        tv.column("what", width=430)
        tv.heading("ex", text="Example")
        tv.column("ex", width=290)
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        groups = {}
        names = {"query": "Status", "location": "Where", "inventory": "Inventory", "invite": "Party invite / join",
                 "move": "Move", "execute": "Run a command", "settings": "Change settings", "hangup": "Hang up",
                 "divert": "Divert telepaths", "party": "Party signals (any party member)"}
        for cat, cmd, what, ex in HELP:
            if cat not in groups:
                groups[cat] = tv.insert("", "end", text=names.get(cat, cat), open=True)
            tv.insert(groups[cat], "end", text="   " + cmd, values=(what, ex.replace("Miserable", me)))
        ttk.Label(fr, text="Typed on your own command line, ';' sends several commands at once: "
                           "e;mist;.@do sand;simp adult red dragon", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Who can use them… (Settings → Talk)", command=lambda: (d.destroy(), self.open_settings("Talk"))).pack(side="left")
        ttk.Button(b, text="Close", command=d.destroy).pack(side="right")
        d.bind("<Escape>", lambda e: d.destroy())

    # ---------------------------------------------------------------- pMUD-style extras
    def track_player(self):
        if self.s.tracker.target:
            if messagebox.askyesno("Tracking", f"Stop tracking {self.s.tracker.target}?", parent=self.root):
                self.s.tracker.stop("stopped by you")
            return
        name = simpledialog.askstring("Track a player", "Player to track (trac):", parent=self.root)
        if name and name.strip():
            self.s.tracker.start(name.strip().split()[0])

    def open_schedules(self):
        popout(self, "Scheduled actions", lambda w: SchedulePane(w, self), "720x380")

    def open_leaderboard(self):
        popout(self, "XP leaderboard", lambda w: LeaderboardPane(w, self), "560x520")

    def open_overview(self):
        """(0.8.201) All characters: one read-only row per MudPilot (overview.py)."""
        from .overview import OverviewPane
        popout(self, "All characters", lambda w: OverviewPane(w, app=self), "1240x360")

    def open_quests(self):
        popout(self, "Quests", lambda w: QuestsPane(w, self), "820x640")

    def open_history(self):
        popout(self, "History", lambda w: HistoryPane(w, self), "980x640")

    def loop_builder_dialog(self):
        """Make a loop through the best lairs near a room, straight from the MME map."""
        s, lb = self.s, self.s.loopbuilder
        d = tk.Toplevel(self.root)
        d.title("Build a loop - MudPilot")
        d.transient(self.root)
        d.configure(background=PANEL)
        d.geometry("1000x520")
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        top = ttk.Frame(fr)
        top.pack(fill="x")
        here = s.state.room
        start = tk.StringVar(value=f"{here[0]}/{here[1]}" if here else "")
        steps = tk.StringVar(value="60")
        safe = tk.BooleanVar(value=True)
        ttk.Label(top, text="Start room (map/room)").pack(side="left")
        ttk.Entry(top, textvariable=start, width=10).pack(side="left", padx=4)
        ttk.Button(top, text="Here", command=lambda: s.state.room and start.set(
            f"{s.state.room[0]}/{s.state.room[1]}")).pack(side="left")
        ttk.Label(top, text="   Up to").pack(side="left")
        ttk.Spinbox(top, from_=10, to=300, width=5, textvariable=steps).pack(side="left", padx=4)
        ttk.Label(top, text="steps").pack(side="left")
        ttk.Checkbutton(top, text="Skip lairs that could kill me", variable=safe).pack(side="left", padx=12)
        info = ttk.Label(fr, text="Looks at every lair you can reach (your level, keys, avoid list), picks the best "
                                  "and chains them into loops. Exp/hr is a rough guess from your pace this session.",
                         style="Muted.TLabel", wraplength=940, justify="left")
        info.pack(anchor="w", pady=(6, 6))
        cols = ("steps", "lairs", "lap", "eph", "need", "mobs")
        tv = ttk.Treeview(fr, columns=cols, show="headings", height=8)
        for c, t, w_ in (("steps", "Steps", 60), ("lairs", "Lairs", 55), ("lap", "Exp/lap", 80),
                         ("eph", "Est. exp/hr", 90), ("need", "Needs HP", 80), ("mobs", "Monsters", 560)):
            tv.heading(c, text=t)
            tv.column(c, width=w_, anchor="w" if c == "mobs" else "e")
        tv.pack(fill="both", expand=True)
        cands = []

        def build():
            import re as _re
            m = _re.match(r"\s*(\d+)\s*[/ ,]\s*(\d+)", start.get())
            if not m or not s.world.room((int(m.group(1)), int(m.group(2)))):
                messagebox.showinfo("Build a loop", "Put a start room as map/room, e.g. 17/1637 (or click Here).", parent=d)
                return
            try:
                n = max(10, min(300, int(steps.get())))
            except ValueError:
                n = 60
            cands[:] = lb.build((int(m.group(1)), int(m.group(2))), n, avoid_deadly=safe.get())
            tv.delete(*tv.get_children())
            for i, c in enumerate(cands):
                need = c["danger"]
                tv.insert("", "end", iid=str(i), values=(c["steps"], len(c["lairs"]), f"{c['exp_lap']:,}",
                                                        f"{c['exp_hr'] / 1000:,.0f}k",
                                                        f"{need:.0f}%" if need and need <= 100 else ("risky" if need else "—"),
                                                        ", ".join(c["mobs"])))
            if cands:
                tv.selection_set("0")
            else:
                tv.insert("", "end", values=("", "", "", "", "", "No lairs worth looping within reach — try more steps."))
        name = tk.StringVar(value="")

        def pick():
            sel = tv.selection()
            return cands[int(sel[0])] if sel and sel[0].isdigit() and int(sel[0]) < len(cands) else None
        tv.bind("<<TreeviewSelect>>", lambda e: pick() and name.set(pick()["title"]))

        def save(run=False):
            c = pick()
            if not c:
                return
            mp = lb.save(c, name.get().strip() or c["title"])
            self.add_log(f"Built loop saved: {mp.title} ({len(mp.steps)} steps)")
            if run:
                d.destroy()
                here_ = s.state.room
                if here_ and not any(x.room == here_ for x in mp.steps):
                    s.bot.goto(mp.steps[0].room, then=mp)
                else:
                    s.bot.start_path(mp, loop=True)
            else:
                messagebox.showinfo("Build a loop", f"Saved '{mp.title}' with your paths.", parent=d)
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Build", style="Accent.TButton", command=build).pack(side="left")
        ttk.Label(b, text="   Name").pack(side="left")
        ttk.Entry(b, textvariable=name, width=40).pack(side="left", padx=4)
        ttk.Button(b, text="Save and run", style="Accent.TButton", command=lambda: save(True)).pack(side="right")
        ttk.Button(b, text="Save", command=save).pack(side="right", padx=6)
        if here:
            d.after(100, build)

    def edit_loop_dialog(self):
        """Mark rooms on the selected loop No attack / Don't rest (MegaMUD's step flags; 0.8.206, Dan)."""
        mp = self._selected_path()
        if not mp:
            return
        from .loopedit import edit_loop_dialog
        edit_loop_dialog(self, mp)

    def analyze_loop_dialog(self):
        """Room by room: what spawns, how much it could hurt you now, and how risky the loop is."""
        mp = self._selected_path()
        if not mp:
            return
        a = self.s.analyzer.analyze(mp)
        d = tk.Toplevel(self.root)
        d.title(f"Analyze: {mp.title} - MudPilot")
        d.configure(background=PANEL)
        d.geometry("1240x640")
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        if a.get("error"):
            ttk.Label(fr, text=a["error"]).pack(anchor="w")
            return
        st = self.s.state
        ttk.Label(fr, text=f"{mp.title}: {a['steps']} steps, {a['lairs']} lairs — ~{a['exp_lap']:,} exp a lap, "
                           f"~{a['exp_hr'] / 1000:,.0f}k/hr (rough)", style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text=f"For {self.s.settings.my_name or 'you'}: HP {st.max_hp or '?'}, AC {st.ac}/DR {st.dr}, "
                           f"party of {a['party']}. Risk = HP % you'd want walking in (safe ≤40 · moderate ≤70 · "
                           "risky ≤100 · deadly = more than you have). '?' = MME's numbers only, until it's fought there.",
                  style="Muted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(2, 8))
        cols = ("room", "spawn", "value", "dmg", "need", "risk", "notes")
        tv = ttk.Treeview(fr, columns=cols, show="tree headings", height=14)
        tv.heading("#0", text="Step / room")
        tv.column("#0", width=230)
        for c, t, w_ in (("room", "Map/room", 75), ("spawn", "Spawn", 360), ("value", "Exp", 65), ("dmg", "Could hurt", 85),
                         ("need", "Needs HP", 80), ("risk", "Risk", 85), ("notes", "Notes", 220)):
            tv.heading(c, text=t)
            tv.column(c, width=w_, anchor="e" if c in ("value", "dmg", "need") else "w")
        for tag, col in (("safe", "#5cff7a"), ("moderate", "#e6b450"), ("risky", "#ff9a3c"), ("deadly", "#ff5c5c")):
            tv.tag_configure(tag, foreground=col)
        tv.pack(fill="both", expand=True)
        for r in a["rows"]:
            tv.insert("", "end", text=f"{r['i']:>3}. {r['name']}", tags=(r["risk"].rstrip("?"),), values=(
                f"{r['room'][0]}/{r['room'][1]}", (f"up to {r['count']}× " + ", ".join(r["mobs"])) if r["lair"] else "",
                f"{r['value']:,}" if r["value"] else "", r["dmg"] or "", f"{r['need']:.0f}%" if r["need"] is not None else "",
                r["risk"] if r["lair"] else "", "; ".join(r["notes"])))
        tf = ttk.LabelFrame(fr, text="What it means", padding=8)
        tf.pack(fill="x", pady=(8, 0))
        for t in a["tips"]:
            ttk.Label(tf, text="• " + t, wraplength=1000, justify="left").pack(anchor="w")
        ttk.Button(fr, text="Close", command=d.destroy).pack(anchor="e", pady=(8, 0))

    def spots_dialog(self):
        """Where should this character / party hunt? Ranked areas across the map, built loops included."""
        s, sf = self.s, self.s.spots
        d = tk.Toplevel(self.root)
        d.title("Best spots - MudPilot")
        d.configure(background=PANEL)
        d.geometry("1100x620")
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        who = s.settings.my_name or "you"
        others = [n for n in s.state.party if n.lower() != who.lower()]
        head = ttk.Label(fr, text=f"Best spots for {who}" + (f" + {', '.join(others)}" if others else ""), style="Head.TLabel")
        head.pack(anchor="w")
        info = ttk.Label(fr, text="Every area you can walk to from here, scored for your HP, AC, spells and party; lairs "
                                  "that could kill you are left out. Exp/hr is calibrated against what your own loops "
                                  "really make (more laps = better numbers). It can't see other players camping a spot.",
                         style="Muted.TLabel", wraplength=1050, justify="left")
        info.pack(anchor="w", pady=(2, 6))
        prog = ttk.Label(fr, text="", style="Muted.TLabel")
        prog.pack(anchor="w")
        cols = ("eph", "proven", "risk", "dist", "steps", "lairs", "start", "mobs")
        tv = ttk.Treeview(fr, columns=cols, show="tree headings", height=14)
        tv.heading("#0", text="Area")
        tv.column("#0", width=170)
        for c, t, w_ in (("eph", "Est. exp/hr", 85), ("proven", "Your real", 75), ("risk", "Risk", 75), ("dist", "Steps away", 75),
                         ("steps", "Loop", 45), ("lairs", "Lairs", 40), ("start", "Starts at", 230), ("mobs", "Monsters", 420)):
            tv.heading(c, text=t)
            tv.column(c, width=w_, anchor="w" if c in ("risk", "mobs", "start") else "e")
        tv.pack(fill="both", expand=True, pady=(4, 0))
        # the selected area's monsters: you vs each one (combatcalc.quick); double-click → the full calculator
        ml = ttk.Label(fr, text="Monsters here — select an area · double-click a monster for the full fight",
                       style="Muted.TLabel")
        ml.pack(anchor="w", pady=(6, 0))
        mcols = ("exp", "hp", "kill", "hit", "die", "lose", "verdict")
        mt = ttk.Treeview(fr, columns=mcols, show="tree headings", height=5)
        mt.heading("#0", text="Monster")
        mt.column("#0", width=200)
        for c, t, w_ in (("exp", "Exp", 70), ("hp", "HP", 55), ("kill", "You kill it in", 150), ("hit", "It hits you/round", 115),
                         ("die", "It kills you in", 105), ("lose", "HP lost per kill", 105), ("verdict", "", 90)):
            mt.heading(c, text=t)
            mt.column(c, width=w_, anchor="e" if c in ("exp", "hp", "hit") else "w")
        for tag, col in (("deadly", "#ff6b6b"), ("hurts", "#e6b450"), ("easy", "#5cff7a")):
            mt.tag_configure(tag, foreground=col)
        mt.pack(fill="x", pady=(2, 0))
        res = {}

        def show_mobs(_e=None):
            from .combatcalc import quick
            mt.delete(*mt.get_children())
            o = pick()
            if not o:
                return
            names = list(o.get("mobs") or []) + [b.split(" (")[0] for b in (o["cand"].get("bosses") or [])]
            seen = set()
            for nm in names:
                mon = s.world.monster_names.get(nm.lower())
                if not mon or mon["num"] in seen:
                    continue
                seen.add(mon["num"])
                try:
                    q = quick(s, mon)
                except Exception as ex:
                    s.log(f"Best spots: couldn't size up {nm} ({ex})")
                    continue
                mt.insert("", "end", iid=str(mon["num"]), text=mon["name"], tags=(q["verdict"].split()[0],), values=(
                    f"{q['exp']:,}", q["hp"] or "?",
                    f"{q['kill']} round(s) ({q['how']}, {q['dmg']}/rd)" if q["kill"] else "—",
                    f"{q['hit']:.0f}" if q["hit"] else "?", f"{q['die']} round(s)" if q["die"] else "—",
                    f"{q['lose_pct']}%" if q["lose_pct"] is not None else "—", q["verdict"]))

        def open_mon(_e=None):
            sel = mt.selection()
            if sel and sel[0].isdigit():
                self.open_combatcalc(int(sel[0]))
        tv.bind("<<TreeviewSelect>>", show_mobs, add="+")
        mt.bind("<Double-1>", open_mon)

        def done(r):
            res.clear()
            res.update(r)
            tv.delete(*tv.get_children())
            if r.get("error"):
                prog.configure(text=r["error"])
                return
            cal = (f"calibrated on {r['calibrated_on']} of your loops (×{r['factor']:.2f})" if r["calibrated_on"]
                   else "not calibrated yet — run a loop for a few laps and these numbers get real")
            prog.configure(text=f"{r['reach']:,} rooms in reach · {r['lairs']:,} lairs you can take · {cal}")
            for i, o in enumerate(r["spots"]):
                c = o["cand"]
                sr = s.world.room(c["start"])
                start = f"{c['start'][0]}/{c['start'][1]} {sr.name if sr else ''}" + \
                    (f" — needs {', '.join(o['needs'])} (bought on the way)" if o.get("needs") else "")
                boss = c.get("bosses") or []
                mobs = ", ".join(m for m in o["mobs"] if not any(b.startswith(m + " (") for b in boss))
                if boss:
                    mobs += ("  ·  " if mobs else "") + "bosses: " + ", ".join(boss)
                tv.insert("", "end", iid=str(i), text=o["area"], values=(
                    f"{o['est_hr'] / 1000:,.0f}k", f"{o['proven'] / 1000:,.0f}k" if o["proven"] else "—", o["risk"],
                    o["dist"], c["steps"], len(c["lairs"]), start, mobs))
            if r["spots"]:
                tv.selection_set("0")

        def run():
            import threading
            sf.cancel = False
            prog.configure(text="Searching…")

            import queue
            q = queue.Queue()

            def work():
                # the search runs in the background; only the window's own thread touches the window
                from .spots import calm_thread
                try:
                    with calm_thread():
                        r = sf.find(progress=lambda dn, tot, msg: q.put(("msg", msg)))
                except Exception as ex:
                    import traceback
                    self.s.log(f"Best spots: {ex}")
                    traceback.print_exc()
                    r = {"error": f"The search hit a problem ({ex}) — it's in the Log tab"}
                q.put(("done", r))

            def pump():
                try:
                    while True:
                        kind, v = q.get_nowait()
                        if kind == "msg":
                            prog.configure(text=v)
                        else:
                            done(v)
                            return
                except queue.Empty:
                    pass
                except tk.TclError:
                    sf.cancel = True                  # window closed
                    return
                d.after(150, pump)
            threading.Thread(target=work, daemon=True).start()
            d.after(150, pump)

        def pick():
            sel = tv.selection()
            return res.get("spots", [])[int(sel[0])] if sel and sel[0].isdigit() else None

        def build_go(run_it=True):
            o = pick()
            if not o:
                return
            mp = s.loopbuilder.save(o["cand"], f"Built: {o['area']} {len(o['cand']['lairs'])} lairs")
            self.add_log(f"Built loop saved: {mp.title} ({len(mp.steps)} steps)")
            if run_it:
                d.destroy()
                here = s.state.room
                if here and not any(x.room == here for x in mp.steps):
                    s.bot.goto(mp.steps[0].room, then=mp)
                else:
                    s.bot.start_path(mp, loop=True)
            else:
                messagebox.showinfo("Best spots", f"Saved '{mp.title}' with your paths.", parent=d)

        def analyze():
            o = pick()
            if not o:
                return
            from .megamud_files import path_from_route
            mp = path_from_route(s.world, o["cand"]["start"], o["cand"]["route"], name=f"{o['area']} (built)")
            a = s.analyzer.analyze(mp)
            messagebox.showinfo(f"{o['area']}", "\n".join(f"{r['i']}. {r['name']}: {r['risk']}"
                                                          + (f" (needs {r['need']:.0f}% HP)" if r['need'] else "")
                                                          for r in a["rows"] if r["lair"])[:1800] + "\n\n" +
                                "\n".join(a["tips"]), parent=d)
        def best_case():
            """The kit from anything in the game that would make the most exp/hr here (bestcase.py)."""
            o = pick()
            if not o:
                return
            names = list(o.get("mobs") or []) + [x.split(" (")[0] for x in (o["cand"].get("bosses") or [])]
            mons = [s.world.monster_names.get(n.lower()) for n in names]
            bw = tk.Toplevel(d)
            bw.title(f"Best case: {o['area']} - MudPilot")
            bw.configure(background=PANEL)
            bw.geometry("1000x480")
            bf = ttk.Frame(bw, padding=12)
            bf.pack(fill="both", expand=True)
            ttk.Label(bf, text=f"Best case for {o['area']}", style="Head.TLabel").pack(anchor="w")
            note = ttk.Label(bf, text="Working it out…", style="Muted.TLabel", wraplength=960, justify="left")
            note.pack(anchor="w", pady=(2, 6))
            bt = ttk.Treeview(bf, columns=("now", "best", "from"), show="tree headings", height=14)
            bt.heading("#0", text="Slot")
            bt.column("#0", width=90)
            for c, t, w_ in (("now", "You wear", 200), ("best", "Best here", 220), ("from", "Where it comes from", 460)):
                bt.heading(c, text=t)
                bt.column(c, width=w_, anchor="w")
            bt.pack(fill="both", expand=True)
            import queue
            import threading
            q = queue.Queue()

            def work():
                from .bestcase import BestCase
                from .spots import calm_thread
                try:
                    with calm_thread():
                        r = BestCase(s, [m for m in mons if m], progress=lambda m: q.put(("msg", m))).run()
                except Exception as ex:
                    s.log(f"Best case: {ex}")
                    r = {"error": f"Couldn't work it out ({ex}) — it's in the Log tab"}
                q.put(("done", r))

            def show(r):
                if r.get("error"):
                    note.configure(text=r["error"])
                    return
                now, best = r["now"], r["best"]
                scale = (o["est_hr"] / now) if now else 1
                if not r["rows"]:
                    note.configure(text="What you wear is already about the best for this area (from anything in the game).")
                    return
                gain = (best / now - 1) * 100 if now else 0
                note.configure(text=(
                    f"Your gear: ~{o['est_hr'] * 1 / 1000:,.0f}k/hr here (Best spots' estimate). This kit: ~{best * scale / 1000:,.0f}k/hr "
                    f"(+{gain:.0f}%). Rough — from kill speed, damage taken and resting against this area's monsters; "
                    "worth it for the slots near the top. Stats with it: Spellcasting "
                    f"{r['stats_now']['spc']:.0f}→{r['stats_best']['spc']:.0f}, AC {r['stats_now']['ac']:.0f}→"
                    f"{r['stats_best']['ac']:.0f}, DR {r['stats_now']['dr']:.0f}→{r['stats_best']['dr']:.0f}, "
                    f"mana regen {r['stats_now']['mreg']:.0f}→{r['stats_best']['mreg']:.0f}."))
                for i, row in enumerate(r["rows"]):
                    bt.insert("", "end", iid=str(i), text=row["slot"], values=(row["now"], row["best"], row["from"]))

            def pump():
                try:
                    while True:
                        kind, v = q.get_nowait()
                        if kind == "msg":
                            note.configure(text=v)
                        else:
                            show(v)
                            return
                except queue.Empty:
                    pass
                except tk.TclError:
                    return
                bw.after(150, pump)
            threading.Thread(target=work, daemon=True).start()
            bw.after(150, pump)

        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Search again", command=run).pack(side="left")
        ttk.Button(b, text="Analyze", command=analyze).pack(side="left", padx=6)
        ttk.Button(b, text="Best case…", command=best_case).pack(side="left")
        ttk.Button(b, text="Build loop & go", style="Accent.TButton", command=build_go).pack(side="right")
        ttk.Button(b, text="Save loop", command=lambda: build_go(False)).pack(side="right", padx=6)
        kept = sf.kept()
        if kept:
            # opened again soon after: the last search straight away, no grinding (Dan, 2026-11-02)
            r, t = kept
            d.after(50, lambda: (done(r), prog.configure(
                text=prog.cget("text") + f" · from {max(1, int((time.time() - t) / 60))} min ago — Search again "
                                         "to refresh")))
        else:
            d.after(100, run)

    def loop_rotation_dialog(self):
        """Pick two or more loops to rotate between, so each refills while you work the other."""
        cfg, x = self.s.settings, self.s.bot.x
        loops = [mp for mp in self.s.paths if mp.is_loop]
        d = tk.Toplevel(self.root)
        d.title("Loop rotation - MudPilot")
        d.transient(self.root)
        d.configure(background=PANEL)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        on = tk.BooleanVar(value=bool(cfg.rotate_on))
        ttk.Checkbutton(fr, text="Rotate between these loops", variable=on).pack(anchor="w")
        ttk.Label(fr, text="Tick the loops (in the order to run them). At the end of a lap it walks to the next one.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 6))
        box = ttk.Frame(fr)
        box.pack(fill="both", expand=True)
        cv = tk.Canvas(box, height=240, background=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        chosen = [k.lower() for k in (cfg.rotate_loops or [])]
        order = []          # keys ticked, in the order you ticked them
        order[:] = [k for k in chosen if any(x.loop_key(mp) == k for mp in loops)]
        vars_ = {}
        nums = {}

        def renum():
            for k, lab in nums.items():
                lab.configure(text=f"{order.index(k) + 1}." if k in order else "")

        def toggle(k):
            if vars_[k].get():
                if k not in order:
                    order.append(k)
            elif k in order:
                order.remove(k)
            renum()
        for i, mp in enumerate(sorted(loops, key=lambda m: m.title.lower())):
            k = x.loop_key(mp)
            vars_[k] = tk.BooleanVar(value=k in order)
            sm = self.s.loopstats.summary(k)
            extra = f"   {sm['exp_hr'] / 1000:,.0f}k/hr" + (f", {sm['empty_lairs']:.0%} lairs empty"
                                                          if sm and sm["empty_lairs"] is not None else "") if sm else ""
            nums[k] = ttk.Label(inner, text="", width=3)
            nums[k].grid(row=i, column=0, sticky="e")
            ttk.Checkbutton(inner, text=f"{mp.title} ({len(mp.steps)} steps){extra}", variable=vars_[k],
                            command=lambda k=k: toggle(k)).grid(row=i, column=1, sticky="w")
        renum()
        if not loops:
            ttk.Label(inner, text="No loops loaded yet.", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        mode = tk.StringVar(value=cfg.rotate_mode or "empty")
        pct = tk.StringVar(value=str(cfg.rotate_empty_pct or 50))
        laps = tk.StringVar(value=str(cfg.rotate_laps or 3))
        m1 = ttk.Frame(fr)
        m1.pack(anchor="w", pady=(8, 0))
        ttk.Radiobutton(m1, text="Move on when at least", value="empty", variable=mode).pack(side="left")
        ttk.Spinbox(m1, from_=10, to=100, width=4, textvariable=pct).pack(side="left", padx=4)
        ttk.Label(m1, text="% of a lap's lairs were empty").pack(side="left")
        m2 = ttk.Frame(fr)
        m2.pack(anchor="w")
        ttk.Radiobutton(m2, text="Move on every", value="laps", variable=mode).pack(side="left")
        ttk.Spinbox(m2, from_=1, to=50, width=4, textvariable=laps).pack(side="left", padx=4)
        ttk.Label(m2, text="laps").pack(side="left")
        ttk.Label(fr, text="Exp/hr keeps counting across the switch. Start any one of them as usual.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        def save():
            try:
                cfg.rotate_empty_pct = max(10, min(100, int(pct.get())))
                cfg.rotate_laps = max(1, int(laps.get()))
            except ValueError:
                pass
            cfg.rotate_on, cfg.rotate_mode, cfg.rotate_loops = on.get() and len(order) >= 2, mode.get(), list(order)
            cfg.save()
            if on.get() and len(order) < 2:
                messagebox.showinfo("Loop rotation", "Tick at least two loops to rotate between.", parent=d)
                return
            d.destroy()
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(10, 0))
        ttk.Button(b, text="Save", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="right", padx=6)

    def loop_stash_dialog(self):
        """Each loop can have its own stash room, so a loop across the realm never walks 300 rooms to stash."""
        mp = self._selected_path()
        if not mp:
            return
        x = self.s.bot.x
        key = x.loop_key(mp)
        cfg = self.s.settings
        d = tk.Toplevel(self.root)
        d.title("Stash room for this loop")
        d.transient(self.root)
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=mp.title, style="Head.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        v = tk.StringVar(value=(cfg.loop_stash or {}).get(key, ""))
        ttk.Label(fr, text="Stash room (map/room)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(fr, textvariable=v, width=12).grid(row=1, column=1, sticky="w", padx=6)
        name = ttk.Label(fr, text="", style="Muted.TLabel")
        name.grid(row=2, column=0, columnspan=3, sticky="w")

        def show(*a):
            k = room_text(v.get())
            r = self.s.world.room(k) if k else None
            on = r and any(stp.room == r.key for stp in mp.steps)
            name.configure(text=(f"{r.name}" + (" — on the loop, stashes as it passes" if on else "")) if r else
                           ("blank = use the Loot tab's default stash" if not v.get().strip() else
                            f"no room {k[0]}/{k[1]} in the map data" if k else
                            "can't read that — type map/room, e.g. 14/6534"))
        v.trace_add("write", show)
        show()

        def here():
            if self.s.state.room:
                v.set(f"{self.s.state.room[0]}/{self.s.state.room[1]}")
        ttk.Button(fr, text="Use the room I'm in", command=here).grid(row=1, column=2, padx=4)

        def ok():
            ls = dict(cfg.loop_stash or {})
            if v.get().strip():
                k = room_text(v.get())
                if not k or not self.s.world.room(k):
                    # 0.8.200: '14\6534' used to be saved without a word and the loop never stashed
                    messagebox.showwarning("Stash room", (f"There's no room {k[0]}/{k[1]} in the map data." if k else
                                           f"'{v.get().strip()}' isn't a room number MudPilot can read.") +
                                           "\n\nType it as map/room, e.g. 14/6534, or stand there and click "
                                           "'Use the room I'm in'.", parent=d)
                    return
                v.set(f"{k[0]}/{k[1]}")
                ls[key] = v.get()
            else:
                ls.pop(key, None)
            cfg.loop_stash = ls
            cfg.save()
            self.add_log(f"Stash for '{mp.title}': {v.get().strip() or 'default'}")
            d.destroy()
        b = ttk.Frame(fr)
        b.grid(row=3, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")

    def delete_path(self):
        mp = self._selected_path()
        if mp and messagebox.askyesno("Delete path", f"Remove '{mp.title}' from MudPilot?"):
            try:
                os.remove(mp.filename)
            except OSError:
                pass
            self.s.paths.remove(mp)
            self.refresh_paths()

    def search_rooms(self):
        q = self.goto_var.get().strip()
        self.results.delete(0, "end")
        self._result_keys = []
        if not q or not self.s.world.loaded:
            return
        w = self.s.world
        if len(q) >= 3:                      # a monster's name finds where it is (Dan: 'sleazy shopkeeper')
            for m in w.search_monsters(q, limit=10):
                for k, how in w.monster_rooms(m["num"]):
                    r = w.room(k)
                    self.results.insert("end", f"{k[0]:>3}/{k[1]:<6} {m['name']} — {r.name if r else ''}"
                                        + ("" if how == "stands here" else f" ({how})"))
                    self._result_keys.append(k)
        for r in w.search_rooms(q):
            self.results.insert("end", f"{r.key[0]:>3}/{r.key[1]:<6} {r.name}")
            self._result_keys.append(r.key)
        if len(self._result_keys) == 1:
            self.results.selection_set(0)

    def goto_selected(self):
        sel = self.results.curselection()
        if not sel:
            self.search_rooms()
            sel = self.results.curselection()
            if not sel:
                return
        self.goto_room(self._result_keys[sel[0]])

    def goto_room(self, key):
        pb = self.windows.get("Path builder") if hasattr(self, "windows") else None
        if getattr(self, "_map_pick", None):
            try:
                live = pb is not None and pb.winfo_exists() and pb.winfo_viewable()
            except tk.TclError:
                live = False
            if live:
                self._map_pick(key)      # Path builder is picking rooms on the map
                return
            self._map_pick = None        # left over from a closed Path builder — don't let it eat the Go
        r = self.s.world.room(tuple(key))
        self.add_log(f"Go to {key[0]}/{key[1]} {r.name if r else ''}")
        from .gotodlg import recent_add
        recent_add(self.s, "room", tuple(key))
        self.plan_route(lambda ask: self.s.bot.goto(tuple(key), ask=ask), f"to {r.name if r else 'there'}")

    PLANNING = "Calculating route — one moment please…"

    def plan_route(self, fn, where=""):
        """Work a route out without freezing the window (Dan, 2026-10-30: Goto went white — 'Not Responding' —
        for 15 s while it thought): 'Calculating route — one moment please…' until it's done."""
        from . import bgplan
        if getattr(self.s.bot, "_planning", False):
            self.add_log("Still working out the last route — one moment")
            return
        if getattr(self.s.settings, "hands_off", False):
            # your own Go to (the Goto button / dialog, the path's or loop's start): you're saying 'go'
            self._var("hands_off").set(False)
            self.s.hands_on("You started a Go to")
        rc = self.s.remote
        hold = rc.holding()
        if hold:
            # a member's @wait holds the walk: say so now, not 90 s of nothing (Dan, 2026-11-10: Revolution's
            # '@wait (confused)' never got its @ok and the pharaoh Go to just sat — "I couldn't tell")
            left = max(0, int(rc.HOLD_SECS - (time.time() - rc.holds.get(hold, time.time()))))
            self.add_log(f"Your Go to waits on {rc.hold_text(hold)} — it goes when they send @ok "
                         f"(at most {left} s more). NoWait, or '.@ok', to go now")
        try:
            note = tk.Toplevel(self.root)
            note.overrideredirect(True)
            note.attributes("-topmost", True)
            note.configure(background=PANEL)
            ttk.Label(note, text=f"Calculating route {where} — one moment please…".replace("  ", " "),
                      padding=(18, 12)).pack()
            note.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - note.winfo_reqwidth()) // 2
            y = self.root.winfo_rooty() + self.root.winfo_height() // 3
            note.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            note = None
        old_status = self.s.bot.status
        self.s.bot.status = self.PLANNING

        def done(ok, err):
            try:
                if note is not None:
                    note.destroy()
            except tk.TclError:
                pass
            if self.s.bot.status == self.PLANNING:
                self.s.bot.status = old_status
            if err is not None:
                import traceback
                from . import report as _rep
                _rep.ERRORS.append((time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "".join(traceback.format_exception(type(err), err, err.__traceback__))))
                messagebox.showerror("Go to", f"Something went wrong planning the route: {err}\n\n"
                                              "Help → Report a problem sends me the details.", parent=self.root)
                return
            if ok:
                self._last_route = self.s.bot.path
        bgplan.plan(self.s, fn, done, ask=self.ask_route, after=self.root.after)

    ASK_ROUTE_SECS = 10

    def ask_route(self, short, scenic, area, kind="area"):
        """Go to went through an avoided area (Negative Power Plane by default): ask which way. Nobody answers in
        10 s (Dan: you're away from the keys) → the safe way round, as if you'd said No — never through the area.
        kind "door" (0.8.201, Dan): a door nobody in the party can open — try anyway? No is the default."""
        if kind == "door":
            return self._timed_yesno(f"{area} — nobody in the party can open it.\n\nTry anyway? ({short} steps)",
                                     "No answer → going round it (or not going)")
        if kind == "hurt":
            # 0.8.224 (Dan): a run of rooms that hurts past your limit — go anyway? No is the default
            return self._timed_yesno(f"{area}.\n\nGo anyway?", "No answer → not going")
        if kind == "hurtpick":
            # 0.8.224.2 (Dan): the short way hurts, a safe way round isn't much longer — pick
            return self._timed_yesno(f"The short way goes through {area}.\n\nYes = the short way through them "
                                     f"({short} steps)\nNo = the safe way round ({scenic} steps, {scenic - short} more)",
                                     "No answer → the safe way round")
        if scenic is None:
            return self._timed_yesno(f"The only way there goes through {area} ({short} steps).\n\nGo through it?",
                                     "No answer → not going")
        return self._timed_yesno(f"The short way goes through {area}.\n\nYes = take {area} ({short} steps)\n"
                                 f"No = the safe way round ({scenic} steps, {scenic - short} more)",
                                 "No answer → the safe way round")

    def _timed_yesno(self, text, timeout_note, secs=None) -> bool:
        """Yes / No that answers No by itself after a few seconds."""
        secs = int(secs or self.ASK_ROUTE_SECS)
        d = tk.Toplevel(self.root)
        d.title("MudPilot")
        d.configure(background=PANEL)
        d.transient(self.root)
        d.attributes("-topmost", True)
        fr = ttk.Frame(d, padding=14)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=text, justify="left", wraplength=420).pack(anchor="w")
        left = ttk.Label(fr, text="", style="Muted.TLabel")
        left.pack(anchor="w", pady=(8, 0))
        res = {"v": False}

        def done(v):
            res["v"] = v
            d.destroy()
        b = ttk.Frame(fr)
        b.pack(fill="x", pady=(10, 0))
        ttk.Button(b, text="Yes", command=lambda: done(True)).pack(side="right", padx=(6, 0))
        ttk.Button(b, text="No", style="Accent.TButton", command=lambda: done(False)).pack(side="right")
        n = {"t": secs}

        def tick():
            if not d.winfo_exists():
                return
            if n["t"] <= 0:
                self.add_log(f"Route prompt: no answer in {secs} s — {timeout_note.split('→ ')[-1]}")
                done(False)
                return
            left.configure(text=f"{timeout_note} in {n['t']} s")
            n["t"] -= 1
            d.after(1000, tick)
        tick()
        d.grab_set()
        d.wait_window()
        return res["v"]

    def save_route(self):
        mp = self._last_route
        if not mp:
            messagebox.showinfo("MudPilot", "Use Go to room first; the route it walks can be saved as a MegaMUD path.")
            return
        name = simpledialog.askstring("Save path", "File name (saved in MudPilot\\data\\paths):",
                                      initialvalue=f"{mp.steps[0].hash[:4]}{mp.steps[-1].hash[:4]}.mp")
        if name:
            if not name.lower().endswith(".mp"):
                name += ".mp"
            self.s.save_path(mp, name)
            self.refresh_paths()

    def open_character(self):
        """File → Open character… (Dan, 2026-11-12: "add an open character in file and have it clearly list the only
        characters that exist"). Every character on this PC, which one this window is, which are open already (those
        can't be opened again: two MudPilots on one character log in over each other). A pick opens it in its own
        MudPilot window, through the launcher like a normal start."""
        import subprocess
        from . import launcher
        try:
            chars = launcher.character_folders()
        except OSError as ex:
            messagebox.showerror("MudPilot", f"Couldn't list the characters: {ex}", parent=self.root)
            return
        mine = os.path.normcase(os.path.abspath(config.DATA_DIR))
        win = tk.Toplevel(self.root)
        win.title("Open character")
        win.resizable(False, False)
        win.transient(self.root)
        fr = ttk.Frame(win, padding=14)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Characters on this PC ({len(chars)}):").pack(anchor="w", pady=(0, 8))

        def go(name, who):
            win.destroy()
            try:
                subprocess.Popen([launcher.EXE, "-m", "mudpilot.launcher", "--data", name], cwd=launcher.ROOT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.s.log(f"Opening {who} in its own MudPilot window")
            except OSError as ex:
                messagebox.showerror("MudPilot", f"Couldn't open {who}: {ex}", parent=self.root)
        for name, folder, who in chars:
            who = who or "(no character yet)"
            label = f"{who}   ({os.path.basename(folder)})"
            if os.path.normcase(os.path.abspath(folder)) == mine:
                ttk.Button(fr, text=label + " — this window", state="disabled").pack(fill="x", pady=2)
            elif launcher.folder_in_use(folder):
                ttk.Button(fr, text=label + " — already open", state="disabled").pack(fill="x", pady=2)
            else:
                ttk.Button(fr, text=label, command=lambda n=name, w=who: go(n, w)).pack(fill="x", pady=2)
        ttk.Label(fr, text="A new character: close MudPilot and open it again → New character…",
                  foreground="#8a96a3").pack(anchor="w", pady=(8, 0))
        ttk.Button(fr, text="Close", command=win.destroy).pack(fill="x", pady=(8, 0))

    def _open(self, path):
        os.makedirs(path, exist_ok=True)
        config.open_path(path)

    def quit(self):
        self._quitting = True
        self._remember_layout()
        try:
            g = dict(self.s.settings.window_geom or {})
            if self.root.state() == "zoomed":
                g["main_zoomed"] = True
            else:
                g["main"], g["main_zoomed"] = self.root.geometry(), False
            self.s.settings.window_geom = g
        except tk.TclError:
            pass
        self.s.settings.save()
        self.s.history.save()
        self.s.lairclock.save(force=True)
        try:
            self.s.sync.sync_now()
        except Exception:
            pass
        self.s.disconnect()
        self.root.destroy()

    # ---------------------------------------------------------- updates (0.8.200)
    def check_updates(self, quiet=True):
        """Ask GitHub for a newer release on a thread; a bar under the menu offers What's new / Update / Skip.
        quiet: at start — say nothing when up to date, offline, or the version was skipped."""
        import threading
        from . import updater

        def work():
            try:
                info = updater.check()
            except Exception as e:
                if not quiet:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Check for updates", f"Couldn't reach GitHub to check ({e.__class__.__name__}).", parent=self.root))
                return
            if not info:
                if not quiet:
                    from . import __version__
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Check for updates", f"You're on the newest MudPilot ({__version__}).", parent=self.root))
                return
            if quiet and info["version"] == (self.s.settings.update_skip or ""):
                return
            self.root.after(0, lambda: self._update_bar(info))
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _update_bar(self, info):
        from . import __version__, updater
        old = getattr(self, "_upd_bar", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        bar = tk.Frame(self.root, background="#2b4a7a")
        self._upd_bar = bar
        lbl = tk.Label(bar, text=f"MudPilot {info['version']} is out — you have {__version__}.", background="#2b4a7a",
                       foreground="#ffffff", font=("Segoe UI", 10, "bold"))
        lbl.pack(side="left", padx=(10, 12), pady=4)

        def whats_new():
            d = tk.Toplevel(self.root)
            d.title(f"What's new in MudPilot {info['version']}")
            d.geometry("760x520")
            tx = tk.Text(d, wrap="word", background=PANEL, foreground="#e6e6e6", relief="flat", padx=10, pady=8)
            tx.pack(fill="both", expand=True)
            tx.insert("1.0", info["notes"] or "No release notes.")
            tx.configure(state="disabled")
            b = ttk.Frame(d, padding=6)
            b.pack(fill="x")
            if info.get("url"):
                import webbrowser
                ttk.Button(b, text="Open on GitHub", command=lambda: webbrowser.open(info["url"])).pack(side="left")
            ttk.Button(b, text="Close", command=d.destroy).pack(side="right")

        def skip():
            self.s.settings.update_skip = info["version"]
            self.s.settings.save()
            bar.destroy()

        def update():
            if not (updater.frozen() and info.get("asset")):
                messagebox.showinfo("Update", "This copy runs from source (MudPilot.bat), so it can't update itself.\n\n"
                                    "Download the new version from GitHub and unzip it over this one.", parent=self.root)
                if info.get("url"):
                    import webbrowser
                    webbrowser.open(info["url"])
                return
            ub.configure(state="disabled", text="Downloading…")

            def work():
                try:
                    path = updater.download(info, progress=lambda g, t: self.root.after(
                        0, lambda: ub.configure(text=f"Downloading… {g * 100 // t}%" if t else "Downloading…")))
                except Exception as e:
                    self.root.after(0, lambda: (ub.configure(state="normal", text="Update"),
                                                messagebox.showerror("Update", f"The download didn't work: {e}",
                                                                     parent=self.root)))
                    return
                self.root.after(0, lambda: done(path))
            import threading
            threading.Thread(target=work, daemon=True, name="update-download").start()

        def done(path):
            self.add_log(f"Downloaded MudPilot {info['version']} ({os.path.basename(path)})")
            if updater.under_launcher():
                if messagebox.askyesno("Update", f"MudPilot {info['version']} is downloaded.\n\nRestart now to install "
                                       "it? (MudPilot logs back in and carries on.)", parent=self.root):
                    self._restart_quit()
                    return
                lbl.configure(text=f"MudPilot {info['version']} installs the next time MudPilot opens.")
            else:
                lbl.configure(text=f"MudPilot {info['version']} is downloaded — close MudPilot and open it again to "
                                   "install it.")
            ub.destroy()

        for text, fn in (("What's new", whats_new), ("Update", update), ("Skip this version", skip)):
            b_ = tk.Button(bar, text=text, command=fn, relief="flat", background="#3d66a8", foreground="#ffffff",
                           activebackground="#4f7cc4", activeforeground="#ffffff", padx=10)
            b_.pack(side="left", padx=3, pady=3)
            if text == "Update":
                ub = b_
        tk.Button(bar, text="✕", command=bar.destroy, relief="flat", background="#2b4a7a", foreground="#ffffff",
                  activebackground="#3d66a8", bd=0).pack(side="right", padx=8)
        try:
            bar.pack(fill="x", before=self.toolbar if self.toolbar.winfo_ismapped() else self._info_row)
        except (tk.TclError, AttributeError):
            bar.pack(fill="x", side="top")

    def _restart_quit(self):
        """The control folder asked for a restart: close normally, and tell the launcher to reopen us."""
        from .control import RESTART_EXIT
        self.exit_code = RESTART_EXIT
        self.quit()


class ImportCharDialog(tk.Toplevel):
    def __init__(self, master, app, path):
        from .megamud_profile import read_ini, plan_import
        super().__init__(master)
        self.app = app
        self.title("Import MegaMUD character")
        self.configure(background=PANEL)
        rows = read_ini(path)
        self.maps, self.extra = plan_import(rows)
        name = next((v for _s, k, v in rows if k.lower() in ("name", "charname", "character")), None) \
            or os.path.splitext(os.path.basename(path))[0]
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"{os.path.basename(path)} — {len(rows)} settings read, {len(self.maps)} recognised. "
                          "Click a row to include/exclude it.", style="Muted.TLabel").pack(anchor="w")
        top = ttk.Frame(f)
        top.pack(fill="x", pady=8)
        ttk.Label(top, text="Save as profile").pack(side="left")
        self.name = tk.StringVar(value=name)
        ttk.Entry(top, textvariable=self.name, width=22).pack(side="left", padx=6)
        self.tree = ttk.Treeview(f, columns=("use", "key", "val", "to", "new"), show="headings", height=14)
        for c, w, t in (("use", 40, "Use"), ("key", 170, "MegaMUD key"), ("val", 90, "Value"),
                        ("to", 140, "MudPilot setting"), ("new", 160, "Becomes")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True)
        self.use = set(range(len(self.maps)))
        for i, (sec, key, val, setting, nv, kind) in enumerate(self.maps):
            shown = nv.get("cast") if isinstance(nv, dict) else (", ".join(nv) if isinstance(nv, list) else nv)
            self.tree.insert("", "end", iid=str(i), values=("✓", f"{sec}/{key}" if sec else key, val, setting, shown))
        self.tree.bind("<ButtonRelease-1>", self.toggle)
        if self.extra:
            ttk.Label(f, text=f"{len(self.extra)} other setting(s) not recognised — kept with the profile: "
                      + ", ".join(list(self.extra)[:8]) + ("…" if len(self.extra) > 8 else ""),
                      style="Muted.TLabel", wraplength=600).pack(anchor="w", pady=6)
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Import", style="Accent.TButton", command=self.apply).pack(side="right", padx=6)
        self.transient(master)
        self.grab_set()

    def toggle(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        i = int(iid)
        if i in self.use:
            self.use.discard(i)
        else:
            self.use.add(i)
        self.tree.set(iid, "use", "✓" if i in self.use else "")

    def apply(self):
        from .megamud_profile import apply_import
        name = self.name.get().strip() or "Imported"
        cur = self.app.s.settings
        cur.save()
        new = config.Settings()
        new.host, new.port, new.triggers, new.username = cur.host, cur.port, cur.triggers, cur.username
        new.board = cur.board
        new.profile = name
        apply_import(new, self.maps, self.extra, self.use)
        new.save()
        self.destroy()
        self.app.switch_profile(name, save_current=False)
        messagebox.showinfo("MudPilot", f"Profile '{name}' created from MegaMUD settings.\n\n"
                                        "Check the Combat, Spells and Bless tabs to fine-tune it.")


class EventDialog(tk.Toplevel):
    def __init__(self, master, app, index):
        from .events import KINDS_WHEN, KINDS_DO
        super().__init__(master)
        self.app, self.index = app, index
        ev = dict(app.s.settings.events[index]) if index is not None else {
            "name": "", "enabled": True, "when": "timer", "every": 180, "do": "hunt", "not_fighting": True,
            "min_hp": 80, "cooldown": 5}
        self.title("Event")
        self.configure(background=PANEL)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=14)
        f.pack()
        w = app.s.world
        bosses = sorted({m["name"] for m in w.monsters.values() if m.get("boss") and m.get("in_game")})
        paths = sorted(p.title for p in app.s.paths)
        self.when_lbl = {v: k for k, v in KINDS_WHEN.items()}
        self.do_lbl = {v: k for k, v in KINDS_DO.items()}
        self.v = {k: tk.StringVar(value=str(ev.get(k, "") if ev.get(k) is not None else ""))
                  for k in ("name", "every", "match", "boss", "room", "path", "min_hp", "cooldown")}
        if ev.get("when") == "boss" and not self.v["boss"].get():
            self.v["boss"].set(ev.get("boss", ""))
        self.when = tk.StringVar(value=KINDS_WHEN.get(ev.get("when", "timer")))
        self.do = tk.StringVar(value=KINDS_DO.get(ev.get("do", "hunt")))
        self.not_fighting = tk.BooleanVar(value=ev.get("not_fighting", True))
        self._rows = []

        def row(label, make, hint=""):
            fr = ttk.Frame(f)
            fr.grid(row=len(self._rows), column=0, sticky="w", pady=3)
            ttk.Label(fr, text=label, width=20).pack(side="left")
            wdg = make(fr)
            wdg.pack(side="left")
            if hint:
                ttk.Label(fr, text=hint, style="Muted.TLabel").pack(side="left", padx=8)
            self._rows.append(fr)
            return fr

        row("Name", lambda p: ttk.Entry(p, textvariable=self.v["name"], width=26), "e.g. Murderer run")
        row("When", lambda p: ttk.Combobox(p, textvariable=self.when, values=list(KINDS_WHEN.values()), width=24,
                                           state="readonly"))
        self.w_every = row("   every (minutes)", lambda p: ttk.Spinbox(p, from_=1, to=10000, textvariable=self.v["every"],
                                                                      width=8), "180 = every 3 hours")
        self.w_match = row("   text", lambda p: ttk.Entry(p, textvariable=self.v["match"], width=26), "plain text, or /regex/")
        self.w_bossw = row("   boss", lambda p: ttk.Combobox(p, textvariable=self.v["boss"], values=bosses, width=24),
                           "fires when its respawn timer is up")
        row("Do", lambda p: ttk.Combobox(p, textvariable=self.do, values=list(KINDS_DO.values()), width=24,
                                         state="readonly"))
        self.w_boss = row("   boss", lambda p: ttk.Combobox(p, textvariable=self.v["boss"], values=bosses, width=24),
                          "walks to its spawn room(s)")

        def mk_cmds(p):
            self.cmds = tk.Text(p, width=30, height=4, background="#0f1318", foreground=TEXT, insertbackground=TEXT,
                                borderwidth=0, font=("Consolas", 10))
            self.cmds.insert("1.0", ev.get("commands", ""))
            return self.cmds
        self.w_cmds = row("   commands", mk_cmds, "one per line; 'wait 3' pauses")
        self.w_room = row("   room", lambda p: ttk.Entry(p, textvariable=self.v["room"], width=12), "map/room, e.g. 3/606")
        self.w_path = row("   path / loop", lambda p: ttk.Combobox(p, textvariable=self.v["path"], values=paths, width=24))
        row("Start only when HP ≥", lambda p: ttk.Spinbox(p, from_=0, to=100, textvariable=self.v["min_hp"], width=6),
            "% — rests first (0 = don't wait)")
        row("Cooldown (minutes)", lambda p: ttk.Spinbox(p, from_=0, to=10000, textvariable=self.v["cooldown"], width=6),
            "text / boss events")
        row("", lambda p: ttk.Checkbutton(p, text="Don't start in the middle of a fight", variable=self.not_fighting))
        bb = ttk.Frame(f)
        bb.grid(row=len(self._rows), column=0, sticky="e", pady=(8, 0))
        ttk.Button(bb, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bb, text="Save", style="Accent.TButton", command=self.save).pack(side="right", padx=6)
        self.when.trace_add("write", lambda *a: self.show())
        self.do.trace_add("write", lambda *a: self.show())
        self.show()
        self.transient(master)
        self.grab_set()

    def show(self):
        wk, dk = self.when_lbl[self.when.get()], self.do_lbl[self.do.get()]
        vis = {self.w_every: wk == "timer", self.w_match: wk == "text", self.w_bossw: wk == "boss",
               self.w_boss: dk == "hunt" and wk != "boss", self.w_cmds: dk == "send",
               self.w_room: dk == "goto", self.w_path: dk == "path"}
        for fr, on in vis.items():
            if on:
                fr.grid()
            else:
                fr.grid_remove()

    def save(self):
        wk, dk = self.when_lbl[self.when.get()], self.do_lbl[self.do.get()]
        ev = {"name": self.v["name"].get().strip(), "when": wk, "do": dk,
              "not_fighting": self.not_fighting.get()}
        try:
            ev["min_hp"] = int(self.v["min_hp"].get() or 0)
            ev["cooldown"] = float(self.v["cooldown"].get() or 0)
            if wk == "timer":
                ev["every"] = float(self.v["every"].get())
                if ev["every"] <= 0:
                    raise ValueError
        except ValueError:
            messagebox.showinfo("Event", "Minutes, HP and cooldown must be numbers.", parent=self)
            return
        if wk == "text":
            ev["match"] = self.v["match"].get().strip()
            if not ev["match"]:
                messagebox.showinfo("Event", "Enter the text to watch for.", parent=self)
                return
        if wk == "boss" or dk == "hunt":
            ev["boss"] = self.v["boss"].get().strip()
            mon = self.app.s.world.boss_named(ev["boss"])
            if not mon:
                messagebox.showinfo("Event", "Pick a boss from the list (it has to be in this board's MME data).",
                                    parent=self)
                return
            if dk == "hunt" and not mon.get("spawn_rooms"):
                messagebox.showinfo("Event", f"MME has no spawn room for {mon['name']}, so it can't be hunted.",
                                    parent=self)
                return
        if dk == "send":
            ev["commands"] = self.cmds.get("1.0", "end").strip()
        elif dk == "goto":
            ev["room"] = self.v["room"].get().strip()
        elif dk == "path":
            ev["path"] = self.v["path"].get().strip()
        if not ev["name"]:
            from .events import describe
            ev["name"] = describe(ev)[1][:24]
        old = self.app.s.settings.events[self.index] if self.index is not None else {}
        ev["enabled"] = old.get("enabled", True)
        ev["last_run"] = old.get("last_run", 0)
        if self.index is None:
            self.app.s.settings.events.append(ev)
        else:
            self.app.s.settings.events[self.index] = ev
        self.app.s.settings.save()
        self.app.refresh_events()
        self.destroy()


class BoardDialog(tk.Toplevel):
    """Ask which board an MME file belongs to (existing or new)."""

    @classmethod
    def ask(cls, master, current, boards, profile):
        d = cls(master, current, boards, profile)
        master.wait_window(d)
        return d.result

    def __init__(self, master, current, boards, profile):
        super().__init__(master)
        self.result = None
        self.title("Which board?")
        self.configure(background=PANEL)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=16)
        f.pack()
        ttk.Label(f, text="Which BBS is this MME file for?").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text=f"Pick an existing board or type a new name. '{profile}' will be set to play "
                          "on it; other characters on that board share it.",
                  style="Muted.TLabel", wraplength=340).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        self.v = tk.StringVar(value=current)
        cb = ttk.Combobox(f, textvariable=self.v, values=boards, width=28)
        cb.grid(row=2, column=0, columnspan=2, sticky="we")
        cb.focus_set()
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Import", style="Accent.TButton", command=self.ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self.ok())
        self.transient(master)
        self.grab_set()

    def ok(self):
        name = config._safe(self.v.get().strip())
        if name:
            self.result = name
            self.destroy()


class BuffDialog(tk.Toplevel):
    FIELDS = (("name", "Name", "e.g. Flux"), ("cast", "Cast command", "e.g. flux"),
              ("check_cmd", "Check command", "e.g. abil 145 (blank = use the general abil)"),
              ("ability", "Ability", "number or name, e.g. 145 or ManaRegen"),
              ("value", "Target value", "e.g. 100 (180, -30 etc.)"),
              ("check_secs", "Check every (sec)", "blank = general setting"),
              ("every", "Or recast every (sec)", "blank = spell duration − margin (Bless tab)"),
              ("on_msg", "Start text", "learned on first cast; e.g. 'You feel protected'"),
              ("off_msg", "Wear-off text", "learned when it wears off; e.g. 'flux fades'"),
              ("max_rerolls", "Max casts in a row", "stop chasing a roll after this many (0 = no limit)"),
              ("min_mana_pct", "Don't cast below MA %", "keeps mana for fighting"),
              ("equip_cmd", "Equip first", "item spell, e.g. eq emerald-tipped crozier (cast: use crozier)"),
              ("unequip_cmd", "…then", "blank = eq your weapon again"))

    def __init__(self, master, app, index, preset=None):
        super().__init__(master)
        self.app, self.index = app, index
        bf = dict(app.s.settings.buffs[index]) if index is not None else \
            {"op": ">=", "enabled": True, "max_rerolls": 8, "min_mana_pct": 25}
        if preset:
            from .spells import MANA_REGEN_PRESETS
            pr = MANA_REGEN_PRESETS[preset]
            bf.update({"name": pr["name"], "cast": preset, "check_cmd": "abil 145", "ability": "145",
                       "source": "spells", "op": ">=", "value": pr["target"], "while_resting": True,
                       "min_mana_pct": 5})       # mana regen is cast when mana is low — that's the point
        self.title("Bless spell")
        self.configure(background=PANEL)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=14)
        f.pack()
        self.v = {}
        for r, (k, label, hint) in enumerate(self.FIELDS):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            self.v[k] = tk.StringVar(value="" if bf.get(k) in (None, 0) and k != "value" else str(bf.get(k, "")))
            ttk.Entry(f, textvariable=self.v[k], width=22).grid(row=r, column=1, pady=3, sticky="w")
            ttk.Label(f, text=hint, style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=8)
        r = len(self.FIELDS)
        self.range_lbl = ttk.Label(f, text="", foreground=ACCENT)
        self.range_lbl.grid(row=r, column=0, columnspan=3, sticky="w", pady=(4, 2))
        r += 1
        for k in ("cast", "value"):
            self.v[k].trace_add("write", lambda *a: self._show_range())
        ttk.Label(f, text="Read from").grid(row=r, column=0, sticky="w", pady=3)
        self.source = tk.StringVar(value=bf.get("source", "spells"))
        ttk.Combobox(f, textvariable=self.source, values=("spells", "worn", "granted", "race", "class", "total"),
                     width=10, state="readonly").grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="spells = Spell effects / 'spells:' line", style="Muted.TLabel").grid(
            row=r, column=2, sticky="w", padx=8)
        r += 1
        ttk.Label(f, text="Keep value").grid(row=r, column=0, sticky="w", pady=3)
        self.op = tk.StringVar(value=bf.get("op", ">="))
        ttk.Combobox(f, textvariable=self.op, values=(">=", "<="), width=5, state="readonly").grid(
            row=r, column=1, sticky="w")
        self.in_combat = tk.BooleanVar(value=bool(bf.get("in_combat")))
        ttk.Checkbutton(f, text="Allowed during combat", variable=self.in_combat).grid(
            row=r + 1, column=0, sticky="w", pady=4)
        self.while_resting = tk.BooleanVar(value=bool(bf.get("while_resting")))
        ttk.Checkbutton(f, text="Also while resting / meditating", variable=self.while_resting).grid(
            row=r + 1, column=1, columnspan=2, sticky="w", pady=4)
        b = ttk.Frame(f)
        b.grid(row=r + 2, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Save", style="Accent.TButton", command=self.save).pack(side="right", padx=6)
        self._show_range()
        self.transient(master)
        self.grab_set()

    def _spell_range(self):
        from .spells import buff_range
        sp = self.app.s.spellbook.find(self.v["cast"].get().strip()) if self.app.s.world.loaded else None
        if not sp or not any(a == 145 for a, _v in sp.get("abils", [])):
            return None, None
        lvl = self.app.s.settings.char_level
        return sp, buff_range(sp, lvl)

    def _show_range(self):
        sp, rng = self._spell_range()
        if not sp:
            self.range_lbl.configure(text="")
            return
        lvl = self.app.s.settings.char_level
        txt = f"{sp['Name']} rolls {rng[0]:+d} to {rng[1]:+d}" + (f" at level {lvl}" if lvl else " at max level")
        try:
            want = int(self.v["value"].get() or 0)
        except ValueError:
            want = 0
        if want > rng[1]:
            txt += f" — target {want:+d} can never be reached"
            self.range_lbl.configure(text=txt, foreground="#ff6b6b")
        else:
            if want and rng[1] > rng[0]:
                pct = max(0, min(100, round(100 * (rng[1] - want + 1) / (rng[1] - rng[0] + 1))))
                txt += f" — about {pct}% of casts hit {want:+d}+"
            self.range_lbl.configure(text=txt, foreground=ACCENT)

    def save(self):
        bf = {k: v.get().strip() for k, v in self.v.items()}
        if not bf["cast"]:
            messagebox.showinfo("Bless spell", "Enter the cast command.", parent=self)
            return
        for k in ("value", "check_secs", "every", "max_rerolls", "min_mana_pct"):
            try:
                bf[k] = int(bf[k]) if bf[k] else 0
            except ValueError:
                messagebox.showinfo("Bless spell", f"{k} must be a number.", parent=self)
                return
        bf["op"] = self.op.get()
        sp, rng = self._spell_range()
        if sp and bf["op"] == ">=" and bf["value"] > rng[1]:
            if not messagebox.askyesno("Bless spell", f"{sp['Name']} can only roll up to {rng[1]:+d} at your "
                                       f"level, so {bf['value']:+d} will never be reached.\n\nSave anyway?",
                                       parent=self):
                return
        bf["source"] = self.source.get()
        bf["in_combat"] = self.in_combat.get()
        bf["while_resting"] = self.while_resting.get()
        old = self.app.s.settings.buffs[self.index] if self.index is not None else {}
        bf["enabled"] = old.get("enabled", True)
        if self.index is None:
            self.app.s.settings.buffs.append(bf)
        else:
            self.app.s.settings.buffs[self.index] = bf
        self.app.s.settings.save()
        self.app.refresh_buffs()
        self.destroy()


class FontDialog(tk.Toplevel):
    """Options → Font: the MUD window (and input line) and the conversation box."""
    def __init__(self, master, app):
        super().__init__(master)
        import tkinter.font as tkfont
        self.app = app
        st = app.s.settings
        self.title("Font")
        self.configure(background=PANEL)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=16)
        f.pack()
        fams = sorted(set(tkfont.families(self)), key=str.lower)
        mono = [x for x in (("Menlo", "SF Mono", "Monaco", "Andale Mono", "PT Mono") if sys.platform == "darwin"
                            else ()) + ("Consolas", "Cascadia Mono", "Cascadia Code", "Lucida Console", "Courier New",
                                        "Terminal", "Fixedsys", "DejaVu Sans Mono", "Liberation Mono", "Ubuntu Mono",
                                        "Noto Sans Mono") if x in fams]
        values = mono + ["──────────"] + [x for x in fams if x not in mono and not x.startswith("@")]
        self.vars = {}
        for r, (lbl, fk, sk) in enumerate((("MUD window", "term_font", "term_font_size"),
                                           ("Conversations", "chat_font", "chat_font_size"))):
            ttk.Label(f, text=lbl, style="Head.TLabel").grid(row=r * 2, column=0, sticky="w", pady=(8 if r else 0, 2))
            fv, sv = tk.StringVar(value=getattr(st, fk)), tk.IntVar(value=getattr(st, sk))
            ttk.Combobox(f, textvariable=fv, values=values, width=28).grid(row=r * 2 + 1, column=0, sticky="w")
            ttk.Spinbox(f, from_=6, to=40, width=5, textvariable=sv).grid(row=r * 2 + 1, column=1, padx=6)
            self.vars[(fk, sk)] = (fv, sv)
            for v in (fv, sv):
                v.trace_add("write", lambda *a: self.preview())
        self.sample = tk.Text(f, height=4, width=52, background=BG, foreground="#cfd6e0", borderwidth=0)
        self.sample.grid(row=4, column=0, columnspan=2, pady=10)
        self.sample.insert("1.0", "[HP=806/MA=588]: (Meditating)\nAboard the Swiftwind, Crew Quarters\n"
                                  "Obvious exits: north, south, east, west")
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="Apply", style="Accent.TButton", command=self.apply).pack(side="left", padx=4)
        ttk.Button(b, text="Close", command=self.destroy).pack(side="left")
        self.preview()
        self.transient(master)

    def preview(self):
        (fv, sv) = self.vars[("term_font", "term_font_size")]
        try:
            self.sample.configure(font=(fv.get(), int(sv.get())))
        except (tk.TclError, ValueError):
            pass

    def apply(self):
        st = self.app.s.settings
        for (fk, sk), (fv, sv) in self.vars.items():
            fam = fv.get().strip()
            if fam and not fam.startswith("─"):
                setattr(st, fk, fam)
            try:
                setattr(st, sk, max(6, min(int(sv.get()), 40)))
            except (tk.TclError, ValueError):
                pass
        st.save()
        self.app.apply_fonts()


class ConnectDialog(tk.Toplevel):
    def __init__(self, master, app: App):
        super().__init__(master)
        self.app = app
        st = app.s.settings
        self.title("Connect")
        self.configure(background=PANEL)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=16)
        f.pack()
        self.host = tk.StringVar(value=st.host)
        self.port = tk.StringVar(value=str(st.port))
        self.user = tk.StringVar(value=st.username)
        saved = config.get_password(st.username, st.host) if st.username else None
        self.pw = tk.StringVar(value=saved or "")
        self.save = tk.BooleanVar(value=st.save_password)
        for i, (lbl, var, show) in enumerate((("BBS host", self.host, None), ("Port", self.port, None),
                                              ("User-ID", self.user, None), ("Password", self.pw, "•"))):
            ttk.Label(f, text=lbl).grid(row=i, column=0, sticky="w", pady=4)
            e = ttk.Entry(f, textvariable=var, width=30, show=show or "")
            e.grid(row=i, column=1, pady=4)
            if i == 0:
                e.focus_set()
        ttk.Checkbutton(f, text="Save password in Windows Credential Manager", variable=self.save).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(f, text="Login prompts are answered automatically (more triggers: data\\profiles\\<character>.json).",
                  style="Muted.TLabel", wraplength=320).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Button(b, text="Import from MegaMUD…", command=self.import_megamud).pack(side="left")
        ttk.Button(b, text="Connect", style="Accent.TButton", command=self.go).pack(side="right", padx=6)
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda e: self.go())
        self.transient(master)
        self.grab_set()

    def go(self):
        host, port = self.host.get().strip(), self.port.get().strip() or "23"
        if not host:
            return
        if not self.save.get():
            config.set_password(self.user.get().strip(), None, self.host.get().strip())
        self.destroy()
        self.app._do_connect(host, int(port), self.user.get().strip(), self.pw.get(), self.save.get())

    def import_megamud(self):
        """Dan: point at a MegaMUD character .ini and go. Reads the UserID and saved password, puts the password
        straight into Windows Credential Manager (never shown), and connects with it."""
        from tkinter import filedialog
        from . import megamud_import
        path = filedialog.askopenfilename(title="MegaMUD character file (Chars\\<name>.ini)",
                                          filetypes=[("MegaMUD character", "*.ini"), ("All files", "*.*")],
                                          parent=self)
        if not path:
            return
        try:
            info = megamud_import.read_login(path)
        except OSError as ex:
            messagebox.showerror("MudPilot", f"Couldn't read that file:\n{ex}", parent=self)
            return
        if not info["user"]:
            messagebox.showinfo("MudPilot", "No UserID in that file — is it a MegaMUD character .ini "
                                "(in MegaMUD's Chars folder)?", parent=self)
            return
        self.user.set(info["user"])
        host = self.host.get().strip()
        if not info["password"]:
            messagebox.showinfo("MudPilot", f"Imported the user name ({info['user']}). The password couldn't be "
                                "read — type it in once and it'll be saved.", parent=self)
            return
        if host:
            config.set_password(info["user"], info["password"], host)      # into Credential Manager, not shown
        self.save.set(True)
        self.destroy()
        self.app._do_connect(host, int(self.port.get().strip() or "23"), info["user"], info["password"], True)


_T0 = 0.0


def claim_data_folder(data_dir=None) -> bool:
    """(0.8.201, bug hunt: only the launcher checked its data folder was free — 'python -m mudpilot' opened a second
    MudPilot on a character already running, and the two logged each other off every minute.) Opened by the
    launcher: it holds the folder already. Otherwise refuse a folder in use, or mark it ours until we close."""
    from . import control as _ctl
    from . import launcher as _l
    if _ctl.by_launcher():
        return True
    data_dir = data_dir or config.DATA_DIR
    if _l.folder_in_use(data_dir):
        return False
    p = os.path.join(data_dir, "control", _l.IN_USE)
    try:
        import json
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "t": time.time()}, f)
    except OSError:
        return True

    def unmark():
        try:
            import json
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("pid") == os.getpid():
                    os.remove(p)
        except (OSError, ValueError):
            pass
    import atexit
    atexit.register(unmark)
    return True


def main():
    global _T0
    _T0 = time.time()
    if os.name == "nt":
        try:  # crisp text on high-DPI Windows displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        from . import winshell
        winshell.set_process_id()   # our own taskbar button with the MudPilot guy — before the first window
    elif sys.platform.startswith("linux") and not os.environ.get("FONTCONFIG_FILE"):
        # the Windows fonts asked for all over (Consolas, Segoe UI) → the Linux system's mono / sans fonts
        conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts-linux.conf")
        if os.path.exists(conf) and os.path.exists("/etc/fonts/fonts.conf"):
            os.environ["FONTCONFIG_FILE"] = conf
    root = tk.Tk()
    if sys.platform == "darwin":
        try:   # Consolas & co. aren't on a Mac: draw them in Menlo so the game's columns line up (macfonts.py)
            from . import macfonts
            macfonts.install(root)
        except Exception:
            pass
    if os.name == "nt":
        try:
            root.iconbitmap(default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mudpilot.ico"))
        except tk.TclError:
            pass
    root.withdraw()                                  # build the window behind the loading screen
    if not claim_data_folder():
        messagebox.showinfo("MudPilot", f"{os.path.basename(config.DATA_DIR)} is already open in another MudPilot.")
        root.destroy()
        return
    from . import config as _c
    from .splash import Splash
    try:
        _c._splash = Splash(root)
    except Exception:
        _c._splash = None
    app = App(root)
    sp = getattr(_c, "_splash", None)
    if sp:
        sp.step(96, "Opening the gates…")
    root.deiconify()
    try:
        if getattr(app.s.settings, "start_maximized", True) or (app.s.settings.window_geom or {}).get("main_zoomed"):
            root.state("zoomed") if os.name == "nt" else root.attributes("-zoomed", True)
    except Exception:
        pass
    root.update_idletasks()
    if sp:
        sp.step(100, "Ready")
        root.after(250, sp.close)
    _c._splash = None
    try:
        from .hangwatch import HangWatch
        app._hangwatch = HangWatch(root, lambda m: app.s.log(m), session=app.s)
    except Exception:
        pass
    app.s.log(f"Started in {time.time() - _T0:.1f} s")
    try:
        from .config import Settings as _S
        if _S._profile_note:
            app.s.log("Settings: " + _S._profile_note)
        app.s.log("Settings: " + app.s.settings.describe())
    except Exception:
        pass
    if app.s.sync.folder:
        root.after(500, lambda: app.add_log("Sync: " + app.s.sync.sync_now(startup=True)))
    if os.name == "nt":
        from . import winshell
        from . import config as _cfg
        winshell.ensure_shortcuts(_cfg.DATA_DIR, log=lambda m: root.after(0, app.s.log, m))
        winshell.ensure_launcher_shortcuts(_cfg.DATA_DIR, log=lambda m: root.after(0, app.s.log, m))
    root.mainloop()
    if getattr(app, "exit_code", 0):
        sys.exit(app.exit_code)


if __name__ == "__main__":
    main()
