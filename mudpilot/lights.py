"""Auto-light with carried lights: ready a torch / lantern before the walk goes into a room too dark to see in, put it
away again where you can see without it, relight or replace it when it burns out, and buy more when you run short.

0.8.200, from the MudPlay review (Settings → Other: "Ready a carried light (torch, lantern…)…", off by default).
This is separate from the older Light switch (a light *command* — a spell — sent in dark rooms); both can be on.

How dark is too dark (MME / the game): a room's light level is its MME Light plus the Illumination (ability 13) of
what you wear plus a lit light's strength (ability 54), and you can see when that's −150 or more. The darkest rooms
on Paradigm are −200 to −325; a torch is 100, a lantern 175, a scaled lantern 200.
  * Per room, not per route: readying for the darkest room anywhere on the loop kept the light burning through the
    towns in between (MudPlay's pitfall). Before each step into a dark room: 'rem' a light too weak, 'use' the
    weakest carried light that's strong enough, and a bare Enter once it's lit — 'use' doesn't show the room again,
    and passive monsters were walked past without it.
  * 'rem' in a room you can see without it (unless the next steps are dark again).
  * Burned out ('Your torch flickers and goes out.', the lamp's oil, the moon-lamp, the light ball, '<item> is no
    longer lit!'): read the pack, light a spare if it's still dark.
  * Dark room while we think a light is lit: the belief is stale (a light walked a two-room dark loop for half an
    hour with spares in the pack) — one 'i', then light a spare.
  * One 'use' at a time (a latch until the game answers): two 'use's before the pack confirmed the first lit a
    second light.
  * Buying, at the end of a lap: no light carried that's strong enough for the loop's darkest room, or the readied
    one nearly spent with no spare → the weakest light in the shops that's strong enough, enough for ~2 hours, as
    far as the purse goes. A failed buy backs off 10 minutes, doubling up to 2 hours (it re-triggered forever).
Never in combat; never while Hands off is on (the bot doesn't tick then).
"""
from __future__ import annotations

import math
import re
import time

from .gamestate import DARK_RE, worn_list

LIGHT_TYPE = 6                   # MME ItemType 6 = light source
STRENGTH_ABIL = 54               # IlluTarget: how much a lit light adds
ILLU_ABIL = 13                   # Illumination on worn gear
SEE_FLOOR = -150                 # you can see when the room's light level is this or more
REORDER_MINS = 10                # the readied light this close to burning out (and no spare): buy more
CARRY_HOURS = 2                  # buy enough to last about this long
USE_SECS = 3                     # one use of a light every ~3 seconds (Readied/N drops 1 every 30 s)
PENDING_SECS = 4.0               # the 'use' latch
LOOKAHEAD = 3                    # steps ahead checked before putting a light away
BACKOFF_MIN, BACKOFF_MAX = 600, 7200

PROMPT_LEAD_RE = re.compile(r"^\s*(?:\[[^\]]*\]:?\s*)+")
LIT_RE = re.compile(r"^You lit (?:the |your |an? )?(.+?)\.?\s*$", re.I)
REMOVED_RE = re.compile(r"^You have removed (?:the |your |an? )?(.+?)(?: and extinguished it)?\.?\s*$", re.I)
NOT_LIT_RE = re.compile(r"^You do not have (?:the |your |an? )?(.+?) lit\.?", re.I)
ALREADY_LIT_RE = re.compile(r"^You already have something lit", re.I)
RECHARGE_RE = re.compile(r"^You must recharge that before you may light it again", re.I)
MAY_NOT_RE = re.compile(r"^You may not light that item", re.I)
CANNOT_RE = re.compile(r"^You cannot light (?:the |your |an? )?(.+?)!", re.I)
BURNOUT_RES = (re.compile(r"^Your (.+?) flickers,? and goes out\.?", re.I),
               re.compile(r"^Your (.+?) runs out of (?:oil|fuel),? (?:and )?goes out\.?", re.I),
               re.compile(r"^The light in (?:the |your )?(.+?) flickers,? and goes out\.?", re.I),
               re.compile(r"^Your (.+?) disappears out of exist[ae]nce\.?", re.I),
               re.compile(r"^(?:Your |The )?(.+?) is no longer lit!?", re.I))
READIED_RE = re.compile(r"\(\s*Readied(?:\s*/\s*(\d+))?\s*\)", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def catalogue(world) -> dict:
    """{item number: {"num", "name", "strength", "uses", "burn_h"}} for every light source MME knows."""
    out = {}
    for num, g in (getattr(world, "gear", None) or {}).items():
        if int(g.get("ItemType") or 0) != LIGHT_TYPE:
            continue
        stg = int((g.get("abils") or {}).get(STRENGTH_ABIL) or 0)
        if stg <= 0:
            continue
        uses = int(g.get("UseCount") or 0)
        out[int(num)] = {"num": int(num), "name": g.get("name") or world.item_name(num), "strength": stg,
                         "uses": uses, "burn_h": max(uses * USE_SECS / 3600.0, 0.05)}
    return out


def parse_carried(carrying, cat_by_name) -> list:
    """Lights in 'You are carrying …': [{"name", "qty", "readied", "left" (Readied/N or None), "strength", "num"}]."""
    out = []
    for part in re.split(r",\s*", (carrying or "").strip().rstrip(".")):
        p = part.strip()
        if not p:
            continue
        m = re.match(r"^(?:(\d+)\s+|an?\s+|the\s+|some\s+)?(.+?)\s*(\([^)]*\))?\s*$", p, re.I)
        if not m:
            continue
        qty, name, tag = int(m.group(1) or 1), _norm(m.group(2)), m.group(3) or ""
        rec = cat_by_name.get(name) or (cat_by_name.get(name[:-1]) if name.endswith("s") else None) or \
            (cat_by_name.get(name[:-2]) if name.endswith("es") else None)
        if not rec:
            continue
        rm = READIED_RE.search(tag)
        out.append({"name": rec["name"], "qty": qty, "readied": bool(rm),
                    "left": int(rm.group(1)) if rm and rm.group(1) else None,
                    "strength": rec["strength"], "num": rec["num"]})
    return out


class AutoLight:
    def __init__(self, bot):
        self.bot = bot
        self.lit = None              # name of the light we believe is lit
        self.pending = None          # (name, sent at): 'use' latch
        self.bad: set = set()        # light names that won't light (spent / not ours to light) this session
        self.seen_ok: dict = {}      # room -> MME light: seen without a light lit
        self.seen_dark: dict = {}    # room -> MME light: couldn't see in it with no light lit
        self.backoff: dict = {}      # light name -> (until, secs)
        self.buying = None           # {"name", "had", "t"}: a buy trip under way, checked when it's over
        self._view_seq = -1
        self._inv_seq = -1
        self._inv_shows_readied = False
        self._relight = False        # read the pack, then light a spare
        self._cat = None
        self._cat_for = None

    @property
    def s(self):
        return self.bot.s

    @property
    def on(self) -> bool:
        return bool(getattr(self.s.settings, "auto_light_items", False))

    # ------------------------------------------------------------ what we know
    def cat(self) -> dict:
        w = self.s.world
        if self._cat is None or self._cat_for is not w:
            self._cat, self._cat_for = catalogue(w), w
            self._by_name = {_norm(v["name"]): v for v in self._cat.values()}
        return self._cat

    def by_name(self) -> dict:
        self.cat()
        return self._by_name

    def carried(self) -> list:
        return [c for c in parse_carried(self.s.state.carrying, self.by_name()) if _norm(c["name"]) not in self.bad]

    def strength_of(self, name) -> int:
        rec = self.by_name().get(_norm(name))
        return rec["strength"] if rec else 0

    def worn_illu(self) -> int:
        """Illumination (ability 13) from what you wear."""
        names = {_norm(g.get("name")): g for g in (getattr(self.s.world, "gear", None) or {}).values()}
        total = 0
        for item, slot in worn_list(self.s.state.carrying or ""):
            if slot.lower().startswith("readied"):
                continue
            g = names.get(_norm(item))
            if g:
                total += int((g.get("abils") or {}).get(ILLU_ABIL) or 0)
        return total

    def need(self, room) -> int:
        """How much light a room needs from us to see in it (0 = none)."""
        r = self.s.world.room(tuple(room)) if room else None
        if r is None:
            return 0
        light = int(r.light or 0)
        if tuple(room) in self.seen_ok:
            return 0                              # seen in it without a light (race / gear we don't count)
        need = max(0, SEE_FLOOR - (light + self.worn_illu()))
        if tuple(room) in self.seen_dark:
            need = max(need, 1)
        return need

    def pick(self, need) -> dict | None:
        """The weakest carried light that's strong enough (keeps the good one for darker places)."""
        ok = [c for c in self.carried() if c["strength"] >= max(need, 1)]
        return min(ok, key=lambda c: (c["strength"], c["readied"] is False)) if ok else None

    def lit_strength(self) -> int:
        return self.strength_of(self.lit) if self.lit else 0

    def upcoming(self, n=LOOKAHEAD) -> list:
        """The rooms the next few steps of the walk go into."""
        b = self.bot
        mp = b.path if b.walking else None
        if mp is None or not getattr(mp, "steps", None):
            return []
        out, i = [], b.idx
        for k in range(n):
            j = i + k
            if j >= len(mp.steps):
                if not b.loop:
                    break
                j %= len(mp.steps)
            d = getattr(mp.steps[j], "dest", None)
            if d:
                out.append(tuple(d))
        return out

    # ------------------------------------------------------------ acting
    def _use(self, c, why) -> bool:
        b, now = self.bot, time.time()
        if self.pending and now - self.pending[1] < PENDING_SECS:
            return True                            # waiting for the game to answer the last 'use'
        if self.lit and _norm(self.lit) != _norm(c["name"]):
            b.send(f"rem {self.lit}")              # Stock refuses a second light ("You already have something lit!")
        self.pending = (c["name"], now)
        self._lit_at = now
        b.send(f"use {c['name']}")
        b.status = f"Lighting the {c['name']} — {why}"
        b.log(f"Auto-light: lighting the {c['name']} ({why})")
        return True

    def before_step(self, step) -> bool:
        """The walker's look-ahead: light up before stepping into a room too dark to see in. True = hold this tick."""
        if not self.on or self.bot.st.in_combat:
            return False
        dest = getattr(step, "dest", None)
        self._expect = tuple(dest) if dest else None
        n = self.need(dest) if dest else 0
        if n <= 0:
            return False
        if self.lit and (self.lit_strength() >= n or not self.pick(n)):
            return False                           # lit and strong enough (or nothing better to light)
        if self.pending:
            if time.time() - self.pending[1] < PENDING_SECS:
                return True
            self.pending = None                    # no answer: walk on (the dark line is the fallback)
            return False
        c = self.pick(n)
        if not c:
            if self.bot.ready("light_none_note", 300):
                self.bot.log(f"Auto-light: dark ahead ({dest[0]}/{dest[1]}) and no light strong enough in the pack")
            return False
        return self._use(c, "dark ahead")

    def tick(self) -> bool:
        """Every tick out of combat: react to the room we're in. True = took the tick."""
        if not self.on:
            return False
        b, st, now = self.bot, self.bot.st, time.time()
        if st.in_combat:
            return False
        if self.pending and now - self.pending[1] > PENDING_SECS * 2:
            self.pending = None
        if st.inv_seq != self._inv_seq:
            self._inv_seq = st.inv_seq
            self._read_inventory()
        if self._relight and (st.inv_seq != getattr(self, "_relight_seq", -1) or
                              now - getattr(self, "_relight_at", now) > 6):
            self._relight = False
            room = st.room
            dark_here = bool(st.view and st.view.name == "(dark)")
            n = max([self.need(room) if room else 0] + [self.need(r) for r in self.upcoming()])
            if (dark_here or n > 0) and not self.lit:
                c = self.pick(max(n, 1)) or (max(self.carried(), key=lambda c: c["strength"])
                                             if dark_here and self.carried() else None)
                if c:
                    return self._use(c, "a spare — the last one went out" if not dark_here else "can't see")
        if st.view_seq == self._view_seq or not st.view:
            return False
        self._view_seq = st.view_seq
        room = st.room or getattr(self, "_expect", None)
        if st.view.name == "(dark)":
            if room and not self.lit:
                r = self.s.world.room(tuple(room))
                if r is not None:
                    self.seen_dark[tuple(room)] = int(r.light or 0)
            if self.lit and not self.pending:
                # we think it's lit and still can't see: the belief is stale — look in the pack first
                b.log(f"Auto-light: can't see, though the {self.lit} should be lit — checking the pack")
                self.lit = None
                self._relight, self._relight_seq, self._relight_at = True, st.inv_seq, time.time()
                b.send("i")
                return True
            if not self.lit and not self.pending:
                cs = self.carried()
                n = self.need(room) if room else 0
                c = self.pick(n) or (max(cs, key=lambda c: c["strength"]) if cs else None)
                if c:
                    return self._use(c, "can't see")
            return False
        if not room:
            return False
        r = self.s.world.room(tuple(room))
        cfg = self.s.settings
        if r is not None and not self.lit and not self.pending and not st.view.players and \
                not (cfg.auto_light and cfg.light_cmd):
            # seen without a light of ours: this room needs none. Not with someone else here (their light counts)
            # or the old light command on (a light spell we can't see the state of)
            self.seen_ok[tuple(room)] = int(r.light or 0)
            self.seen_dark.pop(tuple(room), None)
        if self.lit and not self.pending and now - getattr(self, "_lit_at", 0) > 20 and self.need(room) <= 0 and \
                not any(self.need(x) > 0 for x in self.upcoming()):
            # visible without it, and so are the next few rooms: put it away (it burns while lit)
            name, self.lit = self.lit, None
            b.send(f"rem {name}")
            b.log(f"Auto-light: putting the {name} away — light enough here")
            return True
        return False

    def _read_inventory(self):
        """A fresh 'i': what's lit (when the game marks it), and whether a buy came to anything."""
        cs = parse_carried(self.s.state.carrying, self.by_name())
        readied = [c for c in cs if c["readied"]]
        if readied:
            self._inv_shows_readied = True
            self.lit = readied[0]["name"]
        elif self._inv_shows_readied and not self.pending:
            self.lit = None                        # (only trusted once the game has shown us '(Readied…)')
        if self.buying and not self.s.trips.trip:
            have = sum(c["qty"] for c in cs if _norm(c["name"]) == _norm(self.buying["name"]))
            nm = self.buying["name"]
            if have <= self.buying["had"]:
                _u, secs = self.backoff.get(nm, (0, BACKOFF_MIN // 2))
                secs = min(max(secs * 2, BACKOFF_MIN), BACKOFF_MAX)
                self.backoff[nm] = (time.time() + secs, secs)
                self.bot.log(f"Auto-light: the {nm} buy didn't come to anything — not trying again for "
                             f"{secs // 60} min")
            else:
                self.backoff.pop(nm, None)
            self.buying = None

    # ------------------------------------------------------------ buying
    def buy_plan(self, rooms):
        """(light record, how many) to buy for a walk through `rooms`, or None: nothing carried is strong enough for
        its darkest room, or the readied light is nearly spent and there's no spare."""
        cs = self.carried()
        darkest = max([self.need(r) for r in rooms] + [0])
        if darkest <= 0:
            return None                            # no room on it needs our light
        strong = [c for c in cs if c["strength"] >= darkest]
        readied = next((c for c in cs if c["readied"]), None)
        if readied is None and self.lit:
            readied = next((c for c in cs if _norm(c["name"]) == _norm(self.lit)), None)
        low = readied is not None and readied.get("left") is not None and readied["left"] * 30 / 60 < REORDER_MINS
        spares = sum(c["qty"] for c in strong) - (1 if readied is not None and readied in strong else 0)
        if strong and not (low and spares <= 0):
            return None
        want = darkest
        now = time.time()
        opts = []
        for rec in self.cat().values():
            if rec["strength"] < want or now < self.backoff.get(rec["name"], (0, 0))[0]:
                continue
            opts.append(rec)
        for rec in sorted(opts, key=lambda r: (r["strength"], r["name"])):
            if self.s.trips.stocked_at(rec["num"]):
                return rec, max(1, min(5, math.ceil(CARRY_HOURS / rec["burn_h"])))
        return None

    def lap_end(self, mp) -> bool:
        """End of a lap on a loop: short of a light strong enough for it → a buy trip (ShopTrips runs it). True =
        we're off."""
        if self.buying and time.time() - self.buying["t"] > 1800:
            self.buying = None                     # (never checked: the pack wasn't read after the trip)
        if not self.on or self.s.trips.trip or self.buying:
            return False
        rooms = [tuple(x.dest) for x in getattr(mp, "steps", []) if getattr(x, "dest", None)]
        plan = self.buy_plan(rooms)
        if not plan:
            return False
        rec, n = plan
        trips, st = self.s.trips, self.s.state
        shops = trips.stocked_at(rec["num"])
        price = min(p for _r, _s, p in shops)
        cash = int(st.wealth or 0)
        if price > 0:
            n = min(n, cash // price)
        if n <= 0:
            if self.bot.ready("light_broke_note", 600):
                self.bot.log(f"Auto-light: need a {rec['name']} for this loop but can't afford one")
            return False
        room, _d = trips._nearest([r for r, _s, _p in shops], int(self.s.settings.trip_max_steps or 60) * 2)
        if not room:
            if self.bot.ready("light_far_note", 600):
                self.bot.log(f"Auto-light: need a {rec['name']} for this loop — no shop near enough sells one")
            self.backoff[rec["name"]] = (time.time() + BACKOFF_MIN, BACKOFF_MIN)
            return False
        had = sum(c["qty"] for c in parse_carried(st.carrying, self.by_name()) if c["num"] == rec["num"])
        self.buying = {"name": rec["name"], "had": had, "t": time.time()}
        if not trips.start_trip(mp, "buy", room, [f"buy {rec['name']}"] * n,
                                f"auto-light: {n} {rec['name']} (strength {rec['strength']}) for the dark rooms"):
            self.buying = None
            return False
        return True

    # ------------------------------------------------------------ the game's lines
    def note_line(self, text):
        if not self.on:
            return
        line = PROMPT_LEAD_RE.sub("", text or "").strip()
        if not line:
            return
        b = self.bot
        m = LIT_RE.match(line)
        if m:
            self.lit, self.pending = m.group(1).strip(), None
            b.send("")                             # 'use' doesn't show the room again: look, or passive mobs are missed
            return
        m = REMOVED_RE.match(line) or NOT_LIT_RE.match(line)
        if m:
            if not self.lit or _norm(m.group(1)) == _norm(self.lit) or NOT_LIT_RE.match(line):
                self.lit = None
            return
        if ALREADY_LIT_RE.match(line):
            self.pending = None
            self._relight, self._relight_seq = False, self.bot.st.inv_seq
            b.send("i")                            # something's lit we don't know about: the pack says what
            return
        if RECHARGE_RE.match(line) or MAY_NOT_RE.match(line) or CANNOT_RE.match(line):
            if self.pending:
                self.bad.add(_norm(self.pending[0]))
                b.log(f"Auto-light: the {self.pending[0]} won't light ({line}) — not using it again")
            self.pending = None
            return
        for rx in BURNOUT_RES:
            m = rx.match(line)
            if m and rx is BURNOUT_RES[-1] and self.lit and not line.lower().startswith("your ") and \
                    _norm(m.group(1)) != _norm(self.lit):
                continue      # "Bob's torch is no longer lit!" isn't ours (0.8.201, bug hunt)
            if m and (self.lit or self.strength_of(m.group(1)) or rx is not BURNOUT_RES[-1]):
                was = self.lit or m.group(1)
                self.lit, self.pending = None, None
                b.log(f"Auto-light: the {was} went out — checking the pack for a spare")
                self._relight, self._relight_seq, self._relight_at = True, b.st.inv_seq, time.time()
                b.send("i")
                return
        if DARK_RE.search(line) and not self.lit and not self.pending:
            self._view_seq = -1                    # (the room display handles it: tick looks again)
