"""Game Data window (MegaMUD's Options > Game Data): Players, Monsters, Items, Spells,
Rooms, Paths, Macros — plus the Spell Book and CP/Exp calculator windows."""
from __future__ import annotations

import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from . import expcalc as X
from . import gearcalc as G
from .macros import ALL_KEYS, split as macro_split
from .players import RELATIONSHIPS
from .spells import calc as spell_calc, is_attack_spell, spell_kind, ELEMENT_ABIL

MUTED = "#8a94a6"
ELEMENTS = {0: "cold", 1: "fire", 2: "stone", 3: "lightning", 5: "water"}


def _ago(t):
    if not t:
        return "never"
    d = time.time() - float(t)
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{d / 3600:.1f} h ago"
    return time.strftime("%d %b %Y", time.localtime(float(t)))


def _tree(parent, cols, widths, height=16):
    f = ttk.Frame(parent)
    t = ttk.Treeview(f, columns=cols[1:], show="headings tree" if False else "headings", height=height)
    t.configure(columns=cols)
    for c, w in zip(cols, widths):
        t.heading(c, text=c, command=lambda c=c: _sort(t, c))
        t.column(c, width=w, anchor="w")
    sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, t


def _sort(tree, col, again=False):
    """Click a heading to sort by it, click again to flip. Blank cells always go to the bottom (Dan, 2026-11-16:
    click Get and see everything on auto-grab, not 2,000 blank rows first). again=True re-applies the last sort
    after the list is refilled (typing in Find)."""
    if again:
        col, rev = getattr(tree, "_last", (None, False))
        if not col:
            return
    else:
        rev = getattr(tree, "_rev", {}).get(col, False)
    rows = [(tree.set(k, col), k) for k in tree.get_children("")]
    def key(v):
        s = v[0].replace(",", "").replace("%", "")
        try:
            return (0, float(s), "")
        except ValueError:
            return (1, 0, s.lower())
    full = [r for r in rows if r[0].strip()]
    full.sort(key=key, reverse=rev)
    rows = full + [r for r in rows if not r[0].strip()]
    for i, (_v, k) in enumerate(rows):
        tree.move(k, "", i)
    if rows:
        tree.see(rows[0][1])
    tree._last = (col, rev)
    if again:
        return
    tree._rev = dict(getattr(tree, "_rev", {}), **{col: not rev})


def _search_bar(parent, on_search, label="Find"):
    bar = ttk.Frame(parent)
    var = tk.StringVar()
    ttk.Label(bar, text=label).pack(side="left")
    e = ttk.Entry(bar, textvariable=var, width=30)
    e.pack(side="left", padx=6)
    e.bind("<Return>", lambda ev: on_search(var.get()))
    var.trace_add("write", lambda *a: on_search(var.get()))
    return bar, var


class GameData(ttk.Frame):
    TABS = ("Players", "Monsters", "Items", "Spells", "Rooms", "Paths", "Macros", "Aliases", "Messages")

    def __init__(self, master, app, tab=None):
        super().__init__(master, padding=8)
        self.app, self.s = app, app.s
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tabs = {}
        for name in self.TABS:
            f = getattr(self, "_" + name.lower())(self.nb)
            self.nb.add(f, text=name)
            self.tabs[name] = f
        if tab in self.tabs:
            self.nb.select(self.tabs[tab])

    def select(self, tab):
        if tab in self.tabs:
            self.nb.select(self.tabs[tab])

    # ------------------------------------------------------------ players
    def _players(self, nb):
        f = ttk.Frame(nb, padding=8)
        top = ttk.Frame(f)
        top.pack(fill="x")
        bar, self.p_find = _search_bar(top, lambda q: self.p_fill())
        bar.pack(side="left")
        ttk.Checkbutton(top, text="Look at players once to learn their gear", variable=self.app._var("learn_players")
                        ).pack(side="left", padx=12)
        ttk.Label(top, text="every").pack(side="left")
        ttk.Spinbox(top, from_=1, to=720, width=5, textvariable=self.app._var("look_player_hours")).pack(side="left", padx=4)
        ttk.Label(top, text="hours at most").pack(side="left")
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, pady=6)
        cols = ("Name", "Relationship", "@", "Align", "Gang", "Title", "Class", "Last seen", "Looked", "Items")
        tf, self.p_tree = _tree(body, cols, (130, 80, 45, 60, 140, 120, 80, 90, 90, 40))
        tf.pack(side="left", fill="both", expand=True)
        self.p_tree.tag_configure("Friend", foreground="#5cff7a")
        self.p_tree.tag_configure("Enemy", foreground="#ff6b6b")
        self.p_tree.bind("<Double-1>", lambda e: self.p_edit())
        side = ttk.Frame(body)
        side.pack(side="left", fill="y", padx=(8, 0))
        for txt, fn in (("New…", lambda: self.p_edit(new=True)), ("Modify…", self.p_edit), ("Remove", self.p_remove),
                        ("Look now", self.p_look), ("@ all on/off", self.p_all_remote)):
            ttk.Button(side, text=txt, command=fn, width=12).pack(pady=2)
        ttk.Label(f, text="Friends never trigger a hang-up. Enemies cause a hang-up when seen (PvP tab). "
                          "Players in shadow form show no gear; MudPilot still waits the full interval before looking again.",
                  style="Muted.TLabel", wraplength=760).pack(anchor="w")
        self.s.players.on_change = lambda: self.app.root.after(0, self.p_fill)
        self.p_fill()
        return f

    def p_fill(self):
        if not self.p_tree.winfo_exists():
            return
        q = self.p_find.get().strip().lower()
        self.p_tree.delete(*self.p_tree.get_children())
        for p in self.s.players.rows():
            if q and not any(q in (p.get(k) or "").lower() for k in ("name", "surname", "class", "gang", "title")):
                continue
            looked = "don't look" if p.get("dont_look") else _ago(p.get("last_looked"))
            self.p_tree.insert("", "end", iid=p["name"].lower(), tags=(p.get("relationship", "Unknown"),), values=(
                p["name"] + (f" {p['surname']}" if p.get("surname") else ""), p.get("relationship", "Unknown"),
                remote_label(self.s.settings, p["name"]), p.get("alignment") or "", p.get("gang") or "", p.get("title") or "",
                p.get("class") or "?", _ago(p.get("last_seen") or p.get("last_online")),
                looked, len(p.get("wearing") or [])))

    def _p_sel(self):
        sel = self.p_tree.selection()
        return self.s.players.data.get(sel[0]) if sel else None

    def p_remove(self):
        p = self._p_sel()
        if p and messagebox.askyesno("Remove player", f"Forget everything about {p['name']}?", parent=self):
            self.s.players.remove(p["name"])
            self.s.players.save()
            self.p_fill()

    def p_all_remote(self):
        """Dan: when he gives someone @'s it's nearly always all of them — one click on, one click off."""
        p = self._p_sel()
        if not p:
            return
        from .remote import CATEGORIES
        st = self.s.settings
        rp = dict(st.remote_players or {})
        key = next((k for k in rp if k.lower() == p["name"].lower()), p["name"])
        if set(rp.get(key) or []) >= set(CATEGORIES):
            if not messagebox.askyesno("Remote control", f"Take away all of {p['name']}'s @ commands?", parent=self):
                return
            rp.pop(key, None)
        else:
            if not messagebox.askyesno(
                    "Remote control", f"Give {p['name']} every @ command — including @do (type anything as you), "
                    "hang up / relog and divert telepaths?", parent=self):
                return
            rp[key] = list(CATEGORIES)
        st.remote_players = rp
        st.save()
        self.app.add_log(f"Remote control: {p['name']} — " + ("all @ commands" if rp.get(key) else "none"))
        self.p_fill()

    def p_look(self):
        p = self._p_sel()
        if p and self.s.telnet.connected:
            self.s.players.look_now(p["name"])

    def p_edit(self, new=False):
        if new:
            nm = simpledialog.askstring("New player", "Player name:", parent=self)
            if not nm or not nm.strip():
                return
            p = self.s.players.get(nm.strip().split()[0])
        else:
            p = self._p_sel()
            if not p:
                return
        PlayerDialog(self, self.app, p)
        self.s.players.save()
        self.p_fill()

    # ------------------------------------------------------------ monsters / items / spells (MME data, read-only)
    def _monsters(self, nb):
        f = ttk.Frame(nb, padding=8)
        cols = ("#", "Name", "Exp", "HP", "AC/DR", "MR", "Resists", "Boss", "Regen", "My spell", "Attitude")
        tf, t = _tree(f, cols, (50, 180, 80, 60, 60, 45, 150, 45, 60, 110, 90))
        mine_only = tk.BooleanVar(value=False)
        def fill(q=None):
            if q is None:
                q = ""
            t.delete(*t.get_children())
            q = (q or "").strip().lower()
            n = 0
            for num, m in sorted(self.s.world.monsters.items()):
                if q and q not in m["name"].lower():
                    continue
                choice = self._mon_choice(m)
                if mine_only.get() and choice == "":
                    continue
                ab = m.get("abils") or {}
                res = ", ".join(f"r{n_[:3]} {ab.get(str(a), ab.get(a))}" for a, n_ in
                                ((3, "cold"), (5, "fire"), (65, "stone"), (66, "lit"), (147, "water"))
                                if ab.get(str(a), ab.get(a)))
                t.insert("", "end", values=(num, m["name"], f"{int(m.get('exp') or 0):,}", m.get("hp", ""),
                                            f"{m.get('ac', '')}/{m.get('dr', '')}", m.get("mr", ""), res,
                                            "yes" if m.get("boss") else "", f"{m['regen_h']}h" if m.get("regen_h") else "",
                                            choice, self._attitude(m)), iid=str(num))
                n += 1
                if n >= 2000:
                    break
        bar, v = _search_bar(f, fill)
        bar.pack(fill="x")
        ttk.Checkbutton(bar, text="Only monsters I've set a spell for", variable=mine_only,
                        command=lambda: fill(v.get())).pack(side="left", padx=12)
        tf.pack(fill="both", expand=True, pady=6)
        drops = ttk.Label(f, text="Pick a monster to see what it drops.", style="Muted.TLabel", wraplength=900,
                          justify="left")
        drops.pack(anchor="w", pady=(0, 4))
        ttk.Label(f, text="Double-click a monster to choose the spell MudPilot hits it with (or melee). Your choice "
                          "beats the automatic pick and spell-efficiency learning.", style="Muted.TLabel").pack(anchor="w")

        def show_drops(_e=None):
            sel = t.selection()
            m = (self.s.world.monsters.get(int(sel[0])) if sel else None)
            if not m:
                return
            cl = self.s.combatlog
            mme = cl.mme_drops(m)
            kills, seen = cl.seen_drops(m["name"])
            parts = []
            for nm, pct in mme[:14]:
                got = seen.get(nm.lower())
                parts.append(f"{nm} {pct:g}%" + (f" (seen {got[0]}×, last {time.strftime('%m-%d %H:%M', time.localtime(got[1]))})"
                                                  if got else ""))
            extra = [f"{nm} (seen {c[0]}×)" for nm, c in seen.items() if nm not in {x[0].lower() for x in mme}]
            txt = f"{m['name']} drops — MME: " + (", ".join(parts) if parts else "nothing listed")
            if extra:
                txt += "  ·  also seen after your kills: " + ", ".join(extra[:10])
            txt += f"  ·  your kills counted: {kills}"
            drops.configure(text=txt)
        t.bind("<<TreeviewSelect>>", show_drops, add="+")

        def edit(_e=None):
            sel = t.selection()
            if not sel:
                return
            m = self.s.world.monsters.get(int(sel[0])) or self.s.world.monsters.get(sel[0])
            if m:
                MonsterSpellDialog(self, self.app, m)
                fill(v.get())
                t.selection_set(sel[0]) if t.exists(sel[0]) else None
        t.bind("<Double-1>", edit)

        def set_att(att):
            # Enemy / Neutral / Friend, as on MegaMUD's monster list (0.8.208, Dan): beats MME's alignment
            cfg = self.s.settings
            cur = dict(getattr(cfg, "monster_attitude", None) or {})
            sel = list(t.selection())
            for iid in sel:
                m = self.s.world.monsters.get(int(iid))
                if not m:
                    continue
                k = m["name"].lower()
                if att:
                    cur[k] = att
                else:
                    cur.pop(k, None)
                self.s.log(f"Game Data: {m['name']} → {att or 'default (MME alignment)'}")
            cfg.monster_attitude = cur
            cfg.save()
            fill(v.get())
            for iid in sel:
                if t.exists(iid):
                    t.selection_add(iid)

        menu = tk.Menu(t, tearoff=0)
        menu.add_command(label="Enemy — attack it", command=lambda: set_att("enemy"))
        menu.add_command(label="Neutral — leave it alone unless it attacks", command=lambda: set_att("neutral"))
        menu.add_command(label="Friend — never start a fight with it", command=lambda: set_att("friend"))
        menu.add_command(label="Default (MME's alignment)", command=lambda: set_att(None))
        menu.add_separator()
        menu.add_command(label="Choose its spell…", command=edit)

        def popup(e):
            iid = t.identify_row(e.y)
            if iid and iid not in t.selection():
                t.selection_set(iid)
            if t.selection():
                menu.tk_popup(e.x_root, e.y_root)
        t.bind("<Button-3>", popup)
        att_bar = ttk.Frame(f)
        att_bar.pack(fill="x", before=drops)
        ttk.Label(att_bar, text="Attitude:").pack(side="left")
        for lbl, att in (("Enemy", "enemy"), ("Neutral", "neutral"), ("Friend", "friend"), ("Default", None)):
            ttk.Button(att_bar, text=lbl, command=lambda a=att: set_att(a)).pack(side="left", padx=(4, 0))
        ttk.Label(att_bar, text="  (right-click works too · '@enemy <name>' remotely)",
                  style="Muted.TLabel").pack(side="left")
        fill("")
        return f

    def _attitude(self, m) -> str:
        att = (getattr(self.s.settings, "monster_attitude", None) or {}).get((m.get("name") or "").lower())
        if att:
            return att.capitalize()
        try:
            return "" if self.s.bot.hostile(m) else "(not hostile)"
        except Exception:
            return ""

    def _mon_choice(self, m) -> str:
        ov = self.s.bot.monster_spell(m)
        if ov is None:
            return ""
        return ov or "melee only"

    def _items(self, nb):
        f = ttk.Frame(nb, padding=8)
        cols = ("#", "Name", "Get", "Slot", "Type", "Notes")
        tf, t = _tree(f, cols, (50, 220, 90, 80, 90, 320))
        t.configure(selectmode="extended")
        gear = getattr(self.s.world, "gear", {}) or {}
        cfg = self.s.settings

        def rules():
            """The Loot tab's item rules ('rope and grapple: get, max 1') — what the Get column shows and sets."""
            out = {}
            for ln in cfg.item_rules or []:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    out[k.strip().lower()] = v.strip()
            return out

        def get_text(spec):
            t_ = get_text0(spec)
            if "stash" in [x.strip() for x in re.split(r"[,;]", (spec or "").lower())]:
                return (t_ + ", stash") if t_ else "stash"
            return t_

        def get_text0(spec):
            sp = (spec or "").lower()
            if "never" in sp:
                return "never"
            m = re.search(r"max\s+(\d+)", sp)
            if "get" in sp:
                return f"auto, max {m.group(1)}" if m else "auto"
            return f"max {m.group(1)}" if m else ""

        def fill(q=""):
            t.delete(*t.get_children())
            q = q.strip().lower()
            rs = rules()
            only = q in ("auto", "auto-get", "get")
            only_st = q in ("stash", "auto-stash")
            n = 0
            for num, g in sorted(gear.items()):
                nm = g.get("name") or ""
                if only_st:
                    if "stash" not in rs.get(nm.lower(), "").lower():
                        continue
                elif only:
                    if "get" not in rs.get(nm.lower(), ""):
                        continue
                elif q and q not in nm.lower():
                    continue
                try:
                    note = G.describe(self.s.world, g)
                except Exception:
                    note = ""
                t.insert("", "end", iid=str(num), values=(num, nm, get_text(rs.get(nm.lower())),
                                                          G.WORN_SLOT.get(int(g.get("Worn") or 0), ""),
                                                          {0: "armour", 1: "weapon"}.get(int(g.get("ItemType") or -1), "item"), note))
                n += 1
                if n >= 10000:                         # (was 2000 — Paradigm has 2,748 items, the rest never showed)
                    break
            _sort(t, None, again=True)                 # keep the column sort while typing in Find

        def set_rule(kind):
            """MegaMUD's item flags (Dan, 2026-11-01: everybody's coming from MegaMUD — set it in Game Data → Items):
            auto-get, auto-get up to N, never pick up, or back to normal."""
            names = [t.set(i, "Name") for i in t.selection()]
            if not names:
                return
            spec = {"auto": "get", "never": "never", "clear": ""}.get(kind)
            if kind == "max":
                n = simpledialog.askinteger("Auto-get", "Pick up until you have how many?", parent=self, minvalue=1,
                                            maxvalue=999, initialvalue=1)
                if not n:
                    return
                spec = f"get, max {n}"
            rs = rules()
            stashed = {x.lower() for x in names if kind not in ("clear", "never") and
                       "stash" in [p.strip() for p in re.split(r"[,;]", rs.get(x.lower(), "").lower())]}
            keep = [ln for ln in (cfg.item_rules or [])
                    if ln.split(":", 1)[0].strip().lower() not in {x.lower() for x in names}]
            new = [f"{x}: {spec}" + (", stash" if x.lower() in stashed else "") for x in names if spec]
            cfg.item_rules = keep + new
            if spec and "get" in spec:
                cfg.auto_loot = True                   # (looting has to be on for it to pick anything up)
            cfg.save()
            fill_sel()
            try:
                self.app.add_log(f"Game Data → Items: {', '.join(names)} → {get_text(spec) or 'normal'}")
            except Exception:
                pass

        def fill_sel():
            rs = rules()
            for i in t.selection():
                t.set(i, "Get", get_text(rs.get(t.set(i, "Name").lower())))

        def toggle_stash():
            """0.8.200 (Dan): per item, hide it in the stash room as well as picking it up — the cudgels, not the
            ears. Ticks on for the selection, or off if they're all on already. Turning it on picks it up too."""
            names = [t.set(i, "Name") for i in t.selection()]
            if not names:
                return
            rs = rules()

            def parts(x):
                return [p.strip() for p in re.split(r"[,;]", rs.get(x.lower(), "")) if p.strip()]
            on = not all("stash" in [p.lower() for p in parts(x)] for x in names)
            keep = [ln for ln in (cfg.item_rules or [])
                    if ln.split(":", 1)[0].strip().lower() not in {x.lower() for x in names}]
            new = []
            for x in names:
                ps = [p for p in parts(x) if p.lower() not in ("stash", "never")]
                if on:
                    if not any(p.lower() == "get" for p in ps):
                        ps.insert(0, "get")
                    ps.append("stash")
                if ps:
                    new.append(f"{x}: {', '.join(ps)}")
            cfg.item_rules = keep + new
            if on:
                cfg.auto_loot = True
            cfg.save()
            fill_sel()
            try:
                self.app.add_log(f"Game Data → Items: {', '.join(names)} → auto-stash {'on' if on else 'off'}"
                                 + ("" if not on or cfg.stash_room or cfg.loop_stash or cfg.party_stash_room else
                                    " (no stash room set yet: Loot tab, Paths → More, or a member's @stash)"))
            except Exception:
                pass

        bar, _v = _search_bar(f, fill)
        bar.pack(fill="x")
        tf.pack(fill="both", expand=True, pady=6)
        bb = ttk.Frame(f)
        bb.pack(fill="x")
        ttk.Button(bb, text="Auto-get", command=lambda: set_rule("auto")).pack(side="left")
        ttk.Button(bb, text="Auto-get up to…", command=lambda: set_rule("max")).pack(side="left", padx=4)
        ttk.Button(bb, text="Never get", command=lambda: set_rule("never")).pack(side="left")
        ttk.Button(bb, text="Normal", command=lambda: set_rule("clear")).pack(side="left", padx=4)
        ttk.Button(bb, text="Auto-stash", command=toggle_stash).pack(side="left")
        ttk.Label(bb, text="select items (Ctrl/Shift for several) · Auto-stash = get it and hide it in the stash room "
                           "· find 'auto' or 'stash' lists them",
                  style="Muted.TLabel").pack(side="left", padx=8)
        t.bind("<Double-1>", lambda e: set_rule("clear" if t.set(t.focus(), "Get") else "auto") if t.focus() else None)
        if not gear:
            ttk.Label(f, text="No item data yet — re-import this board's MME file.", style="Muted.TLabel").pack(anchor="w")
        fill()
        return f

    def _spells(self, nb):
        f = ttk.Frame(nb, padding=8)
        cols = ("Short", "Name", "Level", "Mana", "Kind", "Element", "Class")
        tf, t = _tree(f, cols, (60, 200, 50, 60, 80, 80, 120), height=12)
        cfg = self.s.settings
        from .spells import describe, apply_mana_overrides

        def mana_text(sp):
            m, mme = int(sp.get("ManaCost") or 0), sp.get("_mme_mana")
            return f"{m}*" if mme is not None and mme != m else str(m)

        def fill(q=""):
            t.delete(*t.get_children())
            q = q.strip().lower()
            for num, sp in sorted(self.s.world.spells.items()):
                nm = sp.get("Name", "")
                if q and q not in nm.lower() and q != (sp.get("Short") or "").lower():
                    continue
                t.insert("", "end", iid=str(num), values=(sp.get("Short", ""), nm, sp.get("ReqLevel", ""), mana_text(sp),
                                                          spell_kind(sp) or ("attack" if is_attack_spell(sp) else ""),
                                                          ELEMENTS.get(int(sp.get("AttType") or -1), "") if is_attack_spell(sp) else "",
                                                          sp.get("Learned From", "")))

        info = tk.Text(f, height=9, wrap="word", borderwidth=0)
        try:
            info.configure(background=self.app.term.cget("background"), foreground="#e0e0e0")
        except Exception:
            pass

        def show(_e=None):
            sel = t.selection()
            sp = self.s.world.spells.get(int(sel[0])) if sel else None
            info.configure(state="normal")
            info.delete("1.0", "end")
            if sp:
                info.insert("1.0", describe(self.s.world, sp, self.s.state.level or cfg.char_level or 0))
            info.configure(state="disabled")

        def set_mana(reset=False):
            """Your own mana cost: a low character casts (and so engages, and earns its share) without the mana
            for it — the spell just never goes off (Dan, 2026-11-01, power-levelling)."""
            sel = t.selection()
            if not sel:
                return
            sp = self.s.world.spells.get(int(sel[0]))
            if not sp:
                return
            ov = dict(cfg.spell_mana or {})
            if reset:
                ov.pop(str(sel[0]), None)
            else:
                n = simpledialog.askinteger("Mana cost", f"Mana cost for {sp.get('Name')} "
                                            f"(MME says {sp.get('_mme_mana', sp.get('ManaCost'))}; 0 = cast it whatever "
                                            "your mana):", parent=self, minvalue=0, maxvalue=9999,
                                            initialvalue=int(sp.get("ManaCost") or 0))
                if n is None:
                    return
                ov[str(sel[0])] = n
            cfg.spell_mana = ov
            cfg.save()
            apply_mana_overrides(self.s.world, ov)
            t.set(sel[0], "Mana", mana_text(sp))
            show()
            try:
                self.app.add_log(f"Game Data → Spells: {sp.get('Name')} mana {sp.get('ManaCost')}"
                                 + (" (MME's again)" if reset else ""))
            except Exception:
                pass

        bar, _v = _search_bar(f, fill)
        bar.pack(fill="x")
        tf.pack(fill="both", expand=True, pady=6)
        bb = ttk.Frame(f)
        bb.pack(fill="x")
        ttk.Button(bb, text="Set mana cost…", command=set_mana).pack(side="left")
        ttk.Button(bb, text="MME's cost", command=lambda: set_mana(True)).pack(side="left", padx=4)
        ttk.Label(bb, text="click a spell for what it does · * = your own mana cost (0 = cast it even without the "
                           "mana — it engages, the spell just doesn't go off)", style="Muted.TLabel").pack(side="left", padx=8)
        info.pack(fill="x", pady=(6, 0))
        t.bind("<<TreeviewSelect>>", show)
        t.bind("<Double-1>", lambda e: set_mana())
        fill()
        return f

    # ------------------------------------------------------------ rooms
    def _rooms(self, nb):
        f = ttk.Frame(nb, padding=8)
        cols = ("Map/Room", "Name", "Exits", "Hash")
        tf, t = _tree(f, cols, (80, 280, 260, 90))
        w = self.s.world
        def fill(q=""):
            t.delete(*t.get_children())
            q = q.strip()
            if len(q) < 2:
                return
            hits = []
            if "/" in q:
                try:
                    a, b = (int(x) for x in q.split("/", 1))
                    if w.room((a, b)):
                        hits = [(a, b)]
                except ValueError:
                    pass
            if not hits:
                ql = q.lower()
                hits = [k for k, r in w.rooms.items() if ql in r.name.lower()][:500]
            for k in sorted(hits):
                r = w.room(k)
                ex = ", ".join(f"{d.lower()}→{e.to[0]}/{e.to[1]}" if e.to else d.lower() for d, e in r.exits.items())
                h = r.mega_hash or ""
                t.insert("", "end", iid=f"{k[0]}/{k[1]}", values=(f"{k[0]}/{k[1]}", r.name, ex, h))
        bar, var = _search_bar(f, fill, "Find room (name or map/room)")
        bar.pack(fill="x")
        tf.pack(fill="both", expand=True, pady=6)
        act = ttk.Frame(f)
        act.pack(fill="x")
        def sel():
            s = t.selection()
            return tuple(int(x) for x in s[0].split("/")) if s else None
        def go():
            k = sel()
            if k:
                self.app.goto_room(k)
        def here():
            k = sel()
            if k:
                self.s.state.set_room(k)
                self.s.log(f"Location set by hand: {k[0]}/{k[1]} {w.room(k).name}")
        def relearn():
            self.s.state.candidates = []
            b = self.s.bot
            b._locate_failed, b._locate_at, b._unsure_since = 0, 0.0, time.time() - 10
            self.s.send("")
            self.s.log("Relearning where you are…")
        ttk.Button(act, text="Go there", command=go).pack(side="left")
        ttk.Button(act, text="I'm here", command=here).pack(side="left", padx=4)
        ttk.Button(act, text="Relearn current room", command=relearn).pack(side="left")
        def camp():
            k = sel()
            if k:
                self.s.log(self.s.lair_camp.add(k))   # Paths → Camp lairs (0.8.201)
        ttk.Button(act, text="Add to Camp lairs", command=camp).pack(side="left", padx=4)
        ttk.Button(act, text="Show current room", command=lambda: var.set(
            f"{self.s.state.room[0]}/{self.s.state.room[1]}" if self.s.state.room else "")).pack(side="left", padx=4)
        ttk.Label(f, text="Rooms come from this board's MME file. \"Relearn\" makes MudPilot work out the room again "
                          "(look, then your board's locate command if needed).", style="Muted.TLabel",
                  wraplength=760).pack(anchor="w", pady=(6, 0))
        return f

    # ------------------------------------------------------------ paths
    def _paths(self, nb):
        f = ttk.Frame(nb, padding=8)
        cols = ("Name", "Kind", "Steps", "From", "To")
        tf, t = _tree(f, cols, (220, 60, 50, 200, 200))
        w = self.s.world
        def rname(k):
            r = w.room(k) if k else None
            return f"{k[0]}/{k[1]} {r.name}" if r else "?"
        def fill(q=""):
            t.delete(*t.get_children())
            q = q.strip().lower()
            for i, mp in enumerate(self.s.paths):
                a = mp.steps[0].room if mp.steps else None
                b = mp.steps[-1].room if mp.steps else None
                loop = bool(mp.steps) and a == b or getattr(mp, "is_loop", False)
                txt = " ".join((mp.title, rname(a), rname(b))).lower()
                if q and q not in txt:
                    continue
                t.insert("", "end", iid=str(i), values=(mp.title, "loop" if loop else "path", len(mp.steps), rname(a), rname(b)))
        bar, _v = _search_bar(f, fill, "Find path / loop (name or room)")
        bar.pack(fill="x")
        tf.pack(fill="both", expand=True, pady=6)
        act = ttk.Frame(f)
        act.pack(fill="x")
        def chosen():
            s_ = t.selection()
            return self.s.paths[int(s_[0])] if s_ else None
        def run(loop):
            mp = chosen()
            if mp:
                if mp.steps and mp.steps[0].room and self.s.state.room and not any(x.room == self.s.state.room for x in mp.steps):
                    self.s.bot.goto(mp.steps[0].room, then=mp, ask=getattr(self.app, 'ask_route', None))
                else:
                    self.s.bot.start_path(mp, loop=loop)
        ttk.Button(act, text="Run", command=lambda: run(False)).pack(side="left")
        ttk.Button(act, text="Run as loop", command=lambda: run(True)).pack(side="left", padx=4)
        ttk.Button(act, text="Import .mp…", command=lambda: (self.app.import_mp_files(), fill())).pack(side="left")
        fill()
        return f

    # ------------------------------------------------------------ macros
    # ------------------------------------------------------------ messages (MegaMUD Messages file)
    def _messages(self, nb):
        from . import messagerules as MR
        f = ttk.Frame(nb, padding=8)
        top = ttk.Frame(f)
        top.pack(fill="x")
        bar, self.ms_find = _search_bar(top, lambda q: self.ms_fill())
        bar.pack(side="left")
        ttk.Checkbutton(top, text="Use message rules", variable=self.app._var("message_rules_on")).pack(side="left", padx=12)
        self.ms_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Show entries that do nothing too", variable=self.ms_all,
                        command=self.ms_fill).pack(side="left")
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, pady=6)
        cols = ("Name", "Means", "Do", "Reply", "Message", "Wears off with")
        tf, self.ms_tree = _tree(body, cols, (100, 120, 90, 70, 220, 160), height=12)
        side = ttk.Frame(body)
        side.pack(side="right", fill="y", padx=(8, 0))
        tf.pack(side="left", fill="both", expand=True)
        self.ms_tree.bind("<Double-1>", lambda e: self.ms_edit())
        for txt, fn in (("New…", lambda: self.ms_edit(new=True)), ("Edit…", self.ms_edit), ("Remove", self.ms_remove),
                        ("Import MegaMUD file…", self.ms_import), ("Make them mine", self.ms_own)):
            ttk.Button(side, text=txt, command=fn, width=20).pack(pady=2)
        rv = ttk.LabelFrame(f, text="Needs review: death lines MudPilot didn't know (seen just before the exp)", padding=6)
        rv.pack(fill="x")
        self.ms_review = tk.Listbox(rv, height=4, background="#0f1318", foreground="#e0e6ef", borderwidth=0)
        self.ms_review.pack(side="left", fill="x", expand=True)
        ttk.Button(rv, text="Clear", command=self.ms_review_clear).pack(side="left", padx=6)
        self.ms_note = ttk.Label(f, text="", style="Muted.TLabel", wraplength=860, justify="left")
        self.ms_note.pack(anchor="w")
        self.ms_fill()
        return f

    def ms_fill(self):
        from . import messagerules as MR
        m = self.s.msgrules
        t = self.ms_tree
        t.delete(*t.get_children())
        q = self.ms_find.get().strip().lower()
        for i, r in enumerate(m.rules):
            if not self.ms_all.get() and not MR.does_something(r):
                continue
            if q and q not in r["name"].lower() and q not in r["start"].lower():
                continue
            means = ", ".join(n.replace("_", " ") for b, n in MR.BITS.items() if r["mask"] & b)
            if r["mask"] & MR.F_ENDS_COMBAT:
                means += (", " if means else "") + "ends combat"
            if r["mask"] & MR.F_FAILED:
                means += (", " if means else "") + "last action failed"
            do = MR.MODES.get(r["mode"], str(r["mode"])) if r["mode"] else ""
            reply = (r.get("resp") or "").replace("^M", " ⏎ ").strip()
            if r.get("bundled") and (reply or r["mode"] in (3, 4, 6)):
                reply = ("(off) " + reply) if reply else reply
                do = ("(off) " + do) if r["mode"] in (3, 4, 6) else do
            t.insert("", "end", iid=str(i), values=(r["name"], means, do, reply, r["start"], r.get("end", "")))
        bundled = any(r.get("bundled") for r in m.rules)
        self.ms_note.configure(text=(
            f"{len(m.rules)} entries, {len(m.active)} that do something. "
            + ("These are the shipped MegaMUD messages: conditions work, but their replies and hang-ups are off "
               "(they were someone else's choices). Import your own MegaMUD Messages file, or press Make them mine "
               "to switch them all on." if bundled else "Your own messages file (data\\messages.md).")))
        self.ms_review.delete(0, "end")
        for rv in reversed(m.review[-50:]):
            self.ms_review.insert("end", f"{rv['line']}   — {rv.get('monster') or '?'} ×{rv['n']}")

    def _ms_sel(self):
        sel = self.ms_tree.selection()
        return int(sel[0]) if sel else None

    def ms_remove(self):
        i = self._ms_sel()
        if i is None:
            return
        m = self.s.msgrules
        del m.rules[i]
        m.save(); m.compile(); self.ms_fill()

    def ms_import(self):
        path = filedialog.askopenfilename(parent=self, title="MegaMUD Messages file",
                                          filetypes=[("MegaMUD messages", "*.md *.txt *.msg"), ("All files", "*.*")])
        if not path:
            return
        replace = messagebox.askyesno("Import", "Replace the current list with this file?\n\n"
                                                "No = add the new entries to it.", parent=self)
        try:
            n = self.s.msgrules.import_file(path, replace=replace)
        except OSError as ex:
            messagebox.showerror("Import", str(ex), parent=self)
            return
        messagebox.showinfo("Import", f"{n} entries read.", parent=self)
        self.ms_fill()

    def ms_own(self):
        m = self.s.msgrules
        for r in m.rules:
            r.pop("bundled", None)
        m.save(); m.compile(); self.ms_fill()

    def ms_review_clear(self):
        self.s.msgrules.review = []
        self.s.msgrules.save_review()
        self.ms_fill()

    def ms_edit(self, new=False):
        from . import messagerules as MR
        m = self.s.msgrules
        i = None if new else self._ms_sel()
        if not new and i is None:
            return
        r = {"name": "", "mask": 0, "mode": 0, "resp": "", "start": "", "end": ""} if new else dict(m.rules[i])
        d = tk.Toplevel(self)
        d.title("Message rule")
        d.transient(self.winfo_toplevel())
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        v = {k: tk.StringVar(value=str(r.get(k) or "")) for k in ("name", "start", "end", "resp")}
        for row, (lbl, k, w) in enumerate((("Name", "name", 30), ("Message", "start", 64),
                                           ("Wears off with (optional)", "end", 64),
                                           ("Reply (^M = Enter)", "resp", 40))):
            ttk.Label(fr, text=lbl).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(fr, textvariable=v[k], width=w).grid(row=row, column=1, sticky="w", pady=2)
        ttk.Label(fr, text="{target}, {dmg} … match anything", style="Muted.TLabel").grid(row=4, column=1, sticky="w")
        bits = ttk.LabelFrame(fr, text="It means", padding=6)
        bits.grid(row=5, column=0, columnspan=2, sticky="we", pady=6)
        bv = {}
        allbits = dict(MR.BITS)
        allbits.update({MR.F_ENDS_COMBAT: "ends combat", MR.F_FAILED: "last action failed",
                        MR.F_ANYWHERE: "find anywhere in the line", MR.F_CONVO: "also in conversations",
                        MR.F_DISABLED: "disabled"})
        for j, (b, name) in enumerate(allbits.items()):
            bv[b] = tk.BooleanVar(value=bool(r["mask"] & b))
            ttk.Checkbutton(bits, text=name.replace("_", " "), variable=bv[b]).grid(row=j // 4, column=j % 4, sticky="w")
        ttk.Label(fr, text="Then").grid(row=6, column=0, sticky="w")
        mv = tk.StringVar(value=MR.MODES.get(r["mode"], "nothing"))
        ttk.Combobox(fr, textvariable=mv, values=list(MR.MODES.values()), state="readonly", width=26).grid(
            row=6, column=1, sticky="w")

        def ok():
            if not v["start"].get().strip():
                messagebox.showinfo("Message rule", "The message can't be empty.", parent=d)
                return
            rr = {"name": v["name"].get().strip() or "rule", "start": v["start"].get().strip(),
                  "end": v["end"].get().strip(), "resp": v["resp"].get().strip(),
                  "mask": sum(b for b, var in bv.items() if var.get()),
                  "mode": next((k for k, t in MR.MODES.items() if t == mv.get()), 0)}
            if new:
                m.rules.append(rr)
            else:
                m.rules[i] = rr
            m.save(); m.compile()
            d.destroy()
        b = ttk.Frame(fr)
        b.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.wait_window()
        self.ms_fill()

    def _macros(self, nb):
        f = ttk.Frame(nb, padding=8)
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        cols = ("Key", "Macro", "Use")
        tf, self.m_tree = _tree(body, cols, (110, 380, 60))
        tf.pack(side="left", fill="both", expand=True)
        self.m_tree.bind("<Double-1>", lambda e: self.m_edit())
        side = ttk.Frame(body)
        side.pack(side="left", fill="y", padx=(8, 0))
        for txt, fn in (("New…", lambda: self.m_edit(new=True)), ("Modify…", self.m_edit), ("Remove", self.m_remove)):
            ttk.Button(side, text=txt, command=fn, width=12).pack(pady=2)
        ttk.Checkbutton(f, text="Number pad runs macros (turn off to type digits with it)",
                        variable=self.app._var("keypad_macros")).pack(anchor="w", pady=(6, 0))
        ttk.Label(f, text="^M means Enter: \"n^Ml n^M\" walks north then looks north. Text after the last ^M is left in "
                          "the input box for you to finish. Char = this character only; Def = every character. "
                          "Keys: F-keys (Shift/Ctrl too), the number pad, Ctrl+a letter (use \"Press a key…\"), "
                          "Home/End/Insert. A macro can send an alias (\"bs^M\"). F1, Ctrl+S, Page Up/Down are "
                          "MudPilot's own.",
                  style="Muted.TLabel", wraplength=760).pack(anchor="w")
        self.m_fill()
        return f

    def m_fill(self):
        self.m_tree.delete(*self.m_tree.get_children())
        for k, txt, use in self.s.macros.table():
            self.m_tree.insert("", "end", iid=k, values=(k, txt, use))

    def m_remove(self):
        s_ = self.m_tree.selection()
        if s_:
            use = self.m_tree.set(s_[0], "Use")
            self.s.macros.remove(s_[0], use)
            self.m_fill()

    def m_edit(self, new=False):
        key, txt, use = "F1", "", "Char"
        if not new:
            s_ = self.m_tree.selection()
            if not s_:
                return
            key, txt, use = s_[0], self.m_tree.set(s_[0], "Macro"), self.m_tree.set(s_[0], "Use")
        d = tk.Toplevel(self)
        d.title("Macro")
        d.transient(self.winfo_toplevel())
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        kv, tv, uv = tk.StringVar(value=key), tk.StringVar(value=txt), tk.StringVar(value=use)
        ttk.Label(fr, text="Key").grid(row=0, column=0, sticky="w")
        kr = ttk.Frame(fr)
        kr.grid(row=0, column=1, sticky="w", pady=3)
        from .macros import FREE_KEYS, RESERVED_KEYS
        ttk.Combobox(kr, textvariable=kv, values=FREE_KEYS, width=16).pack(side="left")
        cap = ttk.Button(kr, text="Press a key…")
        cap.pack(side="left", padx=6)

        def capture():
            # pMUD's Capture: the next key you press (with Ctrl / Shift) becomes the macro key
            import sys
            from .macros import key_name
            cap.configure(text="…press it now")
            def got(e):
                win = sys.platform.startswith("win")
                nm = key_name(e.keysym, e.keycode, e.state, win, extended=bool(e.state & 0x20000) if win else True)
                if e.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R"):
                    return "break"
                d.unbind("<KeyPress>")
                cap.configure(text="Press a key…")
                if nm in RESERVED_KEYS:
                    messagebox.showinfo("Macro", f"MudPilot already uses {nm} for {RESERVED_KEYS[nm]} — pick "
                                                 "another key.", parent=d)
                elif nm:
                    kv.set(nm)
                else:
                    messagebox.showinfo("Macro", f"'{e.keysym}' can't be a macro key (it types) — try F-keys, the "
                                                 "number pad, Ctrl+a letter, Home/End/Insert…", parent=d)
                return "break"
            d.bind("<KeyPress>", got)
            d.focus_set()
        cap.configure(command=capture)
        ttk.Label(fr, text="Macro").grid(row=1, column=0, sticky="w")
        ttk.Entry(fr, textvariable=tv, width=48).grid(row=1, column=1, sticky="we", pady=3)
        ttk.Label(fr, text="Use").grid(row=2, column=0, sticky="w")
        ttk.Combobox(fr, textvariable=uv, values=("Char", "Def"), width=8, state="readonly").grid(row=2, column=1, sticky="w")
        prev = ttk.Label(fr, text="", style="Muted.TLabel", wraplength=420, justify="left")
        prev.grid(row=3, column=0, columnspan=2, sticky="w", pady=6)
        def show(*a):
            sends, rest = macro_split(tv.get())
            prev.configure(text="Sends: " + (" | ".join(repr(x)[1:-1] or "(Enter)" for x in sends) or "nothing")
                           + (f"\nLeaves in the input box: {rest}" if rest else ""))
        tv.trace_add("write", show)
        show()
        def ok():
            if kv.get().strip() in RESERVED_KEYS and (new or kv.get().strip() != key):
                messagebox.showinfo("Macro", f"MudPilot already uses {kv.get().strip()} for "
                                             f"{RESERVED_KEYS[kv.get().strip()]} — pick another key.", parent=d)
                return
            if not new and (kv.get() != key or uv.get() != use):
                self.s.macros.remove(key, use)
            self.s.macros.set(kv.get(), tv.get(), uv.get())
            d.destroy()
            self.m_fill()
        b = ttk.Frame(fr)
        b.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.wait_window()

    # ------------------------------------------------------------ aliases (0.8.201, aliases.py)
    def _aliases(self, nb):
        f = ttk.Frame(nb, padding=8)
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        tf, self.a_tree = _tree(body, ("Alias", "Sends"), (110, 440))
        tf.pack(side="left", fill="both", expand=True)
        self.a_tree.bind("<Double-1>", lambda e: self.a_edit())
        side = ttk.Frame(body)
        side.pack(side="left", fill="y", padx=(8, 0))
        for txt, fn in (("New…", lambda: self.a_edit(new=True)), ("Modify…", self.a_edit), ("Remove", self.a_remove)):
            ttk.Button(side, text=txt, command=fn, width=12).pack(pady=2)
        ttk.Label(f, text="Type the alias as the first word on the command line: \"bs\" → bash door. ^M or ; starts the "
                          "next command. $1 $2… are the words you type after it, $* is all of them; with no $ they go on "
                          "the end (\"k orc\" with k = kill → kill orc). Only what you type or a macro key sends expands — "
                          "never @do or other remote commands. This character only.",
                  style="Muted.TLabel", wraplength=760).pack(anchor="w", pady=(6, 0))
        self.a_fill()
        return f

    def a_fill(self):
        self.a_tree.delete(*self.a_tree.get_children())
        for k, v in sorted((self.s.settings.aliases or {}).items(), key=lambda kv: kv[0].lower()):
            self.a_tree.insert("", "end", iid=k, values=(k, v))

    def a_save(self, old, name, text):
        """Add / change an alias. Returns why it can't be saved, or None."""
        from .aliases import name_problem
        name, text = (name or "").strip(), (text or "").strip()
        st = self.s.settings
        why = name_problem(name, st.aliases, old)
        if why:
            return why
        if not text:
            return "What should it send?"
        al = {k: v for k, v in (st.aliases or {}).items() if not (old and k.lower() == old.lower())}
        al[name] = text
        st.aliases = al
        st.save()
        self.a_fill()
        return None

    def a_remove(self):
        s_ = self.a_tree.selection()
        if s_:
            st = self.s.settings
            st.aliases = {k: v for k, v in (st.aliases or {}).items() if k != s_[0]}
            st.save()
            self.a_fill()

    def a_edit(self, new=False):
        from .aliases import expand
        name, txt = "", ""
        if not new:
            s_ = self.a_tree.selection()
            if not s_:
                return
            name, txt = s_[0], (self.s.settings.aliases or {}).get(s_[0], "")
        d = tk.Toplevel(self)
        d.title("Alias")
        d.transient(self.winfo_toplevel())
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        nv, tv, ex = tk.StringVar(value=name), tk.StringVar(value=txt), tk.StringVar(value="")
        ttk.Label(fr, text="Alias").grid(row=0, column=0, sticky="w")
        ttk.Entry(fr, textvariable=nv, width=16).grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(fr, text="Sends").grid(row=1, column=0, sticky="w")
        ttk.Entry(fr, textvariable=tv, width=48).grid(row=1, column=1, sticky="we", pady=3)
        ttk.Label(fr, text="Try it with").grid(row=2, column=0, sticky="w")
        ttk.Entry(fr, textvariable=ex, width=24).grid(row=2, column=1, sticky="w", pady=3)
        prev = ttk.Label(fr, text="", style="Muted.TLabel", wraplength=420, justify="left")
        prev.grid(row=3, column=0, columnspan=2, sticky="w", pady=6)

        def show(*a):
            n = nv.get().strip() or "alias"
            al = dict(self.s.settings.aliases or {})
            al = {k: v for k, v in al.items() if k.lower() not in (n.lower(), (name or "").lower())}
            al[n] = tv.get()
            typed = (n + " " + ex.get()).strip()
            out = expand(typed, al, self.s.settings.command_splitter or ";")
            prev.configure(text=f"\"{typed}\" sends: " + (" | ".join(out) or "nothing"))
        for v in (nv, tv, ex):
            v.trace_add("write", show)
        show()

        def ok():
            why = self.a_save(name or None, nv.get(), tv.get())
            if why:
                messagebox.showinfo("Alias", why, parent=d)
                return
            d.destroy()
        b = ttk.Frame(fr)
        b.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.wait_window()


class MonsterSpellDialog:
    """Game Data → Monsters → double-click: which spell to hit this monster with."""
    def __init__(self, parent, app, m):
        from .spelltune import family
        s, cfg = app.s, app.s.settings
        d = tk.Toplevel(parent)
        d.title(f"Spell for {m['name']}")
        d.transient(parent.winfo_toplevel())
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=m["name"], style="Title.TLabel" if False else "TLabel",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(fr, text=f"{int(m.get('exp') or 0):,} exp · {m.get('hp', '?')} HP · AC/DR {m.get('ac', '?')}/{m.get('dr', '?')}"
                           f" · MR {m.get('mr', '?')}", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        lvl = cfg.char_level or s.state.level
        sc = s.bot.spellcasting()
        rows = []
        for sp in s.spell_candidates():
            try:
                eff = spell_calc(sp, lvl, m, sc, cfg.spell_dmg_bonus).round_dmg
            except Exception:
                eff = 0
            rows.append((eff, sp))
        rows.sort(key=lambda r: -r[0])
        opts = ["(automatic — let MudPilot decide)", "Melee only (no spells)"]
        keys = [None, ""]
        for eff, sp in rows:
            short = sp.get("Short") or sp["Name"]
            opts.append(f"{short:<6} {sp['Name']} — ~{eff} dmg/round vs this one, {sp.get('ManaCost', '?')} mana")
            keys.append(short)
        name = m["name"].lower()
        fam = family(name)
        ms = cfg.monster_spells or {}
        cur = s.bot.monster_spell(m)
        var = tk.StringVar(value=opts[keys.index(cur)] if cur in keys else opts[0])
        ttk.Label(fr, text="Hit it with").pack(anchor="w")
        ttk.Combobox(fr, textvariable=var, values=opts, width=64, state="readonly").pack(anchor="w", pady=(2, 8))
        varis = tk.BooleanVar(value=bool((ms.get(fam) or {}).get("variants")) and name not in ms)
        if fam != name or any(family(x["name"]) == fam and x["name"].lower() != name
                              for x in s.world.monsters.values()):
            ttk.Checkbutton(fr, text=f"Same for every \"{fam}\" (large, nasty, tall … versions too)",
                            variable=varis).pack(anchor="w")
        if not rows:
            ttk.Label(fr, text="No attack spells known yet — MudPilot reads them from 'spells' when you're in the game.",
                      style="Muted.TLabel", wraplength=480).pack(anchor="w", pady=(6, 0))

        def ok():
            pick = keys[opts.index(var.get())] if var.get() in opts else None
            new = dict(cfg.monster_spells or {})
            new.pop(name, None)
            if varis.get():
                new.pop(fam, None)
                if pick is not None:
                    new[fam] = {"spell": pick, "variants": True}
            elif pick is not None:
                new[name] = {"spell": pick, "variants": False}
            cfg.monster_spells = new
            cfg.save()
            s.log(f"Monster spell: {m['name']} → " + ("automatic" if pick is None else (pick or "melee only"))
                  + (f" (all {fam})" if pick is not None and varis.get() else ""))
            d.destroy()
        b = ttk.Frame(fr)
        b.pack(anchor="e", pady=(12, 0))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.wait_window()


def remote_label(settings, name) -> str:
    """The Players list's @ column: 'all', '3/9', or blank."""
    from .remote import CATEGORIES
    perms = next((v for k, v in (settings.remote_players or {}).items() if k.lower() == name.lower()), None) or []
    have = len(set(perms) & set(CATEGORIES))
    return "all" if have == len(CATEGORIES) else (f"{have}/{len(CATEGORIES)}" if have else "")


class PlayerDialog:
    def __init__(self, parent, app, p):
        d = tk.Toplevel(parent)
        d.title("Player details")
        d.transient(parent.winfo_toplevel())
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        left = ttk.LabelFrame(fr, text="Details", padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.LabelFrame(fr, text="Last seen wearing", padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        mid = ttk.LabelFrame(fr, text="Allowed remote control", padding=8)
        mid.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        v = {k: tk.StringVar(value=str(p.get(k) or "")) for k in ("name", "surname", "class", "race", "gang", "notes")}
        rel = tk.StringVar(value=p.get("relationship", "Unknown"))
        dont = tk.BooleanVar(value=bool(p.get("dont_look")))
        alert = tk.BooleanVar(value=bool(p.get("alert_enter")))
        inv = tk.BooleanVar(value=bool(p.get("invite_if_seen")))
        joi = tk.BooleanVar(value=bool(p.get("join_if_invited")))
        nheal = tk.BooleanVar(value=bool(p.get("dont_heal")))
        trk = tk.BooleanVar(value=bool(p.get("auto_track")))
        w = app.s.world
        rows = (("Player name", "name", None), ("Surname", "surname", None),
                ("Class", "class", [c.get("Name") for c in w.classes.values()]),
                ("Race", "race", [r.get("Name") for r in w.races.values()]), ("Gang", "gang", None), ("Notes", "notes", None))
        for i, (lbl, k, vals) in enumerate(rows):
            ttk.Label(left, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            (ttk.Combobox(left, textvariable=v[k], values=vals, width=22) if vals else
             ttk.Entry(left, textvariable=v[k], width=24)).grid(row=i, column=1, sticky="w", pady=2)
        i = len(rows)
        ttk.Label(left, text="Relationship").grid(row=i, column=0, sticky="w", pady=2)
        ttk.Combobox(left, textvariable=rel, values=RELATIONSHIPS, width=12, state="readonly").grid(row=i, column=1, sticky="w")
        ttk.Checkbutton(left, text="Don't look (never look at this player)", variable=dont).grid(row=i + 1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(left, text="Alert when this player shows up (phone too)", variable=alert).grid(row=i + 2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(left, text="Auto-track: when they come on and I'm idle, track them down",
                        variable=trk).grid(row=i + 4, column=0, columnspan=2, sticky="w")
        pf = ttk.LabelFrame(fr, text="Party", padding=8)
        pf.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        ttk.Checkbutton(pf, text="Invite to party if seen", variable=inv).pack(anchor="w")
        ttk.Checkbutton(pf, text="Join party if invited", variable=joi).pack(anchor="w")
        ttk.Checkbutton(pf, text="Don't heal", variable=nheal).pack(anchor="w")
        who = " · ".join(x for x in (p.get("alignment"), p.get("title"),
                                     "gossip/auction off" if p.get("who_flag") == "x" else "") if x)
        ttk.Label(left, text=(f"who: {who}\n" if who else "") +
                  f"Last seen: {_ago(p.get('last_seen'))}\nLast online: {_ago(p.get('last_online'))}\n"
                  f"Last looked at: {_ago(p.get('last_looked'))}", style="Muted.TLabel", justify="left").grid(
            row=i + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        plf = ttk.LabelFrame(fr, text="Places seen (last 10)", padding=8)
        plf.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(10, 0), pady=(10, 0))
        pl = tk.Listbox(plf, width=46, height=8, background="#0f1318", foreground="#e0e6ef", borderwidth=0,
                        font=("Consolas", 10))
        pl.pack(fill="both", expand=True)
        for place, n, when, *rest in p.get("places") or []:
            pl.insert("end", f"{place}{f' ×{n}' if n > 1 else ''}  — {_ago(when)}")
        if not p.get("places"):
            pl.insert("end", "(not seen in a room yet)")
        lb = tk.Listbox(right, width=46, height=16, background="#0f1318", foreground="#e0e6ef", borderwidth=0,
                        font=("Consolas", 10))
        lb.pack(fill="both", expand=True)
        for item, slot in p.get("wearing") or []:
            lb.insert("end", f"{item:<30} ({slot})")
        if not p.get("wearing"):
            lb.insert("end", "(nothing seen yet — or shadow form)")
        from .remote import CATEGORIES
        perms = set((app.s.settings.remote_players or {}).get(p["name"], []))
        pv = {}
        for j, (cat, label) in enumerate(CATEGORIES.items() if isinstance(CATEGORIES, dict) else [(c, c) for c in CATEGORIES]):
            pv[cat] = tk.BooleanVar(value=cat in perms)
            ttk.Checkbutton(mid, text=label if isinstance(label, str) else cat, variable=pv[cat]).grid(
                row=j // 2, column=j % 2, sticky="w")

        def all_none():
            on = not all(b.get() for b in pv.values())
            for b in pv.values():
                b.set(on)
        ttk.Button(mid, text="All / None", command=all_none).grid(row=len(pv) // 2 + 1, column=0, sticky="w", pady=(4, 0))

        def ok():
            for k in ("surname", "class", "race", "gang", "notes"):
                p[k] = v[k].get().strip()
            p["relationship"] = rel.get()
            p["dont_look"] = dont.get()
            p["alert_enter"] = alert.get()
            p["auto_track"] = trk.get()
            p["invite_if_seen"], p["join_if_invited"], p["dont_heal"] = inv.get(), joi.get(), nheal.get()
            st = app.s.settings
            chosen = [c for c, b in pv.items() if b.get()]
            rp = dict(st.remote_players or {})
            if chosen:
                rp[p["name"]] = chosen
            else:
                rp.pop(p["name"], None)
            st.remote_players = rp
            st.save()
            d.destroy()
        b = ttk.Frame(fr)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Accent.TButton", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")
        d.wait_window()


# ----------------------------------------------------------------- spell book
class SpellBookPane(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.show_all = tk.BooleanVar(value=False)
        self.level = tk.StringVar(value=str(self.s.state.level or self.s.settings.char_level or 1))
        ttk.Label(top, text="Level").pack(side="left")
        ttk.Spinbox(top, from_=1, to=255, width=5, textvariable=self.level, command=self.fill).pack(side="left", padx=4)
        ttk.Checkbutton(top, text="Show every spell my class can learn", variable=self.show_all,
                        command=self.fill).pack(side="left", padx=10)
        ttk.Button(top, text="Re-read from game", command=self.reread).pack(side="right")
        cols = ("Short", "Name", "Lvl", "Mana", "Kind", "Element", "Damage", "Avg", "Dmg/mana", "Status")
        tf, self.tree = _tree(self, cols, (55, 180, 40, 45, 70, 70, 85, 55, 70, 120), height=18)
        tf.pack(fill="both", expand=True, pady=6)
        self.tree.tag_configure("attack", foreground="#e6b450")
        self.tree.tag_configure("off", foreground=MUTED)
        self.note = ttk.Label(self, text="", style="Muted.TLabel", wraplength=820, justify="left")
        self.note.pack(anchor="w")
        self.fill()

    def reread(self):
        if self.s.telnet.connected:
            self.s.bot._spells_asked = False
            self.s.send("spells", from_bot=True)
            self.after(2500, self.fill)

    def fill(self):
        from .spells import class_spells
        self.tree.delete(*self.tree.get_children())
        try:
            lvl = int(self.level.get())
        except ValueError:
            lvl = 1
        known = {sp["Number"]: sp for sp in self.s.known_spell_dicts()}
        rows = dict(known)
        if self.show_all or not known:
            w = self.s.world
            cname = (self.s.state.char_class or self.s.settings.char_class or "").lower()
            cls = next((k for k, v in w.classes.items() if v.get("Name", "").lower() == cname), 0)
            for sp in class_spells(w, cls, lvl) if cls else []:
                rows.setdefault(sp["Number"], sp)
        refused = self.s.spellbook.refused
        for num, sp in sorted(rows.items(), key=lambda kv: (int(kv[1].get("ReqLevel") or 0), kv[1].get("Name", ""))):
            atk = is_attack_spell(sp)
            dmg = avg = per = ""
            if atk:
                c = spell_calc(sp, lvl)
                dmg, avg = f"{c.min}-{c.max}", str(c.per_cast)
                per = f"{c.per_cast / max(int(sp.get('ManaCost') or 1), 1):.1f}"
            status = "won't cast" if num in refused else ("known" if num in known else "can learn")
            self.tree.insert("", "end", tags=("off" if num not in known else "attack" if atk else "",), values=(
                sp.get("Short", ""), sp.get("Name", ""), sp.get("ReqLevel", ""), sp.get("ManaCost", ""),
                spell_kind(sp) or ("" if not atk else "attack"),
                ELEMENTS.get(int(sp.get("AttType") or -1), "") if atk else "", dmg, avg, per, status))
        missing = self.s.unknown_spells()
        self.note.configure(text=(f"{len(known)} spells read from the game's spell list. " if known else
                                  "The game's spell list hasn't been read yet — showing what your class can learn. ")
                            + "Gold = attack spells the auto-picker can use."
                            + (f"  Not in MME data: {', '.join(missing)}." if missing else ""))


# ----------------------------------------------------------------- CP / exp calculator
class ExpCalcPane(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        w = self.s.world
        st = self.s.state
        self.classes = [c.get("Name") for _k, c in sorted(w.classes.items())]
        self.races = [r.get("Name") for _k, r in sorted(w.races.items())]
        self.cls = tk.StringVar(value=st.char_class or self.s.settings.char_class or (self.classes[0] if self.classes else ""))
        self.race = tk.StringVar(value=st.race or (self.races[0] if self.races else ""))
        self.level = tk.StringVar(value=str(st.level or self.s.settings.char_level or 1))
        self.gmud = tk.BooleanVar(value=self.s.settings.exp_formula == "greatermud")
        top = ttk.Frame(self)
        top.pack(fill="x")
        for lbl, var, vals in (("Class", self.cls, self.classes), ("Race", self.race, self.races)):
            ttk.Label(top, text=lbl).pack(side="left")
            cb = ttk.Combobox(top, textvariable=var, values=vals, width=12, state="readonly")
            cb.pack(side="left", padx=(4, 10))
            cb.bind("<<ComboboxSelected>>", lambda e: self.fill())
        ttk.Label(top, text="Level").pack(side="left")
        ttk.Spinbox(top, from_=1, to=255, width=5, textvariable=self.level, command=self.fill).pack(side="left", padx=4)
        ttk.Checkbutton(top, text="GreaterMUD board", variable=self.gmud, command=self.fill).pack(side="left", padx=10)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, pady=8)
        ef = ttk.Frame(nb, padding=6)
        nb.add(ef, text="Experience")
        self.summary = ttk.Label(ef, text="", style="Head.TLabel", justify="left")
        self.summary.pack(anchor="w", pady=(0, 6))
        tf, self.tree = _tree(ef, ("Level", "Total exp", "This level", "From now"), (60, 150, 150, 150), height=14)
        tf.pack(fill="both", expand=True)
        self.tree.tag_configure("now", foreground="#5cff7a")
        cf = ttk.Frame(nb, padding=8)
        nb.add(cf, text="Character points")
        self.stat_vars = {}
        grid = ttk.Frame(cf)
        grid.pack(anchor="w")
        for j, h in enumerate(("Stat", "Want", "Race min", "Race max", "CP cost")):
            ttk.Label(grid, text=h, style="Muted.TLabel").grid(row=0, column=j, padx=6, sticky="w")
        self.cost_lbls = {}
        for i, (name, k) in enumerate(X.STATS, start=1):
            ttk.Label(grid, text=name).grid(row=i, column=0, sticky="w", padx=6)
            v = tk.StringVar(value="")
            self.stat_vars[k] = v
            ttk.Spinbox(grid, from_=0, to=255, width=5, textvariable=v, command=self.fill_cp).grid(row=i, column=1, padx=6)
            v.trace_add("write", lambda *a: self.fill_cp())
            self.cost_lbls[k] = [ttk.Label(grid, text=""), ttk.Label(grid, text=""), ttk.Label(grid, text="")]
            for j, l in enumerate(self.cost_lbls[k]):
                l.grid(row=i, column=2 + j, padx=6, sticky="w")
        self.cp_sum = ttk.Label(cf, text="", style="Head.TLabel", justify="left")
        self.cp_sum.pack(anchor="w", pady=10)
        pr = ttk.Frame(cf)
        pr.pack(anchor="w", pady=(0, 8))
        ttk.Button(pr, text="Save as CP plan row for this level", command=self.save_plan_row).pack(side="left")
        self.plan_lbl = ttk.Label(pr, text="", style="Muted.TLabel", wraplength=520, justify="left")
        self.plan_lbl.pack(side="left", padx=8)
        self._show_plan()
        ttk.Label(cf, text="Raising a stat costs 1 CP per point for the first 10 over the race minimum, 2 for the next 10, "
                           "and so on. You start with the race's base CP and gain 10 per level (+5 more every 10 levels).",
                  style="Muted.TLabel", wraplength=640, justify="left").pack(anchor="w")
        if st.strength:
            self.stat_vars["STR"].set(str(st.strength))
        if getattr(st, "agility", 0):
            self.stat_vars["AGL"].set(str(st.agility))
        self.fill()

    def _lvl(self):
        try:
            return max(1, int(self.level.get()))
        except ValueError:
            return 1

    def save_plan_row(self):
        """0.8.200: the Want column becomes the auto-train CP plan's row for this level (Loot tab → Training: 'After
        training, spend CP by my CP plan'). A row is the target for that level; a later row wins."""
        from .training import parse_plan, format_plan
        stats = {}
        for k, v in self.stat_vars.items():
            try:
                if int(v.get()) > 0:
                    stats[k] = int(v.get())
            except ValueError:
                pass
        if not stats:
            self.plan_lbl.configure(text="Fill in the Want column first.")
            return
        rows = [r for r in parse_plan(self.s.settings.train_stats_plan) if r[0] != self._lvl()]
        rows.append((self._lvl(), stats))
        self.s.settings.train_stats_plan = format_plan(sorted(rows, key=lambda r: r[0]))
        v = (getattr(self.app, "_vars", None) or {}).get("train_stats_plan")
        if v is not None:
            v.set(self.s.settings.train_stats_plan)     # (the Loot tab's box shows it too)
        self.s.settings.save()
        self._show_plan()

    def _show_plan(self):
        plan = (self.s.settings.train_stats_plan or "").strip()
        self.plan_lbl.configure(text=f"CP plan: {plan}" if plan else "No CP plan yet (Loot tab → Training uses it).")

    def fill(self):
        self.s.settings.exp_formula = "greatermud" if self.gmud.get() else "stock"
        self.tree.delete(*self.tree.get_children())
        lvl = self._lvl()
        rows = X.exp_table(self.s.world, self.cls.get(), self.race.get(), upto=max(lvl + 25, 75), greatermud=self.gmud.get())
        if not rows:
            self.summary.configure(text="Pick a class and race (needs this board's MME data).")
            return
        cur_total = next((t for l, t, _ in rows if l == lvl), 0)
        st = self.s.state
        exp_now = st.exp_total if st.exp_total and st.level == lvl else cur_total
        for l, tot, this in rows:
            if l < max(1, lvl - 3):
                continue
            self.tree.insert("", "end", tags=("now",) if l == lvl else (), values=(
                l, f"{tot:,}", f"{this:,}", f"{max(tot - exp_now, 0):,}" if l > lvl else ""))
        nxt = next((t for l, t, _ in rows if l == lvl + 1), None)
        chart = X.chart_for(self.s.world, self.cls.get(), self.race.get())
        rate = self.s.stats.exp_rate()
        txt = f"Exp chart {chart}%   ·   level {lvl + 1} at {nxt:,} total" if nxt else f"Exp chart {chart}%"
        if nxt and exp_now:
            need = max(nxt - exp_now, 0)
            txt += f"\nNeeded for level {lvl + 1}: {need:,}"
            if rate:
                txt += f"  (about {need / rate:.1f} h at your current {int(rate):,} exp/h)"
        self.summary.configure(text=txt)
        self.fill_cp()

    def fill_cp(self):
        if not hasattr(self, "cp_sum"):
            return
        stats = {}
        for k, v in self.stat_vars.items():
            try:
                stats[k] = int(v.get())
            except ValueError:
                pass
        plan = X.cp_plan(self.s.world, self.race.get(), stats, self._lvl(), self.gmud.get())
        if not plan:
            self.cp_sum.configure(text="Pick a race.")
            return
        for k, info in plan["stats"].items():
            a, b, c = self.cost_lbls[k]
            a.configure(text=str(info["min"]))
            b.configure(text=str(info["max"]))
            c.configure(text=f"{info['cost']}" + ("  over race max!" if info["over"] else ""))
        left = plan["left"]
        self.cp_sum.configure(text=f"CP used: {plan['total']}   ·   CP at level {self._lvl()}: {plan['available']}"
                                   f"   ·   {'left over' if left >= 0 else 'short'}: {abs(left)}\n"
                                   f"Level needed for these stats: {plan['level_needed']}")
