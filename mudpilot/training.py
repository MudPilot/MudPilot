"""Auto-train: level up at a trainer by itself, optionally spend CP by your plan, optionally with the whole party.

0.8.200, from the MudPlay review (Dan: build it off by default, players tune their own settings). Three switches on
the Loot tab, each off until you tick it:
  * Train levels (auto_train). The game never levels you by itself: reaching the exp prints nothing and the level
    waits for 'train' at a trainer. At the end of a loop lap, once a level is banked (the 'exp' line, topped up with
    every "You gain N experience."), MudPilot walks to the nearest trainer that serves this class and level (MME
    Shops, ShopType 8 — ClassRest 0 or ours, the level band, MaxLVL 999 rows are placeholders), checks the purse
    (the bank first if it's short), sends 'train' — again while more levels are banked — and goes back to the loop.
    "Keep N levels banked" holds some back; "don't train above level N" caps it.
  * Train stats with the CP plan (train_stats). After a train, the plan's row for the new level (Loot tab, or Game
    Data → Exp/CP → "Save as CP plan row") is typed into 'train stats'. CP can't be unspent, so: every automatic
    command is held from the moment 'train stats' goes out until the form is gone (a 'par' once landed in the Family
    Name box in MudPlay), the six stats and CP Left are read off the screen, the 11 field payloads go ~200 ms
    apart, and the form is read again before the final Enter: anything not exactly as typed → QUIT, never SAVE.
  * Party training (party_train). A leader with MudPilot members asks who has levels banked (@ptrain), takes the
    party to each member's trainer (members first, its own last), orders each one to train, re-invites them (training
    drops a follower; the leader's own train disbands the party) and only then goes back to the loop. Members never
    start a trip themselves.

The @ptrain wire format (a subset of MudPlay's; telepaths between party MudPilots):
    member → leader   @ptrain st s=<r|w|b|o> l=<level> c=<class#> n=<levels banked to train> cash=<copper>
                      (r ready, w nothing banked, b can't now, o switched off) — on a change and on 'ask'
    leader → member   @ptrain ask                    tell me your st
                      @ptrain trip on|off            a training trip: hold @comeback / leader-gone alarms until off
                      @ptrain train <level> <map>/<room>   train now, up to that level, in that room (you're there)
    member → leader   @ptrain done <levels> [why]    finished (the leader re-invites)
Left out on purpose (Dan can ask for it): MudPlay's coin sharing between members (@ptrain give / with) and its quorum
and power-leveller rules. A member whose purse doesn't cover its own fee is left out of the trip and says so.
Never mid-fight, never while Hands off is on, and your Stop ends it.
"""
from __future__ import annotations

import re
import time

from . import expcalc as X
from .scrolls import class_num, strip_prompt

TRAINER_TYPE = 8                 # MME Shops.ShopType 8 = a trainer
PLACEHOLDER_MAX = 999            # MaxLVL 999 rows are MME placeholders (the Sysop Trainer), not real trainers

# ---- the game's lines (Stock and Paradigm). A prompt can come first on a line; it's stripped before matching.
SUCCESS_STOCK_RE = re.compile(r"^You hand over .+ and you receive training to attain level (\d+)", re.I)
SUCCESS_PARA_RE = re.compile(r"^You hand over .+ to train to the next level", re.I)   # no level: it's current + 1
REFUSALS = (      # in the order Stock tests them
    ("room", re.compile(r"^You must be in an appropriate training room to train!", re.I)),
    ("unsuitable", re.compile(r"^This shop is not suitable for your training\.", re.I)),
    ("too_low", re.compile(r"^You have not progressed far enough to use the training provided here\.", re.I)),
    ("too_high", re.compile(r"^You have progressed too far to use the training provided here\.", re.I)),
    ("maxed", re.compile(r"^You may not train any further\.\s+Please contact your sysop", re.I)),
    ("no_exp", re.compile(r"^You do not have the required experience to train yet!", re.I)),
    ("no_money", re.compile(r"^You do not have the money required for your training\.", re.I)),
)
STATS_REFUSALS = (
    re.compile(r"^Your stats are unnaturally altered!\s+You may not train stats now\.", re.I),
    re.compile(r"^You may not train your stats here!", re.I),
    re.compile(r"^You may not do any training while in tournament mode!", re.I),
    # Paradigm refuses away from a trainer too, wording not recorded: anything that says we may not train
    re.compile(r"^You (?:may not|can ?not|can't) (?:do any )?train", re.I),
)
VALUE_REFUSAL_RE = re.compile(r"^(?:(?:Strength|Intellect|Willpower|Agility|Health|Charm) may not be (?:lower|higher) "
                              r"than \d+|You may not assign that much to \w+)", re.I)
SAVED_RE = re.compile(r"^Training complete!\s+Stats updated", re.I)
ENTERED_RE = re.compile(r"^([A-Z][a-z]+) just entered the Realm", re.I)
JOINED_RE = re.compile(r"^(\w+) (?:started to follow|is now following) you\b", re.I)

# ---- the train stats form, read off the screen ("Strength   (  55 to  160)   133" … "CP Left:   26")
FORM_LABELS = ("Strength", "Intellect", "Willpower", "Agility", "Health", "Charm")
STAT_KEYS = ("STR", "INT", "WIL", "AGL", "HEA", "CHM")
STAT_ROW_RE = re.compile(r"\b(Strength|Intellect|Willpower|Agility|Health|Charm)\s*\(\s*(\d+)\s+to\s+(\d+)\s*\)\s*(\d+)")
CP_LEFT_RE = re.compile(r"\bCP Left:\s*(\d+)")
EXIT_RE = re.compile(r"\bExit:\s*(SAVE|EDIT|QUIT)\b")

# ---- timings
EXP_SECS = 4.0          # 'exp' / 'i' answers before deciding
TRAIN_SECS = 8.0        # a 'train' answer (MudPlay's 8 s)
FORM_WAIT_SECS = 10.0   # 'train stats' → the form (or a refusal)
KEY_GAP = 0.2           # between form keystrokes (~200 ms)
SETTLE_SECS = 0.45      # the screen unchanged this long = the redraw is done
VERIFY_MAX_SECS = 3.0   # …but read it by then anyway
SPACE_SECS = 0.6        # after each Space on Exit, before reading what it shows
CLOSE_SECS = 15.0       # the final Enter → a prompt
MAX_SPACES = 4          # Space cycles SAVE / EDIT / QUIT: never more than this many tries
DONE_SECS = 150.0       # a member's whole train (and its form) before the leader gives up on it
REJOIN_SECS = 90.0      # waiting at a stop for everyone to be back in the party
ASK_GRACE = 20.0        # a member must have been with us this long before the leader asks @ptrain ask
TRIP_HOLD_SECS = 900    # a member's 'trip on' hold ends by itself after this (a leader that never says off)
MUTE_SECS = 1800        # no trainer / no money: not again for half an hour


def fee(level, markup=0) -> int:
    """Copper to train from `level` to the next: Fix(level*5*(markup+100)/100)*10 (MudPlay's TrainCopper).
    Level 7 at 0% markup = 350 copper."""
    return int(int(level) * 5 * (int(markup or 0) + 100) / 100) * 10


def serves(sh, cls, level, stats_only=False) -> bool:
    """Does this MME shop row train this class at this level? A trainer, in the game, not a MaxLVL 999 placeholder,
    ClassRest 0 or ours; the band: it serves unless MinLVL > level+1 or MaxLVL <= level (the levels it trains TO).
    For stats only the band doesn't matter (MudPlay once walked across the map for a band it didn't need)."""
    if not sh or int(sh.get("type") or 0) != TRAINER_TYPE or sh.get("in_game") == 0 or not sh.get("rooms"):
        return False
    mx, mn = int(sh.get("max_lvl") or 0), int(sh.get("min_lvl") or 0)
    if mx == PLACEHOLDER_MAX:
        return False
    rest = int(sh.get("class") or 0)
    if rest and rest != int(cls or 0):
        return False
    if stats_only:
        return True
    return not (mn > int(level) + 1 or mx <= int(level))


def trainers(world, cls, level, stats_only=False) -> list:
    """[(room, shop number, markup)] of every trainer room that serves us."""
    out = []
    for sn, sh in (getattr(world, "shops", None) or {}).items():
        if serves(sh, cls, level, stats_only):
            for r in sh.get("rooms") or []:
                out.append((tuple(r), sn, int(sh.get("markup") or 0)))
    return out


def pick_trainer(options, dist, limit=None):
    """The nearest by steps (the cheaper markup breaks a tie) of [(room, shop, markup)], given {room: steps}."""
    best = None
    for room, sn, markup in options:
        d = dist.get(room)
        if d is None or (limit is not None and d > limit):
            continue
        key = (d, markup, room)
        if best is None or key < best[0]:
            best = (key, (room, sn, markup))
    return best[1] if best else None


def parse_plan(text) -> list:
    """'10: STR 60 AGL 50; 20: STR 70 INT 40' → [(10, {"STR": 60, "AGL": 50}), (20, {...})], sorted by level.
    Each row is a target (what the stat should be by then), not an amount to add."""
    rows = []
    for part in re.split(r"[;\n]", text or ""):
        m = re.match(r"^\s*(?:L(?:evel)?\s*)?(\d+)\s*[:=]\s*(.+)$", part, re.I)
        if not m:
            continue
        stats = {}
        for k, v in re.findall(r"\b(STR|INT|WIL|AGL|HEA|CHM)\b\s*[=:]?\s*(\d+)", m.group(2), re.I):
            stats[k.upper()] = int(v)
        if stats:
            rows.append((int(m.group(1)), stats))
    return sorted(rows, key=lambda r: r[0])


def plan_row(rows, level) -> dict:
    """The targets due at this level: every row at or below it, later rows winning (rows are cumulative targets,
    and a stat a later row leaves out keeps the earlier row's target)."""
    out = {}
    for lvl, stats in rows:
        if lvl <= int(level or 0):
            out.update(stats)
    return out


def format_plan(rows) -> str:
    return "; ".join(f"{lvl}: " + " ".join(f"{k} {v}" for k, v in stats.items()) for lvl, stats in rows)


def read_form(screen_text):
    """The train stats form off the screen: {"stats": [6], "mins": [6], "maxs": [6], "cp": int, "exit": str|None}
    — or None unless all six stat rows and CP Left are there, each once (a half-drawn box is not read in part)."""
    if not screen_text:
        return None
    stats, mins, maxs = [None] * 6, [None] * 6, [None] * 6
    for m in STAT_ROW_RE.finditer(screen_text):
        i = FORM_LABELS.index(m.group(1))
        if stats[i] is not None:
            return None
        mins[i], maxs[i], stats[i] = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if any(v is None for v in stats):
        return None
    cps = CP_LEFT_RE.findall(screen_text)
    if len(cps) != 1:
        return None
    ex = EXIT_RE.findall(screen_text)
    return {"stats": stats, "mins": mins, "maxs": maxs, "cp": int(cps[0]), "exit": ex[0] if len(ex) == 1 else None}


def raise_cost(cur, target, mn, greatermud=False) -> int:
    return X.stat_cost(target - mn, greatermud) - X.stat_cost(cur - mn, greatermud)


def targets_for(form, row, greatermud=False):
    """What to type: (targets [6], CP it costs). Raises only (CP can't be unspent), never past the race maximum,
    in plan order (STR, INT, WIL, AGL, HEA, CHM) as far as CP Left goes — a stat that can't be reached in full is
    raised as far as the CP left allows."""
    budget = int(form["cp"])
    out, spent = list(form["stats"]), 0
    for i, k in enumerate(STAT_KEYS):
        want = row.get(k)
        cur, mn, mx = form["stats"][i], form["mins"][i], form["maxs"][i]
        if want is None or want <= cur:
            continue
        want = min(int(want), mx)
        best = cur
        for t in range(cur + 1, want + 1):
            if raise_cost(cur, t, mn, greatermud) > budget - spent:
                break
            best = t
        if best > cur:
            spent += raise_cost(cur, best, mn, greatermud)
            out[i] = best
    return out, spent


def payloads(current, targets) -> list:
    """The 10 field payloads before Exit: '' for Family Name, each stat's digits if it's a raise else '', '' ×3 for
    the appearance boxes. (The 11th, '' on Exit = SAVE, only goes once the form's been read back.)"""
    seq = [""]
    for c, t in zip(current, targets):
        seq.append(str(t) if t > c else "")
    return seq + ["", "", ""]


class Training:
    def __init__(self, session):
        self.s = session
        self.trip = None             # the leader's / solo trip (see _start)
        self.me = None               # this character's own train at the counter (see _me_start)
        self.mute_until = 0.0        # no trainer / can't pay: not again for a while
        self.maxed = False           # "You may not train any further" — not this session
        self.bad_rooms: dict = {}    # trainer room -> level it refused us at
        self.peers: dict = {}        # leader: member -> their last @ptrain st {"s","l","c","n","cash","t"}
        self.asked: dict = {}        # leader: member -> when we asked
        self.in_party_since: dict = {}
        self.hold = None             # member: {"leader", "until"} — the leader's 'trip on'
        self.member_job = None       # member: {"leader", "target", "room", "t"}
        self._told = None            # member: the last st we sent
        self._told_at = 0.0
        self._exp_asked = 0.0

    # ------------------------------------------------------------ settings
    @property
    def cfg(self):
        return self.s.settings

    @property
    def on(self) -> bool:
        return bool(getattr(self.cfg, "auto_train", False))

    @property
    def party_on(self) -> bool:
        return self.on and bool(getattr(self.cfg, "party_train", False))

    @property
    def busy(self) -> bool:
        return bool(self.trip or self.me or self.member_job)

    # ------------------------------------------------------------ who / what
    def my_class(self) -> int:
        return class_num(self.s.world, self.s.state.char_class or self.cfg.char_class)

    def _chart(self):
        st = self.s.state
        try:
            return X.chart_for(self.s.world, st.char_class or self.cfg.char_class, st.race or self.cfg.char_race)
        except Exception:
            return None

    def banked(self):
        """Levels the exp already pays for, or None if we've never seen the 'exp' line. The line's own
        'still to earn', less what's been gained since, decides whether one is due; the class+race exp chart counts
        how many (one when the chart isn't known)."""
        st = self.s.state
        if not st.level or not getattr(st, "exp_line_at", 0):
            return None
        since = int(getattr(st, "_exp_since_line", 0) or 0)
        if since < int(st.exp_needed or 0):
            return 0
        n = 1
        chart = self._chart()
        if chart:
            gm = (getattr(self.cfg, "exp_formula", "") or "") == "greatermud"
            n = max(1, X.level_for_exp(int(st.exp_total or 0) + since, chart, gm) - int(st.level))
        return n

    def levels_to_train(self) -> int:
        """Banked levels beyond the reserve, under the ceiling."""
        n = self.banked()
        if not n or self.maxed:
            return 0
        n -= int(getattr(self.cfg, "train_keep_levels", 0) or 0)
        cap = int(getattr(self.cfg, "train_max_level", 0) or 0)
        if cap:
            n = min(n, cap - int(self.s.state.level or 0))
        return max(n, 0)

    def _following(self):
        x = getattr(self.s.bot, "x", None)
        return getattr(x, "_following", None) if x else None

    def _leader_name(self):
        x = getattr(self.s.bot, "x", None)
        return (getattr(x, "_following", None) or getattr(x, "_followed", None)) if x else None

    def members(self) -> list:
        me = (self.cfg.my_name or "").lower()
        return [n for n in (self.s.state.party or {}) if n.lower() != me]

    def mudpilot_members(self) -> list:
        peers = getattr(getattr(self.s, "partysync", None), "peers", None) or {}
        low = {p.lower() for p in peers}
        return [n for n in self.members() if n.lower() in low]

    # ------------------------------------------------------------ comeback / remote asks
    def expects(self, name) -> bool:
        """A training trip is why `name` left the Realm / the party (comeback mustn't treat it as the party
        breaking), or it's the leader whose trip we're on (its @ptrain is listened to even out of the party)."""
        n = (name or "").lower()
        t = self.trip
        if t and n in {m.lower() for m in t.get("members0", [])}:
            return True
        h = self.hold
        if h and time.time() < h["until"] and n == h["leader"].lower():
            return True
        j = self.member_job
        return bool(j and n == j["leader"].lower())

    def holding_comeback(self) -> bool:
        """Member side: the leader's training trip is on (or we're training ourselves on its order) — no @comeback,
        no 'leader left' alarm, the leader re-invites."""
        h = self.hold
        if h and time.time() >= h["until"]:
            self.hold = None
            h = None
        return bool(h or self.member_job or (self.me and not self.trip))

    def leader_trip_on(self) -> bool:
        return bool(self.trip)

    # ------------------------------------------------------------ status for the Settings / @status
    def status(self) -> str:
        if self.me:
            return f"Training: {self.me['phase']}"
        if self.trip:
            return f"Training trip: {self.trip['phase']}"
        return ""

    # ------------------------------------------------------------ the game's lines
    def note_line(self, text):
        raw = text or ""
        line = strip_prompt(raw)
        if not line:
            return
        if (self.on or self.busy) and re.match(r"^You gain [\d,]+ experience", line, re.I):
            self._push_status()
        mj = JOINED_RE.match(line)
        if mj and self.trip:
            self.trip.setdefault("joined", {})[mj.group(1).lower()] = time.time()
        me = self.me
        if not me:
            return
        ph = me["phase"]
        if ph == "train_wait" and me.get("answer") is None:
            m = SUCCESS_STOCK_RE.match(line)
            if m:
                me["answer"], me["new_level"] = "ok", int(m.group(1))
                return
            if SUCCESS_PARA_RE.match(line):
                me["answer"], me["new_level"] = "ok", None      # Paradigm: no number — current + 1
                return
            for kind, rx in REFUSALS:
                if rx.match(line):
                    me["answer"] = kind
                    return
            return
        if ph == "form_wait":
            if any(rx.match(line) for rx in STATS_REFUSALS):
                me["form_refused"] = line
            return
        if ph in ("typing", "verify", "backout"):
            if VALUE_REFUSAL_RE.match(line):
                me["value_refused"] = line
            return
        if ph == "closing":
            if SAVED_RE.match(line) or (ENTERED_RE.match(line) and
                                        ENTERED_RE.match(line).group(1).lower() == (self.cfg.my_name or "").lower()):
                me["closed"] = time.time()

    # ------------------------------------------------------------ the end of a lap (leader / solo)
    def _free(self) -> bool:
        s, b, st = self.s, self.s.bot, self.s.state
        return bool(s.telnet.connected and st.room and not st.dead and not st.in_combat
                    and not getattr(self.cfg, "hands_off", False) and not getattr(b, "dead_hold", 0)
                    and not s.trips.trip and not (b.errands.active or b.errands.asking)
                    and not getattr(s.scrolls, "trip", None)
                    and not (st.view and st.view.monsters))

    def lap_end(self, mp) -> bool:
        """End of a loop lap: off to train if a level is due (or, leading with party training on, a member has one).
        True = we're off."""
        if not self.on or self.busy or time.time() < self.mute_until:
            return False
        if self._following():
            return False                     # a follower never sets off on its own: the leader's order only
        if not self._free():
            return False
        st = self.s.state
        if not getattr(st, "exp_line_at", 0):
            # never seen the 'exp' line: read it once, decide next lap (no polling — "You gain" keeps it current)
            if time.time() - self._exp_asked > 600:
                self._exp_asked = time.time()
                self.s.bot.send("exp")
            return False
        mine = self.levels_to_train()
        ready = self.ready_members() if self.party_on else []
        if not mine and not ready:
            if self.party_on:
                self._ask_members()
            return False
        return self._start(back=(mp, True), mine=mine, ready=ready)

    def ready_members(self) -> list:
        now = time.time()
        out = []
        for n in self.members():
            p = self.peers.get(n)
            if p and p.get("s") == "r" and int(p.get("n") or 0) > 0 and now - p.get("t", 0) < 1800 \
                    and p.get("l") and p.get("c"):
                out.append(n)
        return out

    def _ask_members(self):
        """Leader, party training on: ask MudPilot members who've been with us a while (and never mid-fight)."""
        if self.s.state.in_combat:
            return
        now = time.time()
        party = set(self.members())
        for n in list(self.in_party_since):
            if n not in party:
                self.in_party_since.pop(n, None)
                self.asked.pop(n, None)
        for n in self.mudpilot_members():
            since = self.in_party_since.setdefault(n, now)
            if now - since >= ASK_GRACE and n not in self.asked:
                self.asked[n] = now
                self.s.send(f"/{n} @ptrain ask", from_bot=True)

    # ------------------------------------------------------------ distances (tests stub this)
    def _dist_from(self, here) -> dict:
        b = self.s.bot
        return self.s.world.dist_map(tuple(here), level=b.route_level(), have=b.held_items() or set(),
                                     avoid=b.avoid_set() or None) or {}

    def limit(self) -> int:
        # trainers can be a long way off (Titan Trainer) and it's a once-a-level walk: wider than a shop trip
        return max(int(self.cfg.trip_max_steps or 60) * 5, 300)

    def choose(self, cls, level, here=None, dist=None):
        """The trainer for this class and level from `here`: (room, shop, markup) or None. Rooms that refused us
        at this level are skipped."""
        here = here or self.s.state.room
        if not here:
            return None
        dist = dist if dist is not None else self._dist_from(here)
        dist = dict(dist)
        dist.setdefault(tuple(here), 0)
        opts = [o for o in trainers(self.s.world, cls, level) if self.bad_rooms.get(o[0]) != level]
        return pick_trainer(opts, dist, self.limit())

    # ------------------------------------------------------------ the trip
    def plan_stops(self, here, mine, ready):
        """[{"room", "markup", "members": [names], "me": bool}] — members' stops first, our own last (training
        disbands our party, so it goes at the end). Members whose purse won't cover their fee are left out."""
        dist = dict(self._dist_from(here))
        dist.setdefault(tuple(here), 0)
        stops: dict = {}
        notes = []
        for n in ready:
            p = self.peers.get(n) or {}
            pick = self.choose(int(p.get("c") or 0), int(p.get("l") or 0), here, dist)
            if not pick:
                notes.append(f"{n}: no trainer for them within {self.limit()} steps")
                continue
            cost = fee(int(p["l"]), pick[2])
            if int(p.get("cash") or 0) < cost:
                notes.append(f"{n}: carrying {int(p.get('cash') or 0):,} of the {cost:,} copper fee — left out")
                continue
            stops.setdefault(pick[0], {"room": pick[0], "markup": pick[2], "members": [], "me": False,
                                       "targets": {}})
            stops[pick[0]]["members"].append(n)
            stops[pick[0]]["targets"][n] = int(p["l"]) + int(p.get("n") or 1)
        if mine:
            pick = self.choose(self.my_class(), int(self.s.state.level or 0), here, dist)
            if pick:
                stops.setdefault(pick[0], {"room": pick[0], "markup": pick[2], "members": [], "me": False,
                                           "targets": {}})
                stops[pick[0]]["me"] = True
            else:
                notes.append(f"no trainer for a level {self.s.state.level} {self.s.state.char_class or ''} "
                             f"within {self.limit()} steps")
        order = sorted(stops.values(), key=lambda x: (x["me"], dist.get(x["room"], 10 ** 6), x["room"]))
        return order, notes

    def _start(self, back, mine, ready) -> bool:
        st = self.s.state
        here = st.room
        stops, notes = self.plan_stops(here, mine, ready)
        for n in notes:
            self.s.log(f"Training: {n}")
        if not stops:
            self.mute_until = time.time() + MUTE_SECS
            self.s.log("Training: nowhere to train — carrying on (trying again in 30 min)")
            return False
        members0 = self.members()
        self.trip = {"phase": "start", "t": time.time(), "back": back, "stops": stops, "i": -1,
                     "members0": members0, "trained": 0, "joined": {}, "next_at": 0}
        who = []
        if mine:
            who.append(f"me ({mine} level{'s' if mine > 1 else ''})")
        who += [f"{n} (to {s['targets'][n]})" for s in stops for n in s["members"]]
        self.s.log(f"Training: off to train — {', '.join(who)}; "
                   + ", ".join(self._where(s['room']) for s in stops))
        self.s.bot.walking = False                    # (the loop picks up again when we're done)
        for n in self.mudpilot_members():
            self.s.send(f"/{n} @ptrain trip on", from_bot=True)
        mystop = next((x for x in stops if x["me"]), None)
        if mystop and self._bank_for(mystop["markup"], self.trip, mine, redo=False):
            return True                               # short of the fee: the bank on the way out
        self._next_stop()
        return True

    def _where(self, room) -> str:
        r = self.s.world.room(tuple(room))
        return f"{r.name if r else 'the trainer'} ({room[0]}/{room[1]})"

    def _next_stop(self):
        t = self.trip
        t["i"] += 1
        if t["i"] >= len(t["stops"]):
            t["phase"], t["t2"] = "regroup", time.time()
            return
        stop = t["stops"][t["i"]]
        t["went"] = time.time()
        if self.s.state.room == stop["room"]:
            t["phase"] = "at_stop"
            self._stop_begin()
            return
        t["phase"] = "going"
        if not self.s.bot.goto(stop["room"]):
            self.s.log(f"Training: no way to {self._where(stop['room'])} — skipping it")
            self._next_stop()

    def _stop_begin(self):
        t = self.trip
        stop = t["stops"][t["i"]]
        t["queue"] = list(stop["members"])
        t["cur"] = None
        t["stop_t"] = time.time()

    def tick(self):
        s = self.s
        if self.me:
            self._me_tick()                 # the counter and the form (Session doesn't tick us with Hands off on)
        h = self.hold
        if h and time.time() >= h["until"]:
            self.hold = None
        if self.member_job and not self.me:
            self._member_finish()
        seen = getattr(s.state, "exp_line_at", 0)
        if seen != getattr(self, "_exp_line_seen", 0):
            self._exp_line_seen = seen
            self._push_status()                  # a fresh 'exp' line (or a level): the leader hears if it changed
        t = self.trip
        if not t:
            if self.party_on and not self._following() and self.members() and s.telnet.connected \
                    and getattr(s, "_entered", False) and not getattr(self.cfg, "hands_off", False):
                self._ask_members()
            return
        b, st = s.bot, s.state
        now = time.time()
        if not s.telnet.connected or st.dead:
            self._end("disconnected" if not s.telnet.connected else "died", back=False)
            return
        if getattr(self.cfg, "hands_off", False):
            return
        if getattr(b, "_user_stop_at", 0) > t["t"] and not self.me:
            self._end("you stopped it", back=False)
            return
        if self.me:
            return
        # auto-train switched off, or we joined someone's party, mid-trip: don't keep walking to trainers
        # (0.8.201, bug hunt)
        if self._following():
            self._end("joined someone's party", back=False)
            return
        if not self.on:
            self._end("switched off", back=True)
            return
        if st.in_combat:
            return
        ph = t["phase"]
        if ph == "going":
            stop = t["stops"][t["i"]]
            if st.room == stop["room"] and not b.walking:
                t["phase"] = "at_stop"
                self._stop_begin()
            elif not b.walking and now - t["went"] > 5:
                if str(b.status).startswith(("Stopped by you", "Hung up")):
                    self._end("you stopped it", back=False)
                elif now - t["went"] > 30:
                    self.s.log(f"Training: couldn't get to {self._where(stop['room'])} — skipping it")
                    self._next_stop()
            elif now - t["went"] > 900:
                self._end("the walk took too long")
            return
        if st.resting:
            return
        if ph == "at_stop":
            self._stop_tick(now)
            return
        if ph == "bank":
            if not s.trips.trip and now - t.get("bank_t", now) > 5:
                self._end("the bank trip stopped", back=True)
            return
        if ph == "regroup":
            self._regroup_tick(now)

    def _stop_tick(self, now):
        """At a stop: each member trains on our order and is invited back, then (last stop) we train."""
        t, s = self.trip, self.s
        stop = t["stops"][t["i"]]
        cur = t.get("cur")
        if cur is None and t["queue"]:
            n = t["queue"].pop(0)
            cur = t["cur"] = {"name": n, "phase": "ordered", "t": now}
            r = stop["room"]
            s.send(f"/{n} @ptrain train {stop['targets'][n]} {r[0]}/{r[1]}", from_bot=True)
            s.log(f"Training: {n}, train here (to level {stop['targets'][n]})")
            return
        if cur is not None:
            if cur["phase"] == "ordered":
                if cur.get("done") == 0 and cur.get("why") == "notthere" and cur.get("tries", 0) < 4:
                    # a follower walks in a move behind us: "notthere" the first tick isn't a no — ask again a few
                    # times over ~10 s (0.8.201, bug hunt: party training skipped a trailing member)
                    if now - cur.get("done_t", now) >= 2.5:
                        cur.update(done=None, why=None, t=now, tries=cur.get("tries", 0) + 1)
                        r = stop["room"]
                        s.send(f"/{cur['name']} @ptrain train {stop['targets'][cur['name']]} {r[0]}/{r[1]}",
                               from_bot=True)
                    return
                if cur.get("done") == 0:
                    t["cur"] = None                   # didn't train (refused / not due): never left the party
                    return
                if cur.get("done") is not None or now - cur["t"] > DONE_SECS:
                    if cur.get("done") is None:
                        s.log(f"Training: no word from {cur['name']} in {int(DONE_SECS)} s — inviting them back")
                    cur.update(phase="invite", t=now)
                return
            if cur["phase"] == "invite":
                s.send(f"invite {cur['name']}", from_bot=True)    # (training dropped them from the party)
                cur.update(phase="rejoin", t=now)
                return
            if cur["phase"] == "rejoin":
                if self._in_party(cur["name"], cur["t"]) or now - cur["t"] > REJOIN_SECS:
                    if not self._in_party(cur["name"], cur["t"]):
                        s.log(f"Training: {cur['name']} hasn't rejoined in {int(REJOIN_SECS)} s — going on")
                    t["cur"] = None
                elif now - cur["t"] > 15 and not cur.get("re_invited"):
                    cur["re_invited"] = True
                    s.send(f"invite {cur['name']}", from_bot=True)
                return
        # members done here: our own train, if this is our stop
        if stop["me"] and not t.get("me_done_at_stop"):
            t["me_done_at_stop"] = True
            t["invite_after_me"] = True
            self._me_start(stop["markup"], on_done=self._after_my_train)
            return
        self._next_stop()

    def _in_party(self, name, since) -> bool:
        n = name.lower()
        if (self.trip or {}).get("joined", {}).get(n, 0) >= since:
            return True
        return any(p.lower() == n and (rec or {}).get("t", 0) > since for p, rec in (self.s.state.party or {}).items())

    def _after_my_train(self, trained, why):
        t = self.trip
        if not t:
            return
        t["trained"] += trained
        t["my_why"] = why
        t["t_me"] = time.time()
        if why in ("you stopped it", "disconnected", "died"):
            self._end(why, back=False)
            return
        if why in ("room", "unsuitable", "too_low", "too_high") and t.get("rerouted", 0) < 2 \
                and self.levels_to_train() > 0:
            # this trainer won't (or no longer will — the band ends at this level): on to the next one that serves
            # us, the refusing room skipped (MudPlay: "progressed too far" → walk on to the next trainer)
            pick = self.choose(self.my_class(), int(self.s.state.level or 0))
            if pick:
                t["rerouted"] = t.get("rerouted", 0) + 1
                self.s.log(f"Training: on to {self._where(pick[0])}")
                t["stops"].insert(t["i"] + 1, {"room": pick[0], "markup": pick[2], "members": [], "me": True,
                                               "targets": {}})
                t["stops"][t["i"]]["me"] = False
                self._next_stop()
                return
        if why == "no_money" and not t.get("banked_once"):
            # re-read the purse and do one bank top-up, then train again (MudPlay: money refusals once locked the run)
            stop = t["stops"][t["i"]]
            stop["members"] = []                      # (they've trained here already: not again on the way back)
            if self._bank_for(stop["markup"], t, max(self.levels_to_train(), 1), redo=True):
                t["me_done_at_stop"] = False
                return
        self._next_stop()

    def _bank_for(self, markup, t, levels=1, redo=False) -> bool:
        """Short of the fee(s): the existing bank trip (shoptrips.withdraw_for), then on to the trainer — before
        setting off (redo False) or back to the stop we're at (redo True, after a money refusal). Once a trip."""
        st = self.s.state
        if st.wealth is None or t.get("banked_once"):
            return False
        lvl = int(st.level or 0)
        need = sum(fee(lvl + k, markup) for k in range(max(int(levels), 1)))
        have = int(st.wealth or 0)
        if have >= need:
            return False
        mp = (t.get("back") or (None, None))[0]

        def back_to_trainer():
            tr = self.trip
            if not tr:
                return
            if redo:
                tr["i"] -= 1                          # the same stop again
            tr["me_done_at_stop"] = False
            self._next_stop()
        t["banked_once"] = True
        ok = self.s.trips.withdraw_for(mp, True, need - have, why="training", after=back_to_trainer)
        if ok:
            t["phase"], t["bank_t"] = "bank", time.time()
            self.s.log(f"Training: {need:,} copper in fees, carrying {have:,} — the bank first")
        return ok

    def _regroup_tick(self, now):
        """Every stop done: everyone who was in the party at the start is invited back (our own train disbanded it),
        then 'trip off' and back to the loop."""
        t, s = self.trip, self.s
        if not t.get("invite_after_me") or not t["members0"]:
            # we didn't train ourselves: the party was never disbanded, and each member was invited back at its stop
            self._end("trained" if t["trained"] else (t.get("my_why") or "done"))
            return
        if not t.get("regroup_sent"):
            t["regroup_sent"] = now
            for n in t["members0"]:
                s.send(f"invite {n}", from_bot=True)
            return
        since = t["regroup_sent"] - 1
        waiting = [n for n in t["members0"] if not self._in_party(n, since)]
        if waiting and now - t["regroup_sent"] < REJOIN_SECS:
            # again after 10 s — past the session's 8 s duplicate-invite filter, which can eat the first one when a
            # member was invited back at this same stop a moment before our own train disbanded the party
            if now - t["regroup_sent"] > 10 and not t.get("re_invited"):
                t["re_invited"] = True
                for n in waiting:
                    s.send(f"invite {n}", from_bot=True)
            return
        if waiting:
            s.log(f"Training: {', '.join(waiting)} didn't rejoin in {int(REJOIN_SECS)} s — carrying on "
                  "(the party's comeback takes over)")
            cb = getattr(s, "comeback", None)
            if cb is not None and getattr(self.cfg, "party_comeback", False):
                for n in waiting:
                    # handed to comeback as dropped: it waits for them and fetches them when they're back
                    cb.missing.setdefault(n, {"t": now, "why": "dropped"})
        self._end("trained" if t["trained"] else (t.get("my_why") or "done"))

    def _end(self, why, back=True):
        t, self.trip = self.trip, None
        if t is None:
            return
        sent = set()
        peers = {p.lower() for p in (getattr(getattr(self.s, "partysync", None), "peers", None) or {})}
        for n in t.get("members0") or []:
            if n.lower() in peers and n.lower() not in sent:
                sent.add(n.lower())
                self.s.send(f"/{n} @ptrain trip off", from_bot=True)
        self.s.log(f"Training: done ({why})" + (f" — {t['trained']} level{'s' if t['trained'] != 1 else ''} "
                                               f"trained" if t["trained"] else ""))
        if self.me:
            return                                    # (the counter / form finishes on its own)
        bk = t.get("back")
        if back and bk and bk[0] is not None and not self.s.state.dead:
            mp, loop = bk
            self.s.log(f"Training: back to {mp.title}")
            here = self.s.state.room
            steps = [x.room for x in getattr(mp, "steps", []) if x.room]
            if here and steps and here not in steps:
                self.s.bot.goto_bg(steps[0], then=mp)
            else:
                self.s.bot.start_path(mp, loop=loop)

    def cancel(self, why=""):
        if self.me and self.me["phase"] in ("typing", "verify", "backout", "closing", "form_wait", "form_read"):
            # never walk away from an open form with the keyboard held: back it out first (the form's own end
            # releases the hold)
            if self.me["phase"] in ("typing", "verify", "form_read"):
                self._backout(f"{why or 'cancelled'}")
        else:
            self.me = None
            self._release_hold(why or "cancelled")
        self.trip = None
        self.member_job = None

    def reset(self, why=""):
        self.cancel(why)

    # ------------------------------------------------------------ our own train at the counter
    def _me_start(self, markup, on_done, target=None):
        """Train here: read 'exp' and 'i', 'train' (again while levels are banked), then the CP plan if it's on.
        on_done(levels trained, why) when it's over."""
        self.me = {"phase": "check", "t": time.time(), "markup": markup, "on_done": on_done, "trained": 0,
                   "target": target, "sent": False, "next_at": 0, "why": "", "start_level": self.s.state.level}

    def _me_tick(self):
        me, s, st, b = self.me, self.s, self.s.state, self.s.bot
        now = time.time()
        ph = me["phase"]
        if ph in ("form_wait", "form_read", "typing", "verify", "backout", "closing", "left_open"):
            self._form_tick(now)
            return
        if not s.telnet.connected or st.dead:
            self._me_finish("disconnected" if not s.telnet.connected else "died")
            return
        if getattr(self.cfg, "hands_off", False):
            return
        if getattr(b, "_user_stop_at", 0) > me["t"]:
            self._me_finish("you stopped it")
            return
        if st.in_combat or st.resting:
            return
        if now < me["next_at"]:
            return
        if ph == "check":
            if not me["sent"]:
                me.update(sent=True, exp_at=getattr(st, "exp_line_at", 0), inv_seq=st.inv_seq, next_at=now + 0.3,
                          deadline=now + EXP_SECS)
                b.send("exp")
                b.send("i")
                return
            fresh = getattr(st, "exp_line_at", 0) != me["exp_at"] and st.inv_seq != me["inv_seq"]
            if not fresh and now < me["deadline"]:
                return
            n = self.levels_to_train()
            tgt = me.get("target")
            if tgt:
                n = min(n, int(tgt) - int(st.level or 0))
            if n <= 0:
                self._after_trains("no level due" if not me["trained"] else "all banked levels trained")
                return
            cost = fee(int(st.level or 0), me["markup"])
            if st.wealth is not None and int(st.wealth) < cost:
                s.log(f"Training: the fee is {cost:,} copper and I carry {int(st.wealth):,}")
                self._after_trains("no_money")
                return
            me.update(phase="train_wait", answer=None, sent_at=now, fee=cost, level_before=st.level)
            b.status = f"Training: level {int(st.level or 0)} → {int(st.level or 0) + 1}"
            s.log(f"Training: train (level {st.level} → {int(st.level or 0) + 1}, {cost:,} copper)")
            b.send("train")
            return
        if ph == "train_wait":
            ans = me.get("answer")
            if ans is None and now - me["sent_at"] < TRAIN_SECS:
                return
            if ans == "ok":
                new = me.get("new_level") or (int(me["level_before"] or 0) + 1)
                st.level = new
                # the last 'exp' line was for the old level: what's still to earn now is to the level after. With the
                # exp chart we know it; without, nothing more counts as due until the next 'exp' line comes in
                chart = self._chart()
                gm = (getattr(self.cfg, "exp_formula", "") or "") == "greatermud"
                st.exp_needed = (max(X.exp_needed(new + 1, chart, gm) - int(st.exp_total or 0), 0) if chart
                                 else 10 ** 12)
                if st.wealth is not None:
                    st.wealth = max(0, int(st.wealth) - me["fee"])     # the fee left the purse
                me["trained"] += 1
                s.log(f"Training: now level {new}")
                sc = getattr(s, "scrolls", None)
                if sc is not None and getattr(sc, "on", False) and not sc.trip:
                    sc.pending = "level-up"           # (Paradigm's line has no 'attain level' for scrolls to see)
                # (training is a realm excursion — no room shown after it): look, then read 'exp' again
                b.send("")
                me.update(phase="check", sent=False, next_at=now + 1.0)
                return
            if ans is None:
                s.log("Training: no answer to 'train' in 8 s")
                self._after_trains("no answer")
                return
            room = st.room
            if ans in ("room", "unsuitable", "too_low", "too_high"):
                if room:
                    self.bad_rooms[tuple(room)] = int(st.level or 0)
                s.log(f"Training: the trainer here won't train me ({ans.replace('_', ' ')})")
            elif ans == "maxed":
                self.maxed = True
                s.log("Training: the game says I may not train any further — not trying again this session")
            elif ans == "no_exp":
                s.log("Training: not enough exp yet after all")
                st._exp_since_line = 0                 # (the estimate was wrong: wait for the next 'exp' line)
            elif ans == "no_money":
                s.log("Training: not enough money for the fee")
                b.send("i")
            self._after_trains(ans)
            return
        if ph == "after":
            self._me_finish(me["why"])

    def _after_trains(self, why):
        me = self.me
        me["why"] = why
        if me["trained"] and getattr(self.cfg, "train_stats", False):
            row = plan_row(parse_plan(getattr(self.cfg, "train_stats_plan", "")), self.s.state.level or 0)
            if row:
                self._form_begin(row)
                return
            self.s.log(f"Training: no CP plan row for level {self.s.state.level} — not training stats")
        self._me_finish(why)

    def _me_finish(self, why):
        me, self.me = self.me, None
        if not me:
            return
        self._release_hold(why)
        cb = me.get("on_done")
        if cb:
            try:
                cb(me["trained"], me.get("why") or why)
            except Exception as ex:
                self.s.log(f"Training: {ex}")

    # ------------------------------------------------------------ train stats (the form)
    def _screen_text(self) -> str:
        try:
            return "\n".join(self.s.ansi.screen.text_rows())
        except Exception:
            return ""

    def _screen_seq(self) -> int:
        try:
            return int(self.s.ansi.screen.seq)
        except Exception:
            return 0

    def _form_begin(self, row):
        """Off into 'train stats'. The hold on every automatic command starts as it goes out (Session.send) — not
        when the form's marker turns up, which on Paradigm's cursor-drawn box may never come as a line."""
        me, s = self.me, self.s
        me.update(phase="form_wait", row=row, form_t=time.time(), form=None, typed=0, value_refused=None,
                  form_refused=None, seq_at=self._screen_seq(), seq_t=time.time())
        try:
            s.ansi.screen.clear()                 # a box left from an earlier form mustn't read as this one
        except Exception:
            pass
        s.log(f"Training: train stats — plan for level {s.state.level}: "
              + " ".join(f"{k} {v}" for k, v in row.items()))
        s.send("train stats", from_bot=True)

    def _settled(self, now) -> bool:
        me = self.me
        q = self._screen_seq()
        if q != me.get("seq_at"):
            me["seq_at"], me["seq_t"] = q, now
            return False
        return now - me["seq_t"] >= SETTLE_SECS

    def _key(self, payload, enter=True):
        self.s.form_key(payload + ("\r" if enter else ""))

    def _form_tick(self, now):
        me, s = self.me, self.s
        ph = me["phase"]
        if ph in ("form_read", "typing", "verify") and getattr(s.bot, "_user_stop_at", 0) > me["form_t"]:
            # your Stop mid-form: nothing gets saved — out with QUIT (the form's end releases the hold)
            me["why"] = "you stopped it"
            self._backout("you stopped it", advanced=0 if ph == "form_read" else
                          (me["typed"] if ph == "typing" else len(me["keys"])))
            return
        if ph == "left_open":
            # a form we couldn't verify or back out of: left for you; the hold drops once it's gone (or the cap)
            if not s.form_held():
                self._me_finish(me.get("why") or "left open")
            return
        if ph == "form_wait":
            if me.get("form_refused"):
                s.log(f"Training: train stats refused — {me['form_refused']}")
                self._release_hold("refused")
                s.bot.send("")
                self._me_finish(me["why"])
                return
            f = read_form(self._screen_text())
            if f and self._settled(now):
                s.note_form_seen()
                me.update(phase="form_read", form=f)
                return
            if now - me["form_t"] > FORM_WAIT_SECS:
                if f or s.form_seen():
                    me["why"] = "the train stats form couldn't be read"
                    self._leave_open("the form came up but couldn't be read")
                else:
                    s.log("Training: no train stats form in 10 s — carrying on")
                    self._release_hold("no form")
                    s.bot.send("")
                    self._me_finish(me["why"])
            return
        if ph == "form_read":
            f = me["form"]
            gm = (getattr(self.cfg, "exp_formula", "") or "") == "greatermud"
            tg, cost = targets_for(f, me["row"], gm)
            me.update(targets=tg, cost=cost, keys=payloads(f["stats"], tg), typed=0, next_key=now)
            if tg == f["stats"]:
                s.log(f"Training: the form shows {self._fmt(f['stats'])}, CP Left {f['cp']} — nothing to raise "
                      "for the plan (or no CP for it); leaving with QUIT")
                me["why"] = me["why"] or "nothing to raise"
                self._backout("nothing to raise", advanced=0)
                return
            if f.get("exit") != "SAVE":
                self._backout("the Exit field doesn't show SAVE", advanced=0)
                return
            s.log(f"Training: form shows {self._fmt(f['stats'])}, CP Left {f['cp']} — typing "
                  f"{self._fmt(tg)} ({cost} CP)")
            me["phase"] = "typing"
            return
        if ph == "typing":
            if me.get("value_refused"):
                # the cursor stayed on the field the game refused: everything after it is out of step
                self._backout(f"the game refused a value ({me['value_refused']})", advanced=max(me["typed"] - 1, 0))
                return
            if now < me["next_key"]:
                return
            if me["typed"] < len(me["keys"]):
                self._key(me["keys"][me["typed"]])
                me["typed"] += 1
                me["next_key"] = now + KEY_GAP
                if me["typed"] == len(me["keys"]):
                    me.update(phase="verify", verify_t=now, seq_at=self._screen_seq(), seq_t=now)
            return
        if ph == "verify":
            if me.get("value_refused"):
                self._backout(f"the game refused a value ({me['value_refused']})", advanced=len(me["keys"]) - 1)
                return
            if now - me["verify_t"] < KEY_GAP * 2 or (not self._settled(now) and now - me["verify_t"] < VERIFY_MAX_SECS):
                return
            f = read_form(self._screen_text())
            want_cp = me["form"]["cp"] - me["cost"]
            problem = None
            if not f:
                problem = "the form couldn't be read back"
            elif f["stats"] != me["targets"]:
                problem = f"it shows {self._fmt(f['stats'])}, not {self._fmt(me['targets'])}"
            elif f["cp"] != want_cp:
                problem = f"CP Left shows {f['cp']}, not {want_cp}"
            elif f.get("exit") != "SAVE":
                problem = f"Exit shows {f.get('exit') or 'nothing'}, not SAVE"
            elif self._cursor_field() not in (None, "Exit"):
                # the Editor parks the cursor on the box it's on: still on another box = a keystroke went missing,
                # and this Enter would only move on (Paradigm's box leaves it on the title row: no answer, fine)
                problem = f"the cursor is still on {self._cursor_field()}"
            if problem:
                self._backout(problem, advanced=len(me["keys"]))
                return
            s.log(f"Training: form checked ({self._fmt(f['stats'])}, CP Left {f['cp']}) — SAVE")
            self._key("")
            me.update(phase="closing", close_t=now, closed=0, saved=True,
                      prompt_at=getattr(s.state, "last_prompt", 0))
            return
        if ph == "backout":
            self._backout_tick(now)
            return
        if ph == "closing":
            gone = me.get("closed") or getattr(s.state, "last_prompt", 0) > me["prompt_at"]
            if gone:
                self._release_hold("form closed")
                s.bot.send("")                    # some realms don't show the room again after the form
                if me.get("saved"):
                    s.log("Training: stats trained by the plan")
                self._me_finish(me["why"] or ("stats trained" if me.get("saved") else "stats not trained"))
                return
            if now - me["close_t"] > CLOSE_SECS:
                s.log("Training: the train stats form didn't close in 15 s — letting automatic commands go again")
                s.on_alert("Train stats: the form didn't close — check the screen")
                self._release_hold("close timeout")
                self._me_finish(me["why"] or "form didn't close")

    FIELD_RE = re.compile(r"\b(Family Name|Strength|Intellect|Willpower|Agility|Health|Charm|Hair Length|Hair Colou?r|"
                          r"Eye Colou?r|Exit:)")

    def _cursor_field(self):
        """The form box on the cursor's row, or None when it isn't on one."""
        try:
            scr = self.s.ansi.screen
            row = "".join(ch for ch, *_ in scr.cells[scr.r])
        except Exception:
            return None
        m = self.FIELD_RE.search(row[:40])
        return (m.group(1).rstrip(":") if m else None)

    @staticmethod
    def _fmt(stats) -> str:
        return " ".join(f"{k} {v}" for k, v in zip(STAT_KEYS, stats))

    def _backout(self, why, advanced=None):
        """Leave the form without saving: Enter to the Exit field, Space until it reads QUIT (at most 4), Enter.
        Never SAVE a form we couldn't verify — CP can't be unspent."""
        me, s = self.me, self.s
        if not me:
            return
        typed = me.get("typed", 0) if advanced is None else advanced
        s.log(f"Training: not saving the train stats form — {why}. Leaving it with QUIT")
        me.update(phase="backout", why=me.get("why") or f"stats not trained ({why})",
                  enters=max(10 - int(typed), 0), spaces=0, next_key=time.time(), bo_t=time.time(),
                  space_t=0)

    def _backout_tick(self, now):
        me, s = self.me, self.s
        if now < me["next_key"]:
            return
        if me["enters"] > 0:
            self._key("")
            me["enters"] -= 1
            me["next_key"] = now + KEY_GAP
            if me["enters"] == 0:
                me["next_key"] = now + SPACE_SECS
            return
        f = read_form(self._screen_text())
        choice = f.get("exit") if f else None
        if choice is None:
            m = EXIT_RE.findall(self._screen_text())
            choice = m[0] if len(m) == 1 else None
        if choice == "QUIT":
            self._key("")
            me.update(phase="closing", close_t=now, closed=0, saved=False,
                      prompt_at=getattr(s.state, "last_prompt", 0))
            return
        if me["spaces"] >= MAX_SPACES:
            self._leave_open("the Exit field never showed QUIT")
            return
        self._key(" ", enter=False)
        me["spaces"] += 1
        me["next_key"] = now + SPACE_SECS

    def _leave_open(self, why):
        """Can't read it, can't reach QUIT: press nothing more (an Enter could SAVE). Stop, say so, and keep the
        automatic commands held until the form's gone or the cap runs out."""
        me, s = self.me, self.s
        me["phase"] = "left_open"
        me["why"] = me.get("why") or f"stats not trained ({why})"
        s.log(f"Training: {why} — the train stats form is left open for you; finish or leave it by hand")
        s.on_alert("Train stats left open — finish or leave it by hand")
        try:
            s.bot.stop("Stopped: train stats form left open — finish or leave it by hand")
        except Exception:
            pass

    def _release_hold(self, why):
        try:
            if self.s.form_held():
                self.s.end_form_hold(why)
        except Exception:
            pass

    # ------------------------------------------------------------ party protocol
    def _status_fields(self):
        st = self.s.state
        n = self.levels_to_train()
        if not self.party_on:
            s_ = "o"
        elif getattr(self.cfg, "hands_off", False) or st.dead:
            s_ = "b"          # (not combat: it'd flip on every kill — the leader never trains mid-fight anyway)
        else:
            s_ = "r" if n > 0 else "w"
        return (s_, int(st.level or 0), self.my_class(), n, int(st.wealth or 0))

    def status_msg(self) -> str:
        s_, l, c, n, cash = self._status_fields()
        return f"@ptrain st s={s_} l={l} c={c} n={n} cash={cash}"

    def _push_status(self, force=False):
        """Member: tell the leader when what we'd report changes (no heartbeat)."""
        if not self.party_on:
            return
        lead = self._following()
        if not lead or not self.s.telnet.connected:
            return
        f = self._status_fields()
        key = (f[0], f[1], f[3])
        if not force and key == self._told:
            return                                    # (nothing new to tell: no heartbeat)
        self._told, self._told_at = key, time.time()
        self.s.send(f"/{lead} {self.status_msg()}", from_bot=True)

    ST_FIELD_RE = re.compile(r"\b(s|l|c|n|cash)=([\w-]+)")

    def party_msg(self, sender, args):
        """'@ptrain …' from a party member (remote.py: c_ptrain)."""
        words = (args or "").split()
        if not words:
            return None
        verb = words[0].lower()
        lead = self._leader_name()
        from_leader = bool(lead) and sender.lower() == lead.lower()
        if verb == "st":
            p = {"t": time.time()}
            for k, v in self.ST_FIELD_RE.findall(args):
                # (0.8.201, bug hunt: isdecimal, not isdigit — '²'.isdigit() is True but int('²') raises)
                p[k] = v if k == "s" else int(v) if v.lstrip("-").isdecimal() else 0
            self.peers[sender] = p
            return None
        if verb == "done":
            t = self.trip
            cur = (t or {}).get("cur")
            if cur and cur["name"].lower() == sender.lower():
                cur["done"] = int(words[1]) if len(words) > 1 and words[1].isdecimal() else 0   # (0.8.201: as above)
                cur["why"], cur["done_t"] = (words[2].lower() if len(words) > 2 else None), time.time()
                self.s.log(f"Training: {sender} done ({' '.join(words[1:]) or 'no word'})")
                if cur["why"] != "notthere":          # (asked again shortly — 0.8.201, bug hunt)
                    self.peers.pop(sender, None)      # (its status is stale now: it tells us the new one)
            return None
        # leader → member orders: only from the leader we follow (or followed into this trip)
        if not from_leader:
            return None
        if verb == "trip":
            on = len(words) > 1 and words[1].lower() == "on"
            if on:
                # protective only (no @comeback, no leader-gone alarm), so it's honoured even with party training off
                self.hold = {"leader": sender, "until": time.time() + TRIP_HOLD_SECS}
                self.s.log(f"Training: {sender}'s training trip — holding @comeback till it's over")
            else:
                self.hold = None
                self.s.log(f"Training: {sender}'s training trip is over")
            return None
        if not self.party_on:
            return None
        if verb == "ask":
            if not getattr(self.s.state, "exp_line_at", 0):
                self.s.bot.send("exp")                # (answered when the line's in — tick sees it arrive)
                self._told = None
                return None
            self._push_status(force=True)
            return None
        if verb == "train":
            self._member_train(sender, words[1:])
        return None

    def _member_train(self, leader, words):
        st, s = self.s.state, self.s

        def refuse(why):
            s.send(f"/{leader} @ptrain done 0 {why}", from_bot=True)
            s.log(f"Training: {leader} asked me to train — not now ({why})")
        if self.me or self.trip:
            return refuse("busy")
        if st.in_combat or getattr(self.cfg, "hands_off", False) or st.dead:
            return refuse("blocked")
        target = int(words[0]) if words and words[0].isdecimal() else 0      # (0.8.201, bug hunt: not isdigit — '²')
        room = None
        if len(words) > 1:
            m = re.match(r"^(\d+)/(\d+)$", words[1])
            room = (int(m.group(1)), int(m.group(2))) if m else None
        if room is None or st.room is None or tuple(st.room) != room:
            return refuse("notthere")
        markup = 0
        for sn, sh in (getattr(s.world, "shops", None) or {}).items():
            if int(sh.get("type") or 0) == TRAINER_TYPE and room in [tuple(r) for r in sh.get("rooms") or []]:
                markup = int(sh.get("markup") or 0)
                break
        self.member_job = {"leader": leader, "target": target, "room": room, "t": time.time()}
        self.hold = {"leader": leader, "until": time.time() + TRIP_HOLD_SECS}
        s.log(f"Training: {leader} says train here (up to level {target})")
        self._me_start(markup, on_done=self._member_done, target=target or None)

    def _member_done(self, trained, why):
        j = self.member_job
        if j:
            j["result"] = (trained, why)

    def _member_finish(self):
        """Our train is over (and any form gone — the hold is released): tell the leader. Training dropped us from
        the party; the leader invites us back."""
        j, self.member_job = self.member_job, None
        trained, why = j.get("result") or (0, "stopped")
        word = re.sub(r"[^\w -]", "", str(why or ""))[:40]
        self.s.send(f"/{j['leader']} @ptrain done {trained} {word}".rstrip(), from_bot=True)
        self._told = None
