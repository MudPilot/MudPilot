"""The in-app help book (Help → Help topics, 0.8.200). Kept as text in a module so the compiled build carries it.
Each topic: (title, body). Plain text; a line starting with '• ' is a bullet. The Remote @commands topic is built
from remote.HELP when the window opens, so it never goes out of date."""

TOPICS = [
    ("Getting started", """\
MudPilot plays MajorMUD the way MegaMUD does, with MME (MajorMUD Explorer) built in, so it always knows the exact map and room number you're in.

• File → Import MME database (.mdb): pick your board's MME data file. Re-import when the board's data changes.
• Character → Import MegaMUD character (.ini): your MegaMUD settings, mapped across. Untick anything you don't want.
• File → Import MegaMUD paths folder: every .mp path and loop, matched step by step to MME rooms.
• Connect: host, port, User-ID and password. Tick Save password to keep it in Windows Credential Manager.

Want to try it without risking a character? Connection → Start practice server runs a fake MajorMUD built from your MME data.

New to it? Help → Step-by-step guides walks you through first-run setup, a loop, a party, auto-get/stash and phone alerts, pointing at each thing to click."""),

    ("Paths, loops and Go to", """\
• Paths tab: Walk from here, Go to start then run, or Run as loop. Your MegaMUD .mp files work as they are.
• Go to: type a room name, a monster, a shop or a map/room (e.g. 14/6534), or double-click the map. MudPilot plans the way itself: through doors it (or a party member) can pick or bash, fetching keys, buying rafts or other things the way needs, and going round water when the party has no raft.
• Path builder (Window menu): build paths and loops from the map without walking them, saved as normal .mp files.
• Record Path / Record Loop on the map: walk it once and save it.
• Rego carries on with what you were doing. Moving by hand (keypad, typing a direction) pauses the loop until you click Rego.
• Dark rooms: Settings → Other → "Ready a carried light…" lights a torch or lantern from your pack before the walk goes into a room too dark to see in, puts it away where it's light enough, lights a spare when one burns out, and buys more at the end of a lap when you run short.
• Lair camping: Paths → Camp lairs. Mark the lairs (Add this room, type a map/room, or Game Data → Rooms → Add to Camp lairs) and Start camping. MudPilot waits in the room next to each lair and steps in as it comes back — never early — fights, loots and goes on to the next one: the closest that's back, else the one back soonest. Respawn times come from MME's room Delay (Stock: from the last kill; Paradigm: from your last entry) until MudPilot has timed a lair itself. Bank, stash, sell and train trips go between lairs and come back to camping; a dropped line carries on with the clocks kept. Stop (or '@camp stop') ends it; it never starts on a follower ('@camp start' / '@camp list' from a party member)."""),

    ("Combat and spells", """\
• After login MudPilot reads your spell list ('spells'): there's no spell list to set up.
• For every monster it works out each attack spell's damage with MME's own formula (resists, anti-magic, magical monsters) and casts the best one, skipping spells that would do under 75% of their rating. It learns from the damage you really do.
• Attack only if monsters ≥ / ≤ a count, never-attack and only-attack lists, and a spell per monster (Game Data → Monsters).
• Area spells from N monsters (Combat tab), a pre-attack spell, max casts per fight.
• Your weapon (or fists) having no effect on a monster stops it meleeing that one; spells still go.
• New spells: Spells tab → "After a level-up, buy and read scrolls…" goes to the shops that stock scrolls for spells you can now learn, buys and reads them (lowest level first, with the cash you carry), then carries on. "Look for scrolls now" does it once."""),

    ("Training", """\
• Settings → Loot → Training. Every switch is off until you tick it.
• Train levels automatically: reaching the exp doesn't level you; 'train' at a trainer does. Once a level is banked, at the end of a lap MudPilot walks to the nearest trainer for your class and level (MME's trainers), gets the fee from the bank if you're short, trains (again while more levels are banked) and goes back to the loop. Keep N levels banked holds some back; "don't train above level" caps it (0 = no cap).
• Spend CP by my CP plan: after training, your plan's target stats for the new level are typed into 'train stats' (plan e.g. 10: STR 60 AGL 50; 20: STR 70 — or Game Data → Exp/CP → Save as CP plan row). While that form is up nothing automatic is sent. The form is read back before saving; if anything isn't exactly as typed it leaves with QUIT, so no CP is spent wrongly. Not enough CP for the whole row: stats are raised in plan order as far as the CP goes.
• Train together with my MudPilot party: the leader asks its MudPilot members (@ptrain) who has a level banked, takes everyone to their trainers (members first, its own last), invites everyone back, then carries on. A member never sets off by itself — it trains when its leader says so. A member whose purse doesn't cover its fee is left out of that trip.
• Never mid-fight, never with Hands off on; Stop ends it."""),

    ("Blesses and mana regen", """\
• Bless tab: each rule recasts a spell on a timer, when its wear-off message shows, or when an ability check (abil 145 and so on) is off target.
• Mana regen ▾ makes a ready rule for mana flux, nature tap or serenity. These roll a random ManaRegen each cast; MudPilot rerolls until the roll reaches your target, up to a number of casts in a row, never below a mana floor.
• Window → Stat & mana-regen breakpoints shows the rolls where your mana tick actually goes up. Set the reroll target on one of those: anything in between buys no extra mana."""),

    ("Resting and healing", """\
• Combat / Health tabs: rest below an HP %, meditate below a mana %, heal and run at an HP %.
• Pre-rest / post-rest and pre-med / post-med gear swaps, as in MegaMUD.
• In a party the leader waits for hurt members; followers send @wait with a reason and @ok when ready. A healer checks the party ('par') straight after a heal so it can heal again quickly.
• Poison, blindness, disease and being held get their cures (Spells tab). "You are too sick to rest!" holds rests off instead of spamming them."""),

    ("Loot, Auto-get and Auto-stash", """\
• Loot tab: which coins to pick up (and when to stop picking up copper and silver), items to loot, never-get items.
• Game Data → Items: select items and click Auto-get, Auto-get up to N, Never get, or Normal — like MegaMUD's item flags.
• Auto-stash (Game Data → Items): the item is picked up AND hidden in your stash room. Use it for things you sell, so you don't walk round heavy. Items you auto-get without Auto-stash (rares) stay in your pack.
• Stash room: the Loot tab's default, or one per loop (Paths → More → Stash room for this loop). Type it as map/room, e.g. 14/6534, or stand there and click 'Use the room I'm in'. The coins you tick are hidden there too.
• A party member: stand in the stash room and telepath them '@stash'. They remember it and hide their own Auto-stash items there every time the party passes.
• '@collect <item>' and '@stash <item>' set a character's Auto-get / Auto-stash from anywhere.
• Too heavy for you? The strongest party member standing with you picks it up, and Auto-stash items they picked up for you get hidden in your stash room too."""),

    ("Party play", """\
• Party tab: party heals (minor, major, area), heal-first players, party blesses ({name} = each member), wait for hurt members, 'par' every few seconds.
• Window → Party (Alt+P) shows everyone's HP and mana bars.
• Two or more MudPilots in a party share their strength and picklocks, so routes are planned around the whole party: the best picker picks, the strongest bashes. Quest flags are checked for everyone before going a way a flag decides.
• Paths tab → right-click a path → Send to a party member: the path goes to their MudPilot by telepath.
• Followers rest together with the leader and come back (@comeback) if the party breaks."""),

    ("Boss hunting", """\
• Bosses tab: tick the bosses to hunt. MudPilot keeps their respawn clocks (shared with pMUD through @spawn) and goes for each one when it's due, then back to your loop.
• Hunt now (or telepath '@hunt <boss>'): goes straight away, checking every lair the boss can be in, nearest first, and picks up its drops (chests left alone).
• '@hunt' on its own lists what's being hunted; '@hunt off' stops hunting, '@hunt on' turns it back on.
• '@timer <boss>' tells you a boss's clock."""),

    ("PvP safety", """\
• Alt+H hangs up instantly, no questions.
• Settings → PvP: hang up when a player attacks you, below an HP %, when a player you marked Enemy shows up (or any player), and stay offline for N minutes after.
• Listen: on "You hear movement to the …" MudPilot looks that way once.
• '@pvp on' from a party member: fight back and defend the party instead of hanging up (the low-HP hang-up still works).
• Hang-up item pickup (Settings → PvP): on a board that drops items when you hang up in a fight, tick it and set how many it drops. Back in, the walk waits while MudPilot reads 'i', looks at the floor of the same room and gets back what's missing (never more than the board drops), then puts worn gear back on. Paradigm doesn't drop items on a hang-up (only HP), so it's off there."""),

    ("Phone alerts and the watchdog", """\
• Settings → Phone alerts: install the free ntfy app, pick a secret topic, and MudPilot sends alerts there: hang-ups, attacks by players, deaths, a stranger's tracks, the loop stopping, the line dropping, a boss due back.
• Tick 'Let me send status / stop / hang up from the ntfy app' to control it from your phone.
• The stuck watchdog alerts you when a loop makes no progress for a while.
• Keep the topic secret: anyone who knows it could read your alerts and send those commands."""),

    ("Calculators and game data", """\
• Inventory calculator: best armour and weapons per slot for AC, DR, mana regen, HP, spellcasting or a resist, from MME's items and rules.
• CP / Exp calculator: exp per level, time to level, and what a set of stats costs.
• Combat calculator: you against a monster.
• Stat & mana-regen breakpoints: the stat values where each derived value goes up, and the ManaRgn rolls where your mana tick goes up.
• Spell book: every spell you know, with damage and damage per mana.
• Game Data (Alt+D): players, monsters, items, spells, rooms, paths and macros, all searchable."""),

    ("Updates", """\
• MudPilot checks GitHub for a newer version when it opens (Settings → General to turn it off; nothing about you is sent). Help → Check for updates asks now.
• When there's one, a bar shows: What's new (the release notes), Update (downloads it; a restart installs it), or Skip this version.
• Updates install the next time MudPilot opens. Your settings, paths and logs are never touched."""),

    ("Reporting a problem", """\
Help → Report a problem (or the toolbar button) sends the developer your logs and what MudPilot was doing, straight from the app. Say in a line what went wrong. Passwords are never included.

Copy diagnostics (Ctrl+Shift+D) puts a summary on the clipboard if someone helping you asks for it."""),

    ("Keys", """\
• Numpad 8/2/4/6/7/9/1/3 move, + up, − down, 5 looks. Enter on an empty line looks.
• Esc stops the bot. Alt+H hangs up. Alt+P party window. Alt+D game data. Alt+B back-scroll / find. Ctrl+S settings.
• Note: the numpad − key is 'down' — tapping it by accident pauses the loop."""),

    ("Credits", """\nBig thanks to syntax53 for MajorMUD Explorer (MME) — github.com/syntax53/MMUD-Explorer.

• MudPilot's map, room, monster, item, shop and spell data come from MME's databases.
• Many of its game calculations work the way MME works them: spell and melee damage, who can use an item, which spells a class learns, the exp tables and the monster attack simulator.
• Used with his blessing."""),
]


def all_topics():
    """The topics plus one built from the live @command list."""
    out = list(TOPICS)
    try:
        from .remote import HELP, CATEGORY_NAMES
    except ImportError:
        try:
            from .remote import HELP
            CATEGORY_NAMES = {}
        except ImportError:
            return out
    lines = ["Party members and friends control you with MegaMUD's @commands, by telepath ('/You @health'). Nobody "
             "can unless you add them on the Remote tab and tick what they may do. ★ = MudPilot only.", ""]
    for cat, cmd, what, example in HELP:
        lines.append(f"• {cmd} — {what}   e.g. {example}")
    out.insert(7, ("Remote @commands", "\n".join(lines)))
    return out


def make_pane(parent, app=None):
    import tkinter as tk
    from tkinter import ttk
    topics = all_topics()
    f = ttk.Frame(parent, padding=8)
    top = ttk.Frame(f)
    top.pack(fill="x")
    ttk.Label(top, text="Search").pack(side="left")
    q = tk.StringVar()
    ent = ttk.Entry(top, textvariable=q, width=30)
    ent.pack(side="left", padx=6)
    hits = ttk.Label(top, text="", style="Muted.TLabel")
    hits.pack(side="left", padx=6)
    if app is not None and hasattr(app, "open_guides"):      # (0.8.201) the walkthroughs that point at the screen
        ttk.Button(top, text="Step-by-step guides…", command=app.open_guides).pack(side="right")
    body = ttk.Frame(f)
    body.pack(fill="both", expand=True, pady=(6, 0))
    lb = tk.Listbox(body, width=28, activestyle="none", exportselection=False)
    lb.pack(side="left", fill="y")
    tx = tk.Text(body, wrap="word", padx=12, pady=8, relief="flat")
    tx.pack(side="left", fill="both", expand=True)
    try:
        from .app import PANEL
        lb.configure(background=PANEL, foreground="#e6e6e6", selectbackground="#3d66a8", highlightthickness=0, bd=0)
        tx.configure(background=PANEL, foreground="#e6e6e6", insertbackground="#e6e6e6")
    except Exception:
        pass
    tx.tag_configure("h", font=("Segoe UI", 13, "bold"), spacing3=6)
    tx.tag_configure("hit", background="#5a4a12")
    shown = []

    def show(i):
        if not (0 <= i < len(shown)):
            return
        title, text = shown[i]
        tx.configure(state="normal")
        tx.delete("1.0", "end")
        tx.insert("end", title + "\n", "h")
        tx.insert("end", text)
        w = q.get().strip()
        if w:
            start = "1.0"
            while True:
                pos = tx.search(w, start, "end", nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(w)}c"
                tx.tag_add("hit", pos, end)
                start = end
            first = tx.search(w, "2.0", "end", nocase=True)
            if first:
                tx.see(first)
        tx.configure(state="disabled")

    def refill(*_a):
        w = q.get().strip().lower()
        shown[:] = [t for t in topics if not w or w in t[0].lower() or w in t[1].lower()]
        lb.delete(0, "end")
        for title, _t in shown:
            lb.insert("end", title)
        hits.configure(text=(f"{len(shown)} topic{'s' if len(shown) != 1 else ''}" if w else ""))
        if shown:
            lb.selection_set(0)
            show(0)
        else:
            tx.configure(state="normal"); tx.delete("1.0", "end"); tx.insert("end", "Nothing matches."); tx.configure(state="disabled")
    lb.bind("<<ListboxSelect>>", lambda e: show(lb.curselection()[0]) if lb.curselection() else None)
    q.trace_add("write", refill)
    refill()
    ent.focus_set()
    return f
