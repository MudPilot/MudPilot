"""Spell-scroll errand: after a level-up (or when you ask), buy and read the scrolls for spells you can now learn.

0.8.200, from the MudPlay review (Settings → Spells: "After a level-up, buy and read scrolls…", off by default).
  * Which spells: every spell your class can learn at your level (MME's own rules: Learnable / Learned From, magery
    type and level, the Classes list, ReqLevel, and the 'learnspell' steps in MME's textblocks) that isn't in your
    spell list. Earlier levels count too: scrolls restock on low chances, so last level's may be in now.
  * Where: shops whose stock slots hold a scroll for it (an item with ability 42, LearnSp — its value is the spell).
    A slot that never restocks, or a guild shop for another class, doesn't count.
  * Order: lowest level first, as far as the cash you carry goes. A shop on the loop wins; otherwise the one adding
    the fewest steps there and back to where we carry on; a tie goes to the cheaper scroll. Nearest shop first, and
    the plan is made again after every shop with what's really left in the purse.
  * At the counter: 'list' (closed on the prompt, not a fixed wait), skip "(You can't use)" and "(Too powerful)"
    rows and anything not in stock, 'buy', then 'read' — done when the spellbook gains it or the game says you
    already know it. A scroll you already carry is read without buying another (counted by name: two item records
    share 'scroll of resist lightning').
Never mid-fight, never while Hands off is on, and your Stop ends it.
"""
from __future__ import annotations

import math
import re
import time

from .gamestate import parse_item_list, CHAT_LINE_RE

LEARN_ABIL = 42                  # LearnSp: the item teaches the spell whose number is the ability's value
KAI = 5                          # MME magery type 5 = Kai (Mystics, Monks…)

# what the game says (Stock and Paradigm). A prompt can come first on the same line, so it's stripped first.
LEARN_RES = (re.compile(r"^You (?:read .+ and )?learn the spell (.+?)\.", re.I),
             re.compile(r"^You add (.+?) to your spellbook!?", re.I))
ALREADY_RE = re.compile(r"^You realize that you already know this scroll", re.I)
CANT_LEARN_RE = re.compile(r"^You don'?t know what to do with this", re.I)
BARRED_RE = re.compile(r"^You may not use that item", re.I)
BOUGHT_RE = re.compile(r"^You just bought (.+?) for (.+?)\.?\s*$", re.I)
AFFORD_RE = re.compile(r"^You cannot afford (.+?)\.?\s*$", re.I)
NO_STOCK_RE = re.compile(r"^You cannot buy (.+?) here!?", re.I)
NOT_KNOWN_RE = re.compile(r"^(.+?) is not a known item\.?", re.I)
NOT_SHOP_RE = re.compile(r"^You cannot BUY if you are not in a shop", re.I)
HEAVY_RE = re.compile(r"^You cannot carry that much", re.I)
LIST_HEAD_RE = re.compile(r"^The following items are for sale here", re.I)
LEVEL_UP_RE = re.compile(r"you are now level|you have gained a level|attain level \d+", re.I)
PROMPT_LEAD_RE = re.compile(r"^\s*(?:\[[^\]]*\]:?\s*)+")
CANT_USE_TAG, TOO_POWERFUL_TAG = "(you can't use)", "(too powerful)"
NAME_COL = 29                    # the list's name column is cut to 29 characters

LIST_SECS = 4.0                  # the 'list' window (closed early on the prompt)
SPELLS_SECS = 2.5                # the 'spells' / 'i' window before planning
ANSWER_SECS = 4.0                # 'buy' / 'read' answers
SOFT_SKIP_SECS = 1800            # out of stock / too powerful: not again for half an hour


def _norm(s) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def strip_prompt(text: str) -> str:
    return PROMPT_LEAD_RE.sub("", text or "").strip()


def class_num(world, name) -> int:
    name = _norm(name)
    return next((k for k, v in (getattr(world, "classes", None) or {}).items() if _norm(v.get("Name")) == name), 0)


def tb_learnspells(world) -> dict:
    """{class number: {spell numbers}} from MME textblock steps like 'check class:class 11:…:learnspell 5573'
    (trainer-taught spells MME's spell rows don't mark learnable). Cached per world."""
    cache = getattr(world, "_tb_learn_cache", None)
    if cache is not None:
        return cache
    out: dict = {}
    for act, _link, _cf in (getattr(world, "textblocks", None) or {}).values():
        for line in str(act or "").replace("\r", "").split("\n"):
            spells = [int(x) for x in re.findall(r"\blearnspell\s+(\d+)", line)]
            if not spells:
                continue
            classes = [int(x) for x in re.findall(r"\bclass\s+(\d+)", line)] or [0]     # 0 = any class
            for c in classes:
                out.setdefault(c, set()).update(spells)
    try:
        world._tb_learn_cache = out
    except AttributeError:
        pass
    return out


def learnable(world, sp, cls, level, tb=None) -> bool:
    """MudPlay's KnownSpellCatalog.IsUsable (MME's SpellIsUsable) for one spell row. The optional alignment check
    (abilities 97/98/112, 110/111/113) is left out: the shop's "(You can't use)" tag and the game's own 'read'
    answer catch those."""
    c = (getattr(world, "classes", None) or {}).get(cls) or {}
    cmag, cmlvl = int(c.get("MageryType") or 0), int(c.get("MageryLVL") or 0)
    smag, req = int(sp.get("Magery") or 0), int(sp.get("ReqLevel") or 0)
    flag = int(sp.get("Learnable") or 0) == 1
    tb = tb_learnspells(world) if tb is None else tb
    taught = int(sp.get("Number") or 0) in (tb.get(cls, set()) | tb.get(0, set()))
    if not (flag or len(str(sp.get("Learned From") or "")) >= 5 or (smag == KAI and req >= 1) or taught):
        return False
    if smag:
        if cmag != smag or (cmlvl and cmlvl < int(sp.get("MageryLVL") or 0)):
            return False
        if cmag != KAI and not flag and not taught:
            return False
    classes = str(sp.get("Classes") or "").strip()
    if classes and classes != "(*)" and f"({cls})" not in classes:
        return False
    return int(level or 0) >= req


def scroll_items(world) -> dict:
    """{spell number: [item numbers]} — every item with ability 42 (LearnSp)."""
    out: dict = {}
    for num, g in (getattr(world, "gear", None) or {}).items():
        sp = (g.get("abils") or {}).get(LEARN_ABIL)
        if sp:
            out.setdefault(int(sp), []).append(int(num))
    return out


def parse_list(lines) -> list:
    """The shop's 'list' body → [(name, quantity, price text, can't use, too powerful)]. Item names have spaces in
    them ('rope and grapple'), so the name column is cut where the header's 'Quantity' starts; the quantity is the
    first number after it and the price is whatever follows (a spell shop's wide prices start left of 'Price')."""
    rows, qcol = [], -1
    for raw in lines:
        line = raw.rstrip()
        t = line.strip()
        if not t or LIST_HEAD_RE.match(t):
            continue
        if qcol < 0:
            q, p = line.find("Quantity"), line.find("Price")
            if q >= 0 and p > q:
                qcol = q
                continue
            m = re.match(r"^(.*?\S)\s+(\d+)\s+(.+)$", t)       # no header seen: best guess
            if not m:
                continue
            name, qty, price = m.group(1), int(m.group(2)), m.group(3)
        else:
            if set(t) == {"-"} or len(line) <= qcol:
                continue
            name, rest = line[:qcol].strip(), line[qcol:].strip()
            m = re.match(r"^(\d+)(?:\s+(.*))?$", rest)
            if not name or not m:
                continue
            qty, price = int(m.group(1)), (m.group(2) or "").strip()
        low = price.lower()
        rows.append((name, qty, price, low.endswith(CANT_USE_TAG), low.endswith(TOO_POWERFUL_TAG)))
    return rows


def list_row_for(rows, item_name):
    """The list row for an item (the name column is cut to 29 characters)."""
    n = _norm(item_name)
    for r in rows:
        rn = _norm(r[0])
        if rn == n or (len(rn) >= NAME_COL - 1 and n.startswith(rn)):
            return r
    return None


def carried_counts(carrying) -> dict:
    """{item name (lower): count} from 'You are carrying …'."""
    out: dict = {}
    for qty, name in parse_item_list(carrying or ""):
        name = _norm(re.sub(r"\s*\([^)]*\)\s*$", "", name))
        out[name] = out.get(name, 0) + qty
    return out


class ScrollErrand:
    def __init__(self, session):
        self.s = session
        self.pending = None          # why we want to go ("level-up", "you asked") — None = nothing to do
        self.trip = None             # the errand under way (see start())
        self.never: set = set()      # spell numbers the game / shop says we can't ever learn (this session)
        self.soft: dict = {}         # spell number -> time: out of stock / too powerful — skipped for a while
        self.learned: list = []      # spell names learned on this errand
        self._known_extra: set = set()   # names learned since the last 'spells' read
        self.forced = False          # the button asked for it (runs even with the setting off)

    # ------------------------------------------------------------ what we want
    @property
    def on(self) -> bool:
        return bool(getattr(self.s.settings, "auto_scrolls", False))

    def known_names(self) -> set:
        st = self.s.settings
        names = {_norm(r[1]) for r in (st.known_spell_rows or []) if len(r) > 1 and r[1]}
        names |= {_norm(sp.get("Name")) for sp in self.s.known_spell_dicts()}
        shorts = {_norm(x) for x in (self.s.state.known_spells or st.known_spells or [])}
        return names | self._known_extra | {("short:" + x) for x in shorts}

    @staticmethod
    def _known(sp, known) -> bool:
        return _norm(sp.get("Name")) in known or ("short:" + _norm(sp.get("Short"))) in known

    def wanted(self) -> list:
        """Spell rows we can learn now and don't know, that a scroll teaches — lowest level first."""
        w, st, cfg = self.s.world, self.s.state, self.s.settings
        cls = class_num(w, st.char_class or cfg.char_class)
        level = int(st.level or cfg.char_level or 0)
        if not cls or not level:
            return []
        known, now = self.known_names(), time.time()
        tb = tb_learnspells(w)
        scrolls = scroll_items(w)
        out, seen = [], set()
        for num in scrolls:
            sp = (getattr(w, "spells", None) or {}).get(num)
            if not sp or num in self.never or now - self.soft.get(num, 0) < SOFT_SKIP_SECS:
                continue
            if not learnable(w, sp, cls, level, tb) or self._known(sp, known):
                continue
            if _norm(sp.get("Name")) in seen:
                continue                                  # (duplicate spell records under one name)
            seen.add(_norm(sp.get("Name")))
            out.append(sp)
        return sorted(out, key=lambda sp: (int(sp.get("ReqLevel") or 0), _norm(sp.get("Name"))))

    def carried_scrolls(self, wanted=None) -> list:
        """[(item name, spell row)] for scrolls already in the pack that teach a wanted spell."""
        w = self.s.world
        have = carried_counts(self.s.state.carrying)
        sc = scroll_items(w)
        out = []
        for sp in (self.wanted() if wanted is None else wanted):
            for it in sc.get(int(sp["Number"]), []):
                nm = w.item_name(it)
                if have.get(_norm(nm)):
                    out.append((nm, sp))
                    break
        return out

    # ------------------------------------------------------------ distances (tests stub these)
    def _dist_from(self, here) -> dict:
        b = self.s.bot
        return self.s.world.dist_map(tuple(here), level=b.route_level(), have=b.held_items() or set(),
                                     avoid=b.avoid_set() or None) or {}

    def _dist_to(self, room) -> dict:
        b = self.s.bot
        return self.s.world.dist_map(tuple(room), level=b.route_level(), have=b.held_items() or set(),
                                     avoid=b.avoid_set() or None, reverse=True) or {}

    def limit(self) -> int:
        return max(int(self.s.settings.trip_max_steps or 60) * 2, 60)

    def plan(self, here, resume=None, route_rooms=(), budget=None, skip_rooms=()):
        """The next shop: {"room", "shop", "buys": [(item num, spell row, price)], "dist"} or None, and notes
        (unaffordable / nowhere sold) for the log."""
        w, trips = self.s.world, self.s.trips
        want = self.wanted()
        notes = {"broke": [], "nowhere": []}
        if not want or not here:
            return None, notes
        budget = int(self.s.state.wealth or 0) if budget is None else int(budget)
        d_here = self._dist_from(here)
        d_on = self._dist_to(resume) if resume and tuple(resume) != tuple(here) else None
        route_rooms = set(tuple(r) for r in route_rooms or ())
        sc = scroll_items(w)
        picks = []
        for sp in want:
            opts = []
            for it in sc.get(int(sp["Number"]), []):
                for room, shop, price in trips.stocked_at(it):
                    if room in skip_rooms or room not in d_here or d_here[room] > self.limit():
                        continue
                    added = d_here[room] + ((d_on.get(room, 10 ** 4) if d_on is not None else d_here[room]))
                    opts.append((0 if room in route_rooms else 1, added, price, room, shop, it))
            if not opts:
                notes["nowhere"].append(sp["Name"])
                continue
            best = min(opts)
            if best[2] > budget:
                notes["broke"].append(sp["Name"])
                continue
            budget -= best[2]
            picks.append((best[3], best[4], best[5], sp, best[2]))
        if not picks:
            return None, notes
        room = min({p[0] for p in picks}, key=lambda r: (d_here.get(r, 10 ** 6), r))
        buys = [(p[2], p[3], p[4]) for p in picks if p[0] == room]
        return {"room": room, "shop": next(p[1] for p in picks if p[0] == room), "buys": buys,
                "dist": d_here.get(room, 0)}, notes

    # ------------------------------------------------------------ starting
    def want_now(self, why="you asked") -> bool:
        """The Spells tab's button: look for scrolls as soon as we're free — even with the automatic errand
        switched off (you asked for this one)."""
        if self.trip:
            return False
        self.pending, self.forced = why, True
        return True

    def _free(self) -> bool:
        s, b, st = self.s, self.s.bot, self.s.state
        return bool(s.telnet.connected and st.room and not st.dead and not st.in_combat and not st.resting
                    and not getattr(s.settings, "hands_off", False) and not getattr(b, "dead_hold", 0)
                    and not s.trips.trip and not (b.errands.active or b.errands.asking)
                    and not (st.view and st.view.monsters)
                    # a follower walking off to a shop would break the party: the leader's errand only
                    and not getattr(getattr(b, "x", None), "_following", None))

    def lap_end(self, mp) -> bool:
        """End of a lap: off on the errand if one's due. True = we're off."""
        if not ((self.on or self.forced) and self.pending) or self.trip or not self._free():
            return False
        return self.start(back=(mp, True))

    def start(self, back=None) -> bool:
        b = self.s.bot
        why, self.pending = self.pending or "you asked", None
        self.learned, self._known_extra = [], set()
        self.trip = {"phase": "reading", "t": time.time(), "back": back, "why": why, "visited": set(),
                     "next_at": 0, "sent": False, "stop": None, "queue": [], "cur": None, "forced": self.forced}
        self.forced = False
        if back is not None:
            b.walking = False                       # (the loop picks up again when we're done)
        self.s.log(f"Spell scrolls: looking for spells to learn ({why})")
        return True

    # ------------------------------------------------------------ running
    def tick(self):
        t, s, b, st = self.trip, self.s, self.s.bot, self.s.state
        if not self.on and not (t or {}).get("forced") and not (self.forced and not t):
            if t:
                self._finish("switched off", back=True)
            self.pending = None
            return
        if not t:
            # the button's errand starts as soon as nothing's walking; a level-up's waits for the end of a lap (it
            # mustn't walk off while you're playing by hand between loops)
            if self.pending and self.forced and not b.walking and not b.path and self._free():
                self.start()
            return
        now = time.time()
        if not s.telnet.connected or st.dead:
            self.trip = None
            return
        if getattr(s.settings, "hands_off", False):
            return
        if getattr(b, "_user_stop_at", 0) > t["t"]:
            self._finish("you stopped it", back=False)
            return
        if getattr(getattr(b, "x", None), "_following", None):
            # made a follower mid-errand: walking off to a shop would break the party (0.8.201, bug hunt)
            self._finish("joined someone's party", back=False)
            return
        if st.in_combat or st.resting:
            return
        ph = t["phase"]
        if ph == "reading":
            # the spell list and the pack first: what we know now, what we carry, what's in the purse
            if not t["sent"]:
                t["sent"], t["next_at"] = True, now + SPELLS_SECS
                t["spells_at"], t["inv_seq"] = s.settings.known_spells_at, st.inv_seq
                b.send("spells")
                b.send("i")
                return
            fresh = s.settings.known_spells_at != t["spells_at"] and st.inv_seq != t["inv_seq"]
            if fresh or now >= t["next_at"]:
                self._next_stop()
            return
        if ph == "going":
            stop = t["stop"]
            if st.room == stop["room"] and not b.walking:
                t["phase"], t["sent"], t["next_at"] = "list", False, now + 0.8
            elif not b.walking and now - t["went"] > 5:
                if str(b.status).startswith(("Stopped by you", "Hung up")):
                    self._finish("you stopped it", back=False)
                elif now - t["went"] > 30:
                    self.s.log(f"Spell scrolls: couldn't get to {self._where(stop['room'])} — skipping it")
                    t["visited"].add(stop["room"])
                    self._next_stop()
            elif now - t["went"] > 900:
                self._finish("the walk took too long")
            return
        if now < t["next_at"]:
            return
        if ph == "list":
            if not t["sent"]:
                t.update(sent=True, list_lines=[], list_head=0.0, list_at=now)
                b.send("list")
                return
            # closed on the prompt after the header (waiting out the full window wasted time), else after 4 s
            if (t["list_head"] and st.last_prompt > t["list_head"]) or now - t["list_at"] > LIST_SECS:
                self._after_list()
            return
        if ph == "read_carried" and t["cur"] is None and not t["queue"]:
            self._next_stop()
            return
        if ph in ("buy", "read", "read_carried"):
            cur = t["cur"]
            if cur is None:
                if not t["queue"]:
                    t["phase"], t["sent"] = "check", False
                    return
                cur = t["cur"] = dict(t["queue"].pop(0), step=("read" if ph == "read_carried" else "buy"))
                cur["sent_at"] = 0
            if not cur["sent_at"]:
                cur["sent_at"], cur["answer"] = now, None
                b.send(f"{cur['step']} {cur['name']}")
                b.status = f"Spell scrolls: {cur['step']}ing {cur['name']}"
                return
            if cur["answer"] is None and now - cur["sent_at"] < ANSWER_SECS:
                return
            self._answered(cur)
            return
        if ph == "check":
            # what's left in the purse, then the next shop
            if not t["sent"]:
                t["sent"], t["inv_seq"], t["next_at"] = True, st.inv_seq, now + SPELLS_SECS
                b.send("i")
                return
            if st.inv_seq != t["inv_seq"] or now >= t["next_at"]:
                self._next_stop()

    def _where(self, room) -> str:
        r = self.s.world.room(tuple(room))
        return f"{r.name if r else 'the shop'} ({room[0]}/{room[1]})"

    def _resume_room(self):
        back = (self.trip or {}).get("back")
        mp = back[0] if back else None
        if mp is not None and getattr(mp, "steps", None):
            return next((x.room for x in mp.steps if x.room), None), [x.room for x in mp.steps if x.room]
        return self.s.state.room, []

    def _next_stop(self):
        t, st, b = self.trip, self.s.state, self.s.bot
        carried = [c for c in self.carried_scrolls() if c[0].lower() not in t.get("read_tried", set())]
        if carried:
            # already in the pack (bought last time and never read, or looted): read those first, no shop needed
            t.setdefault("read_tried", set()).update(c[0].lower() for c in carried)
            t["queue"] = [{"name": nm, "spell": sp, "item": None, "price": 0} for nm, sp in carried]
            t["phase"], t["cur"] = "read_carried", None
            return
        resume, rooms = self._resume_room()
        stop, notes = self.plan(st.room, resume, rooms, skip_rooms=t["visited"])
        if stop is None:
            why = "nothing more to buy"
            if notes["broke"]:
                why = f"not enough cash on you for {', '.join(notes['broke'][:4])}"
            elif notes["nowhere"] and not self.learned:
                why = f"no shop within {self.limit()} steps sells {', '.join(notes['nowhere'][:4])}"
            self._finish(why)
            return
        w = self.s.world
        stop["names"] = [w.item_name(it) for it, _sp, _p in stop["buys"]]
        t["stop"] = stop
        t["visited"].add(stop["room"])
        self.s.log(f"Spell scrolls: {self._where(stop['room'])} for {', '.join(stop['names'])} "
                   f"({sum(p for _i, _s, p in stop['buys']):,} copper)")
        if st.room == stop["room"]:
            t["phase"], t["sent"], t["next_at"] = "list", False, 0
            return
        t["phase"], t["went"] = "going", time.time()
        if not b.goto(stop["room"]):
            # (the room is in t["visited"] now, so the next plan picks another shop)
            self.s.log(f"Spell scrolls: no way to {self._where(stop['room'])} — skipping it")
            t["phase"], t["sent"], t["inv_seq"], t["next_at"] = "check", True, st.inv_seq, 0

    def _after_list(self):
        t = self.trip
        rows = parse_list(t.get("list_lines") or [])
        w, stop, queue, now = self.s.world, t["stop"], [], time.time()
        skipped = {"cant": [], "power": [], "out": []}
        for it, sp, price in stop["buys"]:
            nm = w.item_name(it)
            row = list_row_for(rows, nm) if t.get("list_head") else None
            if row is not None and row[3]:
                self.never.add(int(sp["Number"]))         # never learnable by this character: no coin on it
                skipped["cant"].append(nm)
                continue
            if row is not None and row[4]:
                self.soft[int(sp["Number"])] = now
                skipped["power"].append(nm)
                continue
            if t.get("list_head") and row is None:
                self.soft[int(sp["Number"])] = now        # shops list only what's in stock
                skipped["out"].append(nm)
                continue
            queue.append({"name": nm, "spell": sp, "item": it, "price": price})
        for k, label in (("cant", "marked \"You can't use\""), ("power", "marked \"Too powerful\""),
                         ("out", "out of stock")):
            if skipped[k]:
                self.s.log(f"Spell scrolls: {label} — not buying {', '.join(skipped[k])}")
        if not t.get("list_head"):
            self.s.log("Spell scrolls: no stock list from the shop — trying the buys anyway")
        t["queue"], t["cur"], t["phase"] = queue, None, "buy"

    def _answered(self, cur):
        """One 'buy' / 'read' answered (or timed out)."""
        t, b = self.trip, self.s.bot
        ans, sp = cur["answer"], cur["spell"]
        num = int(sp["Number"])
        if cur["step"] == "buy":
            if ans == "bought":
                cur.update(step="read", sent_at=0)       # read it straight away
                return
            if ans == "afford":
                self.s.log(f"Spell scrolls: can't afford {cur['name']} — moving on")
            elif ans in ("nostock", "unknown"):
                self.soft[num] = time.time()
                self.s.log(f"Spell scrolls: no sale on {cur['name']} here — moving on")
            elif ans == "notshop":
                self.s.log("Spell scrolls: not in a shop after all — on to the next")
                t["queue"] = []
            elif ans == "heavy":
                t["cur"] = None
                self._finish(f"too heavy to carry {cur['name']}")
                return
            else:
                self.s.log(f"Spell scrolls: no answer to 'buy {cur['name']}' — moving on")
            t["cur"] = None
            return
        # read
        if ans in ("learned", "already"):
            self._known_extra.add(_norm(sp.get("Name")))
            if ans == "learned":
                self.learned.append(sp["Name"])
                self.s.log(f"Spell scrolls: learned {sp['Name']} from {cur['name']}")
                b._spells_asked = False               # read the new list (attack spells, blesses)
            else:
                self.s.log(f"Spell scrolls: already know {sp['Name']} — {cur['name']} wasn't needed")
        elif ans in ("cant", "barred"):
            self.never.add(num)
            self.s.log(f"Spell scrolls: can't learn {sp['Name']} ({'barred from' if ans == 'barred' else 'no use for'} "
                       f"{cur['name']}) — not trying it again")
        else:
            self.soft[num] = time.time()
            self.s.log(f"Spell scrolls: read {cur['name']} but {sp['Name']} wasn't learned — it stays in the pack")
        t["cur"] = None

    def _finish(self, why, back=True):
        t, self.trip = self.trip, None
        if t is None:
            return
        got = f" — learned {', '.join(self.learned)}" if self.learned else " — nothing learned"
        self.s.log(f"Spell scrolls: done ({why}){got}")
        if self.learned:
            self.s.bot._spells_asked = False
        b = t.get("back")
        if back and b and b[0] is not None:
            mp, loop = b
            self.s.log(f"Spell scrolls: back to {mp.title}")
            here = self.s.state.room
            steps = [x.room for x in getattr(mp, "steps", []) if x.room]
            if here and steps and here not in steps:
                self.s.bot.goto_bg(steps[0], then=mp)
            else:
                self.s.bot.start_path(mp, loop=loop)

    def cancel(self, why=""):
        if self.trip:
            self._finish(why or "cancelled", back=False)
        self.pending = None

    # ------------------------------------------------------------ the game's lines
    def note_line(self, text):
        raw = text or ""
        if self.on and not self.trip and LEVEL_UP_RE.search(strip_prompt(raw)) and \
                not CHAT_LINE_RE.match(strip_prompt(raw)):
            # (not someone's gossip / tell that says "now level 20" — 0.8.201, bug hunt)
            self.pending = "level-up"
        t = self.trip
        if not t:
            return
        line = strip_prompt(raw)
        if t["phase"] == "list" and t.get("sent"):
            if LIST_HEAD_RE.match(line):
                t["list_head"] = time.time()
                return
            if t.get("list_head"):
                t["list_lines"].append(raw.rstrip())
            return
        cur = t.get("cur")
        if not cur or not cur.get("sent_at") or cur.get("answer"):
            return
        if cur["step"] == "buy":
            for rx, ans in ((BOUGHT_RE, "bought"), (AFFORD_RE, "afford"), (NO_STOCK_RE, "nostock"),
                            (NOT_SHOP_RE, "notshop"), (HEAVY_RE, "heavy"), (NOT_KNOWN_RE, "unknown")):
                if rx.match(line):
                    cur["answer"] = ans
                    return
            return
        for rx in LEARN_RES:
            if rx.match(line):
                cur["answer"] = "learned"
                return
        for rx, ans in ((ALREADY_RE, "already"), (CANT_LEARN_RE, "cant"), (BARRED_RE, "barred")):
            if rx.match(line):
                cur["answer"] = ans
                return
