"""Practice server: a tiny MajorMUD look-alike built from your imported MME data.
Real room names and exits, wandering monsters from MME, doors, combat, resting,
cash drops. Useful for testing paths/combat settings without risking a character.

    python -m mudpilot.simserver --port 2323
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import time

from .worlddb import WorldDB, DIR_WORDS, norm_dir, DIRS
from . import config
from .spells import calc as spell_calc, is_attack_spell

CY, GR, MG, YE, WH, RS = "\x1b[1;36m", "\x1b[0;32m", "\x1b[1;35m", "\x1b[1;33m", "\x1b[0;37m", "\x1b[0m"


class Player:
    def __init__(self, world, start):
        self.world = world
        self.room = start
        self.hp = self.max_hp = 120
        self.ma = self.max_ma = 400
        self.resting = False
        self.combat = None
        self.open_doors: set = set()
        self.buffs: dict = {}   # name -> expires
        self.regen: dict = {}   # mana-regen buff -> (expires, rolled value)


class Sim:
    def __init__(self, world: WorldDB, seed=1, mob_rate=0.15, start=(1, 1), gates=None):
        self.world = world
        # gates: True or a dict of Gates() options — keys, items, tolls, casts, level gates played honestly
        self.gates = (Gates(self, **(gates if isinstance(gates, dict) else {})) if gates else None)
        self.start = start
        self.rng = random.Random(seed)
        self.mob_rate = mob_rate
        self.mobs: dict = {}      # room -> list[monster rec]
        self.items: dict = {}     # room -> list[(qty, name)]
        self.players = []
        from .spells import class_spells
        druid = next((k for k, v in world.classes.items() if v.get("Name") == "Druid"), 0)
        self.known = class_spells(world, druid, 38) if druid else []
        self.pool = [m for m in world.monsters.values() if m["exp"] > 0 and m["in_game"] and m["hp"] < 80]

    def spawn(self, room):
        if getattr(self, "gates", None) is not None:
            return self.gates.residents(room)
        if room not in self.mobs:
            n = 0
            if self.rng.random() < self.mob_rate:
                n = self.rng.choice([1, 1, 2, 2, 3, 4])
            self.mobs[room] = [self.rng.choice(self.pool) for _ in range(n)]
        return self.mobs[room]

    def action_exits(self, room) -> list:
        """[(exit's room, dir, exit)] whose lever / button is worked from `room`: the room's own hidden exits
        (actions with no 'at'), and other rooms' exits whose actions are done here."""
        idx = getattr(self, "_act_idx", None)
        if idx is None:
            idx = self._act_idx = {}
            for rk, r in self.world.rooms.items():
                for dd, e in r.exits.items():
                    for a in getattr(e, "actions", None) or []:
                        at = tuple(a["at"]) if a.get("at") else rk
                        lst = idx.setdefault(at, [])
                        if (rk, dd, e) not in lst:
                            lst.append((rk, dd, e))
        return idx.get(tuple(room), [])

    quest = {}                                         # ability → value the practice character has (abil gates)

    def drop_for(self, room, low, d):
        """A random drop taken from `room` with this command / direction: the room it lands in, or None."""
        opts = []
        for e, gate in (getattr(self.world, "scatter", None) or {}).get(tuple(room), ()):
            if (d and e.dir == d) or (not d and e.accepts(low)):
                if all(self._gate(g) for g in gate):
                    opts.append(e.to)
        return self.rng.choice(sorted(set(opts))) if opts else None

    def _gate(self, g):
        verb, a, v = g
        val = self.quest.get(a, 0)
        return (val >= v) if verb == "checkability" else (val == v) if verb == "testability" else not val

    def render(self, p: Player) -> str:
        r = self.world.room(p.room)
        g = getattr(self, "gates", None)
        if g is not None and g.too_dark(p, r):
            # (gates' dark_at: MME's room light at or below it, and no light of your own — you see the exits only)
            ex = [DIR_WORDS[d] for d in DIRS if r.exits.get(d) and r.exits[d].visible]
            return "\r\n".join(["The room is very dark - you can't see anything",
                                 f"{GR}Obvious exits: " + (", ".join(ex) if ex else "NONE!!!") + RS])
        out = [f"{CY}{r.name}{RS}"]
        items = self.items.get(p.room)
        if items:
            out.append(f"{CY}You notice " + ", ".join(f"{q} {n}" if q > 1 else n for q, n in items) + f" here.{RS}")
        mobs = self.spawn(p.room)
        if mobs:
            out.append(f"{MG}Also here: " + ", ".join(m["name"] for m in mobs) + f".{RS}")
        ex = []
        for d in DIRS:
            e = r.exits.get(d)
            if e and e.visible:
                w = DIR_WORDS[d]
                if e.door:
                    is_open = (self.gates.door_open(p.room, d, e) if getattr(self, "gates", None) is not None
                               else (p.room, d) in p.open_doors)
                    w = ("open door " if is_open else "closed door ") + w
                ex.append(w)
        out.append(f"{GR}Obvious exits: " + (", ".join(ex) if ex else "NONE!!!") + RS)
        return "\r\n".join(out)

    def prompt(self, p: Player) -> str:
        rest = (" (Meditating) " if getattr(p, "medit", False) else " (Resting) ") if p.resting else ""
        return f"{WH}[HP={p.hp}/MA={p.ma}]:{rest}{RS}"


# ------------------------------------------------------------------ honest gates (Sim(..., gates=Gates(...)))
# The plain practice server walks you through anything MME draws and answers "Your path is blocked." for every key,
# item, toll, cast and level exit. With gates on it plays them the way the realm does, so a walk sweep can go
# through them instead of skipping them: locked doors you unlock / pick / bash, keys and items you carry (keys wear
# out), tolls out of your purse, traps that hurt, class / race / alignment / ability / level gates, the spells
# exits and rooms cast on you (the golden idol teleport in the earthen catacombs, rivers without a raft, sea
# currents, random drops), room commands run from their MME textblocks, hidden exits you search for or open with
# their actions (in order, with the item they need), shops you buy from. The game's own wording where MudPilot
# already knows it ("The door is locked.", "You successfully unlocked the door.", "You cannot afford …");
# messages MME doesn't carry (a textblock's 'message N') are left out.

GATE_KEY_RE = re.compile(r"^\(Key:\s*(\d+)\s*(?:\[or\s+(any|\d+)\s+picklocks(/strength)?\])?\)", re.I)
GATE_DOOR_RE = re.compile(r"^\((?:Door|Gate)\s*(?:\[(any|\d+)\s+picklocks(/strength)?\])?\)", re.I)
GATE_ITEM_RE = re.compile(r"^\((Item|Ticket/Item|Ticket):\s*(\d+)", re.I)
CAST_EX_RE = re.compile(r"\(Cast:\s*pre-(\d+),\s*post-(\d+)\)", re.I)
TOLL_EX_RE = re.compile(r"\(Toll:\s*(\d+)\)", re.I)
TRAP_EX_RE = re.compile(r"\(Trap,\s*(\d+)\s*damage\)", re.I)
LEVEL_EX_RE = re.compile(r"\(Level:\s*(\d+)\s*to\s*(\d+)\)", re.I)
CLASS_EX_RE = re.compile(r"\((Class|Race):\s*(\d+)\s*OK,\s*(\d+)\s*NO\)", re.I)
ALIGN_EX_RE = re.compile(r"\(Alignment:\s*(\w+)\s*to\s*(\w+)\)", re.I)
ABIL_EX_RE = re.compile(r"\(Ability:\s*(\d+)\s*w/value\s*(-?\d+)\s*to\s*(-?\d+)\)", re.I)
SPELLTRAP_RE = re.compile(r"\(Spell Trap:\s*(\d+)\)", re.I)
PRICE_EX_RE = re.compile(r"\(Price:\s*(\d+)\)", re.I)
ALIGNS = ["saint", "good", "lawful", "neutral", "seedy", "outlaw", "criminal", "villain", "fiend"]
DEFAULT_KIT = ("golden idol", "rope and grapple")
WORN = ("a mithril longsword (Wielded)", "woodland robes (Worn)", "an elven cloak (Worn)", "silver gloves (Worn)")
COPPER = (1, 10, 100, 10000, 1000000)        # copper, silver, gold, platinum, runic
DOOR_SECS = 120          # an opened door swings shut (and locks again) after this long
VOYAGE_SECS = 0.2        # a boat's round at sea, sped up (the real ones take minutes)
HIDDEN_SECS = 90         # a found / opened hidden exit stays open this long
BLOCKED = "Your path is blocked."
NO_EFFECT = "Your command had no effect."
_FAIL = object()


class Gates:
    def __init__(self, sim, kit=DEFAULT_KIT, level=55, cls="Mage", race="Human", align="Good", cash=500000,
                 picklocks=0, strength=60, abil=None, hp=None, timed=(), seed=11, search_rate=0.5,
                 pick_rate=0.6, bash_rate=0.35, chance_rate=0.6, trap_rate=0.5, dark_at=None, move_delay=0.0):
        import collections
        self.move_delay = move_delay                 # seconds before a move's room shows (the real realm's pace)
        self.dark_at = dark_at                       # None: every room lit; else MME light at or below this is dark
        import sqlite3
        self.sim, self.w = sim, sim.world
        self.rng = random.Random(seed)
        self.level, self.cls, self.race, self.align = level, cls, race, align
        self.cash, self.picklocks, self.strength = cash, picklocks, strength
        self.abil = dict(abil or {})
        self.hp = hp or max(60, 13 * level)
        self.rates = {"search": search_rate, "pick": pick_rate, "bash": bash_rate, "chance": chance_rate,
                      "trap": trap_rate}
        self.kit = []
        for k in kit or ():
            num = k if isinstance(k, int) else (self.w.item_names.get(str(k).lower()) or {}).get("num")
            if num:
                self.kit.append(int(num))
        self.cls_num = next((n for n, v in self.w.classes.items() if (v.get("Name") or "").lower() == cls.lower()), None)
        self.race_num = next((n for n, v in self.w.races.items() if (v.get("Name") or "").lower() == race.lower()), None)
        self.doors = {}       # door key -> {"open": until, "unlocked": bool}
        self.opened = {}      # (room, dir) -> until: hidden exits found / opened, remote actions
        self.progress = {}    # (room, dir) -> [action numbers done, in order]
        self.timed = set(timed)
        self.events = []      # (what, room, detail) — the walk sweep reads these
        self.count = collections.Counter()
        self.room_tb = {}
        try:
            con = sqlite3.connect(self.w.path)
            self.room_tb = {(m, r): tb for m, r, tb in con.execute("SELECT * FROM room_tb")}
            con.close()
        except Exception:
            pass

    def note(self, what, room, detail=""):
        self.count[what] += 1
        self.events.append((what, tuple(room) if room else None, detail))
        del self.events[:-400]

    def setup(self, p):
        import collections
        p.items = collections.Counter(self.kit)
        p.uses = {}
        p.cash, p.level = self.cash, self.level
        p.abil = dict(self.abil)
        p.hp = p.max_hp = self.hp
        p.spells_on = {}

    # ------------------------------------------------------------ what you are and carry
    def has(self, p, num):
        return p.items.get(int(num), 0) > 0

    def is_key(self, num):
        return int((self.w.gear.get(int(num)) or {}).get("ItemType") or -1) == 7

    def item_named(self, p, words):
        """An item you carry whose name holds every word typed ('use lion key' → golden lion key)."""
        ws = [x for x in words if x not in ("the", "a", "an")]
        typed = " ".join(ws)
        held = [num for num, q in p.items.items() if q > 0]
        for ok in (lambda nm: nm == typed, lambda nm: nm.startswith(typed),
                   lambda nm: all(any(n.startswith(x) for n in nm.split()) for x in ws)):
            for num in held:                          # the whole name first, then its start, then any words
                if ws and ok(self.w.item_name(num).lower()):
                    return num
        return None

    def inventory(self, p):
        carry = ([f"{p.cash} copper farthings"] if p.cash else []) + list(WORN)
        keys = []
        for num, q in sorted(p.items.items()):
            if q <= 0:
                continue
            nm = self.w.item_name(num)
            (keys if self.is_key(num) else carry).append(f"{q} {nm}" if q > 1 else nm)
        out = ["You are carrying " + (", ".join(carry) or "Nothing!")]
        out.append("You have the following keys:  " + ", ".join(keys) if keys else "You have no keys.")
        out += [f"Wealth: {p.cash} copper farthings", "Encumbrance: 812/2400 - Light [33%]"]
        return out

    def stat(self, p, user):
        return [f"Name: {(user.split() or ['Tester'])[0].capitalize() + ' Abil':<20}Lives/CP:      9/0",
                f"Race: {self.race:<12}Exp: 123456     Perception:  60",
                f"Class: {self.cls:<11}Level: {p.level:<8} Stealth:     40",
                f"Hits:  {p.hp}/{p.max_hp}   Armour Class: 30/5   Thievery:    0",
                f"Mana:  {p.ma}/{p.max_ma}   Spellcasting: 120  Traps:       0",
                f"                              Picklocks:   {self.picklocks}",
                f"Strength: {self.strength}   Agility: 50   Tracking:    0",
                "Intellect: 80   Health: 60   Martial Arts: 0",
                "Willpower: 70   Charm: 50    MagicRes:    60"]

    # ------------------------------------------------------------ doors
    def door_key(self, room, d):
        r = self.w.room(room)
        ex = r.exits.get(d) if r else None
        back = self.w.room(ex.to) if ex is not None else None
        for bd, be in (back.exits.items() if back else []):
            if be.to == tuple(room) and be.door:
                return min((tuple(room), d), (ex.to, bd))
        return (tuple(room), d)

    @staticmethod
    def lock_of(ex):
        """(key item or None, picklocks/strength needed ('any', a number) or None, bashable)."""
        m = GATE_KEY_RE.match(ex.etype or "")
        if m:
            return int(m.group(1)), (m.group(2) or None), bool(m.group(3))
        m = GATE_DOOR_RE.match(ex.etype or "")
        if m and m.group(1):
            return None, m.group(1), bool(m.group(2))
        return None, None, False

    def lockable(self, ex):
        key, need, _b = self.lock_of(ex)
        return bool(key or need)

    def door(self, room, d, ex):
        k = self.door_key(room, d)
        st = self.doors.get(k)
        now = time.time()
        if st is None or (st["open"] and now > st["open"]):
            st = self.doors[k] = {"open": 0, "unlocked": not self.lockable(ex)}
        return st

    def door_open(self, room, d, ex):
        if (tuple(room), d) in self.timed and (time.time() % 60) < 25:
            return True                              # opens on its own timer (the pyramid's creaking doors)
        return self.door(room, d, ex)["open"] > time.time()

    def door_cmd(self, p, parts, out) -> bool:
        """open / bash / pick / use <key> <dir>. True = handled."""
        if len(parts) < 2 or parts[0] not in ("open", "bash", "pick", "use", "unlock"):
            return False
        d = norm_dir(parts[-1])
        if not d:
            return False
        r = self.w.room(p.room)
        ex = r.exits.get(d) if r else None
        if parts[0] == "use":
            num = self.item_named(p, parts[1:-1])
            if num is None:
                out.append(f"You don't have {' '.join(parts[1:-1])}!")
                return True
            if ex is None or not ex.door:
                out.append(NO_EFFECT)
                return True
        if ex is None or not ex.door:
            out.append("There is no door there.")
            return True
        st = self.door(p.room, d, ex)
        key, need, bashable = self.lock_of(ex)
        now = time.time()
        if st["open"] > now or self.door_open(p.room, d, ex):
            out.append("The door is already open.")
            return True
        if parts[0] == "open":
            if not st["unlocked"]:
                out.append("The door is locked.")
                self.note("door locked", p.room, d)
            else:
                st["open"] = now + DOOR_SECS
                out.append("The door is now open.")
            return True
        if parts[0] in ("use", "unlock"):
            if st["unlocked"]:
                out.append("The door is not locked.")
                return True
            if parts[0] == "unlock" or key is None or num != key:
                out.append("That key doesn't fit!" if parts[0] == "use" else NO_EFFECT)
                self.note("wrong key", p.room, f"{d} {self.w.item_name(num) if parts[0] == 'use' else ''}")
                return True
            st["unlocked"] = True
            out.append("You successfully unlocked the door.")
            self.note("key used", p.room, f"{d} {self.w.item_name(num)}")
            uses = int((self.w.gear.get(num) or {}).get("UseCount") or -1)
            if uses > 0:
                left = p.uses.get(num, uses) - 1
                p.uses[num] = left
                if left <= 0 and not int((self.w.gear.get(num) or {}).get("Retain After Uses") or 0):
                    p.items[num] -= 1
                    p.uses.pop(num, None)
                    out.append(f"Your {self.w.item_name(num)} crumbles to dust!")
                    self.note("key used up", p.room, self.w.item_name(num))
            return True
        lvl = 10 ** 6 if need is None else (0 if need == "any" else int(need))
        if parts[0] == "pick":
            if st["unlocked"]:
                out.append("The door is not locked.")
            elif need is not None and lvl < 1000 and self.picklocks >= lvl and self.rng.random() < self.rates["pick"]:
                st["unlocked"] = True
                out.append("You successfully unlocked the door.")
                self.note("door picked", p.room, d)
            else:
                out.append("Your attempts to pick the lock fail!")
                self.note("pick failed", p.room, d)
            return True
        # bash
        if not self.lockable(ex):
            bashable, lvl = True, 0                  # a plain door: shut, not locked — a shove opens it
        if bashable and lvl < 1000 and self.strength >= lvl and self.rng.random() < self.rates["bash"]:
            st["unlocked"], st["open"] = True, now + DOOR_SECS
            out.append("You bashed the door open!")
            self.note("door bashed", p.room, d)
        else:
            p.hp = max(1, p.hp - self.rng.randint(1, 5))
            out.append("Your attempts to bash through fail!")
            self.note("bash failed", p.room, d)
        return True

    # ------------------------------------------------------------ hidden exits
    def is_open(self, room, d):
        return self.opened.get((tuple(room), d), 0) > time.time()

    def open_exit(self, room, d, why=""):
        room = tuple(room)
        self.opened[(room, d)] = time.time() + HIDDEN_SECS
        r = self.w.room(room)
        ex = r.exits.get(d) if r else None
        if ex is not None and ex.door:
            st = self.door(room, d, ex)
            st["unlocked"], st["open"] = True, time.time() + DOOR_SECS
        self.note("opened", room, f"{d} {why}")

    def search(self, p, parts, out):
        r = self.w.room(p.room)
        want = norm_dir(parts[1]) if len(parts) > 1 else None
        found = []
        for dd, e in r.exits.items():
            if e.kind == "hidden" and "search" in (e.etype or "").lower() and (not want or dd == want):
                if self.rng.random() < self.rates["search"]:
                    self.open_exit(p.room, dd, "search")
                    found.append(dd)
        if found:
            out.append("You found an exit " + " and ".join(DIR_WORDS.get(x, x) for x in found) + "!")
        else:
            out.append("You notice nothing different.")
            self.note("search missed", p.room, want or "")

    def action(self, p, cmd, out) -> bool:
        """A lever / button / 'turn stand' that opens a hidden exit (here or elsewhere), each step once, in order
        when MME says so, with the item it needs."""
        hits = []
        for rk, dd, e in self.sim.action_exits(p.room):
            for a in e.steps_needed():
                at = tuple(a["at"]) if a.get("at") else rk
                if at == tuple(p.room) and cmd in [c.lower() for c in a.get("cmds") or []]:
                    hits.append((rk, dd, e, a))
        if not hits:
            return False
        moved = False
        for rk, dd, e, a in hits:
            if a.get("item") and not self.has(p, a["item"]):
                out.append(NO_EFFECT)
                self.note("action needs item", p.room, f"{cmd} {self.w.item_name(a['item'])}")
                continue
            steps = e.steps_needed()
            need = e.needs_actions or len(steps)
            if need > 20 or need > len(steps):
                need = len(steps)
            prog = self.progress.setdefault((rk, dd), [])
            n = a.get("n") or 1
            if "specific" in (e.etype or "").lower():
                want = [s.get("n") or 1 for s in steps]
                if len(prog) < len(want) and want[len(prog)] == n:
                    prog.append(n)
                else:
                    prog[:] = [n] if want and want[0] == n else []
            elif n not in prog:
                prog.append(n)
            if len(prog) >= need:
                prog.clear()
                self.open_exit(rk, dd, cmd)
                moved = True
        out.append("You hear a grinding noise as a passage opens!" if moved else "You hear a click.")
        return True

    # ------------------------------------------------------------ gates on an exit
    def gate_why(self, p, ex):
        et = ex.etype or ""
        m = LEVEL_EX_RE.search(et)
        if m and not (int(m.group(1)) <= p.level <= (int(m.group(2)) or 9999)):
            return f"level {m.group(1)}-{m.group(2)}"
        for m in CLASS_EX_RE.finditer(et):
            mine = self.cls_num if m.group(1).lower() == "class" else self.race_num
            ok_n, no_n = int(m.group(2)), int(m.group(3))
            if (ok_n and mine != ok_n) or (no_n and mine == no_n):
                return m.group(0)
        m = ALIGN_EX_RE.search(et)
        if m:
            lo, hi, al = m.group(1).lower(), m.group(2).lower(), self.align.lower()
            if al in ALIGNS and lo in ALIGNS and hi in ALIGNS:
                a, b = sorted((ALIGNS.index(lo), ALIGNS.index(hi)))
                if not a <= ALIGNS.index(al) <= b:
                    return m.group(0)
        for m in ABIL_EX_RE.finditer(et):
            v = p.abil.get(int(m.group(1)), 0)
            if not int(m.group(2)) <= v <= int(m.group(3)):
                return m.group(0)
        if "(Block" in et:
            return "blocked"
        return None

    def req_why(self, p, req):
        if not req:
            return None
        if req.get("level") and p.level < req["level"]:
            return f"level {req['level']}"
        if req.get("maxlevel") and p.level > req["maxlevel"]:
            return f"max level {req['maxlevel']}"
        if req.get("classes") and self.cls_num not in req["classes"]:
            return "class"
        if req.get("races") and self.race_num not in req["races"]:
            return "race"
        for a, v in req.get("abil") or []:
            if p.abil.get(a, 0) < v:
                return f"ability {a} {v}"
        for a, v in req.get("abil_eq") or []:
            if p.abil.get(a, 0) != v:
                return f"ability {a} = {v}"
        for a, v in req.get("no_abil") or []:
            if p.abil.get(a, 0) >= v:
                return f"not ability {a}"
        for i in req.get("items") or []:
            if not self.has(p, i):
                return f"needs {self.w.item_name(i)}"
        for i in req.get("no_items") or []:
            if self.has(p, i):
                return f"carrying {self.w.item_name(i)}"
        if req.get("monster"):
            return "needs a monster there"
        if req.get("price") and p.cash < req["price"]:
            return f"price {req['price']}"
        return None

    def cross(self, p, ex, out) -> bool:
        """Go through exit ex from p.room. Messages go to out; True = you moved (p.room is where you landed)."""
        here = tuple(p.room)
        why = self.gate_why(p, ex)
        if why:
            out.append(BLOCKED)
            self.note("blocked", here, f"{ex.dir} {why}")
            return False
        et = ex.etype or ""
        if ex.kind == "item":
            m = GATE_ITEM_RE.match(et)
            num = int(m.group(2)) if m else 0
            it = self.w.items.get(num) or {}
            if num and it and it.get("gettable", 1):
                if not self.has(p, num):
                    out.append(BLOCKED)
                    self.note("blocked", here, f"{ex.dir} needs {self.w.item_name(num)}")
                    return False
                if m.group(1).lower().startswith("ticket"):
                    p.items[num] -= 1
        if ex.kind == "toll":
            m = TOLL_EX_RE.search(et)
            n = int(m.group(1)) if m else 0
            if p.cash < n:
                out.append(BLOCKED)
                self.note("blocked", here, f"{ex.dir} toll {n}, have {p.cash}")
                return False
            p.cash -= n
            out.append(f"You pay the toll of {n} copper farthings.")
            self.note("toll paid", here, n)
        if ex.kind == "text" or getattr(ex, "req", None):
            why = self.req_why(p, getattr(ex, "req", None))
            if why:
                out.append(NO_EFFECT)
                self.note("command refused", here, f"{ex.text_command} {why}")
                return False
            m = PRICE_EX_RE.search(et)
            if m and not (getattr(ex, "req", None) or {}).get("price"):
                if p.cash < int(m.group(1)):
                    out.append(NO_EFFECT)
                    return False
                p.cash -= int(m.group(1))
            elif (getattr(ex, "req", None) or {}).get("price"):
                p.cash -= int(ex.req["price"])
            if (getattr(ex, "chance", False) or "(Chance)" in et) and self.rng.random() > self.rates["chance"]:
                out.append("You fail.")
                self.note("chance failed", here, ex.text_command)
                return False
        if ex.kind == "trap" and self.rng.random() < self.rates["trap"]:
            m = TRAP_EX_RE.search(et)
            self.hurt(p, self.rng.randint(1, int(m.group(1)) if m else 20), "trap", out, "You triggered a trap!")
            # (MME's figure read as the most it does: 'Trap, 400 damage' — up to 400)
        pre, post = CAST_EX_RE.search(et).groups() if CAST_EX_RE.search(et) else (0, 0)
        land = self.cast(p, int(pre), out) if int(pre) else None
        if land is None:
            p.room = ex.to
            if int(post):
                land = self.cast(p, int(post), out)
        m = SPELLTRAP_RE.search(et)
        if land is None and m:
            land = self.cast(p, int(m.group(1)), out)
        if land is not None and land != tuple(p.room):
            self.note("teleported", here, f"{ex.dir} → {land[0]}/{land[1]} (map says {ex.to[0]}/{ex.to[1]})")
            p.room = land
        self.arrive(p, out)
        p.resting = False
        return True

    def arrive(self, p, out, depth=0):
        """A room spell hits whoever walks in (a river without a raft, a sea current, the desert)."""
        sp = (getattr(self.w, "room_spells", {}) or {}).get(tuple(p.room))
        if not sp or depth > 2:
            return
        if any(self.has(p, i) for i in (getattr(self.w, "negates", {}) or {}).get(sp, [])):
            return
        was = tuple(p.room)
        land = self.cast(p, sp, out)
        if land is not None and land != was and land in self.w.rooms:
            self.note("room spell moved you", was, f"{(self.w.spells.get(sp) or {}).get('Name')} → {land[0]}/{land[1]}")
            p.room = land
            self.arrive(p, out, depth + 1)

    def hurt(self, p, dmg, what, out, line=None):
        if line:
            out.append(line)
        out.append(f"You are hit by the {what} for {dmg} damage!")
        p.hp -= dmg
        if p.hp <= 0:
            self.note("would have died", p.room, what)
            p.hp = 1

    # ------------------------------------------------------------ spells and textblocks
    def cast(self, p, n, out, depth=0):
        """A spell cast on you: where it sends you (or None)."""
        sp = self.w.spells.get(int(n)) or {}
        if not sp or depth > 6:
            return None
        ab = {int(a[0]): a[1] for a in sp.get("abils") or [] if len(a) >= 2 and a[0] is not None}
        here = tuple(p.room)
        if int(ab.get(140) or 0):
            return (int(ab.get(141) or here[0]), int(ab[140]))
        if int(ab.get(148) or 0):
            r = self.block(p, int(ab[148]), out, depth + 1)
            return r if isinstance(r, tuple) else None
        lo, hi = int(sp.get("MinBase") or 0), int(sp.get("MaxBase") or 0)
        if int(ab.get(141) or 0) > 0 and 0 < lo <= hi:
            if int(ab.get(151) or 0):
                from .mmetext import _voyage
                land, _rounds = _voyage(self.w.spells, int(ab[151]), here[0])
                return land
            rooms = [(int(ab[141]), x) for x in range(lo, hi + 1) if (int(ab[141]), x) in self.w.rooms]
            return self.rng.choice(rooms) if rooms else None
        if hi > 0 and 1 in ab:                       # (ability 1 = damage; a bare MinBase is a message number)
            self.hurt(p, self.rng.randint(lo, hi), sp.get("Name") or "spell", out)
        return None

    def block(self, p, num, out, depth=0):
        """Run a textblock: the first line that doesn't fail counts (a teleport ends it). A room, None or _FAIL."""
        from .mmetext import block_lines, is_trigger
        res = _FAIL
        for segs in block_lines(self.w.textblocks, num):
            if not segs or is_trigger(segs[0]):
                continue
            res = self.line(p, segs, out, depth)
            if res is not _FAIL:
                return res
        return res

    def line(self, p, segs, out, depth=0):
        """One textblock line, effects in order. A room you're sent to, None (done) or _FAIL (a check failed)."""
        from .mmetext import block_lines, _voyage
        here = tuple(p.room)
        aboard = None
        for seg in segs:
            if not seg:
                continue
            self._seg = seg                          # (the check that fails, for the sweep's notes)
            w_ = seg.split()
            verb = w_[0].lower()
            a = [int(x) for x in re.findall(r"-?\d+", seg)]
            if verb == "cast" and a and aboard is not None:
                # the voyage: a timed spell whose end casts the next, until one lands you (VOYAGE_SECS a round here)
                land, rounds = _voyage(self.w.spells, a[0], here[0])
                if land:
                    p.voyage = (time.time() + max(3.0, rounds * VOYAGE_SECS), land)
                    self.note("boat", here, f"aboard {aboard[0]}/{aboard[1]}, lands {land[0]}/{land[1]} in {rounds} rounds")
                return aboard
            if verb == "cast" and a and self._boards(a[0]):
                sp = self.w.spells.get(a[0]) or {}
                ab = {int(x[0]): x[1] for x in sp.get("abils") or [] if len(x) >= 2 and x[0] is not None}
                lo, hi, mp = int(sp.get("MinBase") or 0), int(sp.get("MaxBase") or 0), int(ab.get(141) or here[0])
                cabins = [(mp, x) for x in range(lo, hi + 1) if (mp, x) in self.w.rooms]
                if cabins:
                    aboard = self.rng.choice(cabins)
                    continue
            if verb in ("checkitem",) and a and not self.has(p, a[0]):
                return _FAIL
            if verb == "failitem" and a and self.has(p, a[0]):
                return _FAIL
            if verb == "takeitem" and a:
                if not self.has(p, a[0]):
                    return _FAIL
                p.items[a[0]] -= 1
            elif verb == "giveitem" and a:
                p.items[a[0]] += 1
            elif verb == "clearitem" and a and self.has(p, a[0]):
                p.items[a[0]] = 0
            elif verb == "roomitem" and a and not self.room_has(here, a[0]):
                return _FAIL                         # (the nexus portal MME places on Rock Island is there)
            elif verb == "failroomitem" and a and self.room_has(here, a[0]):
                return _FAIL
            elif verb in ("needmonster", "monsters") and a and not any(
                    m is self.w.monsters.get(a[0]) for m in self.residents(here)):
                return _FAIL
            elif verb == "nomonsters" and any(float(m.get("exp") or 0) > 0 for m in self.sim.mobs.get(here, [])):
                return _FAIL                         # (kill what's here first)
            elif verb == "class" and a and self.cls_num != a[0]:
                return _FAIL
            elif verb == "race" and a and self.race_num != a[0]:
                return _FAIL
            elif verb == "minlevel" and a and p.level < a[0]:
                return _FAIL
            elif verb == "maxlevel" and a and p.level > a[0]:
                return _FAIL
            elif verb == "levelcheck" and len(a) >= 2 and not a[0] <= p.level <= a[1]:
                return _FAIL
            elif verb == "goodaligned" and self._align_at() > 2:
                return _FAIL
            elif verb == "evilaligned" and self._align_at() < 5:
                return _FAIL
            elif verb == "checkability" and len(a) >= 2 and p.abil.get(a[0], 0) < a[1]:
                return _FAIL
            elif verb == "testability" and len(a) >= 2 and p.abil.get(a[0], 0) != a[1]:
                return _FAIL
            elif verb == "failability" and a and p.abil.get(a[0], 0) >= (a[1] if len(a) > 1 else 1):
                return _FAIL
            elif verb == "failspell" and a and p.spells_on.get(a[0], 0) > time.time():
                return _FAIL
            elif verb in ("giveability", "setability") and len(a) >= 2:
                p.abil[a[0]] = a[1]
            elif verb == "addability" and len(a) >= 2:
                p.abil[a[0]] = p.abil.get(a[0], 0) + a[1]
            elif verb == "removeability" and a:
                p.abil.pop(a[0], None)
            elif verb == "price" and a:
                if p.cash < a[0]:
                    out.append(f"You cannot afford that.")
                    return _FAIL
                p.cash -= a[0]
            elif verb == "givecoins" and a:
                p.cash += a[0]
            elif verb == "testskill":
                if self.rng.random() > self.rates["chance"]:
                    return _FAIL
            elif verb == "remoteaction" and a:
                di = a[3] if len(a) >= 4 else None
                d = DIRS[di] if isinstance(di, int) and 0 <= di < len(DIRS) else None
                room = (here[0], a[0])
                r = self.w.room(room)
                for dd in ([d] if d else list(r.exits) if r else []):
                    if r and dd in r.exits:
                        self.open_exit(room, dd, "remoteaction")
            elif verb == "teleport" and a:
                return ((a[1] if len(a) > 1 and a[1] else here[0]), a[0])
            elif verb == "cast" and a:
                r = self.cast(p, a[0], out, depth + 1)
                if r is not None:
                    return r
            elif verb == "text" and a and depth < 8:
                r = self.block(p, a[0], out, depth + 1)
                if isinstance(r, tuple):
                    return r
            elif verb == "random" and a and depth < 8:
                lines = block_lines(self.w.textblocks, a[0])
                roll = self.rng.randint(1, 100)
                pick = None
                for sub in lines:
                    if sub and sub[0].strip().isdigit():
                        if roll <= int(sub[0]):
                            pick = sub[1:]
                            break
                    elif sub:
                        pick = None
                if pick is None and lines and not any(s and s[0].strip().isdigit() for s in lines):
                    pick = self.rng.choice(lines)
                if pick:
                    r = self.line(p, pick, out, depth + 1)
                    if isinstance(r, tuple):
                        return r
        if aboard is not None:
            return aboard                            # no voyage after it: a drop somewhere in the range (the
                                                     # Darkwood Tree's uninvited portal → the Caves of Chaos)
        return None

    def _boards(self, n) -> bool:
        """A spell that puts you aboard a boat (a random cabin, MinBase–MaxBase on map 141); the next cast sails."""
        sp = self.w.spells.get(int(n)) or {}
        ab = {int(x[0]): x[1] for x in sp.get("abils") or [] if len(x) >= 2 and x[0] is not None}
        return int(ab.get(141) or 0) > 0 and not int(ab.get(140) or 0) and int(sp.get("MinBase") or 0) > 0 \
            and not int(ab.get(151) or 0)

    def tick(self, p):
        """Each second: a boat that's arrived puts you ashore. Lines to show (the new room)."""
        v = getattr(p, "voyage", None)
        if v and time.time() >= v[0]:
            p.voyage = None
            p.room = v[1]
            out = []
            self.arrive(p, out)
            return out + [self.sim.render(p)]
        return []

    def room_has(self, room, num) -> bool:
        """An item lying in the room: one MME places there, or one dropped."""
        r = self.w.room(room)
        placed = {int(x) for x in re.findall(r"\d+", (r.placed if r else "") or "")}
        return int(num) in placed or any(self.w.item_name(num).lower() == n.lower()
                                          for _q, n in self.sim.items.get(tuple(room), []))

    def room_command(self, p, low, out) -> bool:
        """A command the room's MME textblock knows ('dive sinkhole', 'ask barmaid adventure'). True = handled."""
        from .mmetext import block_lines, is_trigger
        tb = self.room_tb.get(tuple(p.room))
        if not tb:
            return None
        lines = [s for s in block_lines(self.w.textblocks, tb) if s and is_trigger(s[0]) and s[0].strip().lower() == low]
        if not lines:
            return None
        here = tuple(p.room)
        why = []
        for segs in lines:
            res = self.line(p, segs[1:], out)
            if res is _FAIL:
                why.append(getattr(self, "_seg", ""))
                continue
            if isinstance(res, tuple) and res in self.w.rooms and res != here:
                p.room = res
                self.note("room command moved you", here, f"'{low}' → {res[0]}/{res[1]}")
                self.arrive(p, out)
                p.resting = False
                return "moved"
            out.append("Ok.")
            return "stay"
        out.append(NO_EFFECT)
        self.note("command refused", here, f"{low} ({'; '.join(why)})")
        return "stay"

    def buy(self, p, name, out):
        r = tuple(p.room)
        for sh in self.w.shops.values():
            if r not in [tuple(x) for x in sh.get("rooms") or []]:
                continue
            for row in sh.get("stock") or []:
                num = int(row[0])
                if self.w.item_name(num).lower() == name.lower():
                    it = self.w.items.get(num) or {}
                    cost = int(it.get("price") or 0) * COPPER[min(4, max(0, int(it.get("currency") or 0)))]
                    if p.cash < cost:
                        out.append(f"You cannot afford {self.w.item_name(num)}.")
                        return
                    p.cash -= cost
                    p.items[num] += 1
                    out.append(f"You just bought {self.w.item_name(num)} for {cost} copper farthings.")
                    self.note("bought", r, self.w.item_name(num))
                    return
        out.append("You cannot buy that here.")

    def too_dark(self, p, r) -> bool:
        return self.dark_at is not None and r is not None and int(r.light or 0) <= self.dark_at \
            and getattr(p, "lit_until", 0) < time.time()

    def _align_at(self):
        al = (self.align or "neutral").lower()
        return ALIGNS.index(al) if al in ALIGNS else 3

    def command(self, p, cmd, low, parts, d, user):
        """A command played by the gates rules: the lines to send back, or None (the plain server handles it)."""
        out = []
        r = self.w.room(p.room)
        if d:
            p.combat = None
            e = r.exits.get(d) if r else None
            hidden_ok = e is not None and ((e.kind == "hidden" and "pass" in (e.etype or "").lower())
                                           or self.is_open(p.room, d))
            if e is None or e.to not in self.w.rooms or (not e.visible and not hidden_ok):
                return ["There is no exit in that direction!"]
            if e.door and not self.door_open(p.room, d, e):
                self.note("walked into a closed door", p.room, d)
                return ["The door is closed in that direction!"]
            if self.cross(p, e, out):
                out.append(self.sim.render(p))
            return out
        if self.door_cmd(p, parts, out):
            return out
        if parts[0] == "light" or low in ("cast light", "illu", "glow"):
            p.lit_until = time.time() + 900          # a torch / light spell: 15 minutes
            return ["The room brightens."] + [self.sim.render(p)]
        if parts[0] == "search":
            self.search(p, parts, out)
            return out
        if parts[0] == "buy" and len(parts) > 1:
            self.buy(p, " ".join(parts[1:]), out)
            return out
        if parts[0] == "ask" and len(parts) >= 3 and self.ask(p, parts, out):
            if out and out[-1] == "__moved__":
                out[-1] = self.sim.render(p)
            return out
        if low in ("i", "inv", "inventory"):
            return self.inventory(p)
        if parts[0] in ("st", "stat"):
            return self.stat(p, user)
        if parts[0] == "abil" and len(parts) == 2 and parts[1].isdigit() and int(parts[1]) != 145:
            v = p.abil.get(int(parts[1]))
            return [f"granted: Ability({parts[1]})             {v:04d}"] if v is not None else [""]
        rc = self.room_command(p, low, out)
        if rc == "moved":
            return out + [self.sim.render(p)]
        if self.action(p, low, out if not rc else []) or rc:
            # (a room command can print its message AND be the action MME lists for a hidden exit: 6/859's
            # 'push sarcophagus' only says something in its textblock, yet opens the west wall)
            return out
        ex = next((e for e in r.exits.values() if e.accepts(low)), None) if r else None
        if ex is not None:
            if ex.to not in self.w.rooms:
                return [NO_EFFECT]
            if self.cross(p, ex, out):
                out.append(self.sim.render(p))
            return out
        return None

    # ------------------------------------------------------------ monsters that live in a room, their drops
    RESPAWN_SECS = 90

    def _residents_idx(self):
        idx = getattr(self, "_res_idx", None)
        if idx is None:
            idx = self._res_idx = {}
            for num, m in self.w.monsters.items():
                if not m.get("in_game"):
                    continue
                rooms = [tuple(rm) for rm in m.get("spawn_rooms") or []]
                if (m.get("boss") or int(m.get("limit") or 0) == 1) and len(rooms) > 1:
                    rooms = [self.rng.choice(rooms)]  # one of it in the realm: in one of its rooms, not all
                for rm in rooms:
                    idx.setdefault(rm, []).append(num)
            for k, r in self.w.rooms.items():
                if r.npc and int(r.npc) in self.w.monsters and int(r.npc) not in idx.get(k, []):
                    idx.setdefault(k, []).append(int(r.npc))
            self._dead = {}                          # (room, monster) -> killed at
        return idx

    def residents(self, room):
        room = tuple(room)
        nums = self._residents_idx().get(room, [])
        cur = self.sim.mobs.setdefault(room, [])
        now = time.time()
        for n in nums:
            if not any(m.get("number", m.get("num")) == n or m is self.w.monsters.get(n) for m in cur) \
                    and now - self._dead.get((room, n), 0) > self.RESPAWN_SECS:
                cur.append(self.w.monsters[n])
        return cur

    def killed(self, p, mob, msg):
        ref = mob.get("_ref")
        num = next((n for n, m in self.w.monsters.items() if m is ref), None)
        if num is None:
            return
        self._residents_idx()
        self._dead[(tuple(p.room), num)] = time.time()
        pat = re.compile(rf"\bMonster #{num}(?:\(([\d.]+)%\))?(?!\d)")
        for inum, g in (self.w.gear or {}).items():
            m = pat.search(g.get("obtained") or "")
            if m and self.rng.random() * 100 < float(m.group(1) or 100):
                self.sim.items.setdefault(tuple(p.room), []).append((1, self.w.item_name(inum)))
                self.note("monster dropped", p.room, f"{mob.get('name')}: {self.w.item_name(inum)}")

    def get(self, p, parts, out):
        its = self.sim.items.get(tuple(p.room), [])
        want = " ".join(parts[1:])
        pick = next((x for x in its if not want or want in ("all",) or x[1].lower().startswith(want)
                     or want in x[1].lower()), None)
        if pick is None:
            out.append("You don't see that here.")
            return
        its.remove(pick)
        q, n = pick
        if n == "copper farthings":
            p.cash += q
        else:
            num = (self.w.item_names.get(n.lower()) or {}).get("num")
            if num:
                p.items[int(num)] += q
        out.append(f"You picked up {q} {n}.")

    def _talk_idx(self):
        idx = getattr(self, "_talk", None)
        if idx is None:
            idx = self._talk = {}
            for num, (act, link, cf) in (self.w.textblocks or {}).items():
                for mn in re.findall(r"Monster #?(\d+)", cf or ""):
                    idx.setdefault(int(mn), []).append(num)
        return idx

    def ask(self, p, parts, out) -> bool:
        """'ask commander orb': a monster standing here talks about a topic (its MME talk block)."""
        from .mmetext import block_lines
        word, topic = parts[1], " ".join(parts[2:])
        here = tuple(p.room)
        for m in self.residents(here):
            if word not in (m.get("name") or "").lower().split():
                continue
            num = next((n for n, x in self.w.monsters.items() if x is m), None)
            for tb in self._talk_idx().get(num, []):
                for segs in block_lines(self.w.textblocks, tb):
                    if len(segs) >= 2 and segs[0].strip().lower() == topic and segs[1].strip().isdigit():
                        res = self.block(p, int(segs[1]), out)
                        self.note("asked", here, f"{m.get('name')} {topic}")
                        if isinstance(res, tuple) and res in self.w.rooms and res != here:
                            p.room = res
                            self.arrive(p, out)
                            out.append("__moved__")
                        elif res is _FAIL:
                            out.append(f"The {m.get('name')} ignores you.")
                        else:
                            out.append(f"The {m.get('name')} nods.")
                        return True
            out.append(f"The {m.get('name')} has nothing to say about that.")
            return True
        return False

    def give(self, p, num, qty=1):
        p.items[int(num)] += qty


SOUND_RATE = float(os.environ.get("SIM_SOUNDS", "0") or 0)
_snd = random.Random(7)       # separate so sounds don't change the mobs


async def handle(sim: Sim, reader, writer):
    def w(s):
        writer.write(s.replace("\n", "\r\n").replace("\r\r", "\r").encode("cp437", "replace"))

    async def line():
        data = await reader.readline()
        if not data:
            raise ConnectionError
        return data.decode("cp437", "replace").strip("\r\n")

    p = Player(sim.world, getattr(sim, "start", (1, 1)))
    if getattr(sim, "gates", None) is not None:
        sim.gates.setup(p)
    sim.players.append(p)
    try:
        w("Welcome to the MudPilot practice board.\nIf you already have a User-ID on this system, type it in and press ENTER: ")
        user = await line()
        w("Enter your password: ")
        await line()
        w(f"\x1b[2J{YE}Entering the Realm as {user}...{RS}\n")
        w(sim.render(p) + "\n" + sim.prompt(p))

        async def ticker():
            while True:
                await asyncio.sleep(1.0)
                msg = []
                if p.combat:
                    mob = p.combat
                    sp = mob.get("_spell")
                    if sp and p.ma < sp["ManaCost"]:
                        msg.append("You don't have enough mana!")
                    elif sp:
                        p.ma -= sp["ManaCost"]
                        c = spell_calc(sp, 0, mob)
                        dmg = max(0, int(c.per_cast * sim.rng.uniform(0.8, 1.2)))
                        mob["_hp"] -= dmg
                        if dmg:
                            msg.append(f"You cast {sp['Name']} on the {mob['name']} for {dmg} damage!")
                        else:
                            msg.append(f"The {mob['name']} resists your {sp['Name']}!")
                    elif sim.rng.random() < 0.7:
                        dmg = sim.rng.randint(4, 12) if getattr(sim, "gates", None) is None else sim.rng.randint(p.level, 3 * p.level)
                        mob["_hp"] -= dmg
                        msg.append(f"You hit the {mob['name']} for {dmg} damage!")
                    if mob["_hp"] <= 0:
                        msg.append(f"The {mob['name']} falls to the ground dead.")
                        msg.append(f"You gain {int(mob['exp'])} experience.")
                        if mob["_ref"] in sim.mobs.get(p.room, []):
                            sim.mobs[p.room].remove(mob["_ref"])
                        if getattr(sim, "gates", None) is not None:
                            sim.gates.killed(p, mob, msg)
                        if sim.rng.random() < 0.6:
                            sim.items.setdefault(p.room, []).append((sim.rng.randint(2, 30), "copper farthings"))
                        p.combat = None
                        msg.append("*Combat Off*")
                    else:
                        if sim.rng.random() < 0.5:
                            d = sim.rng.randint(1, 4)
                            p.hp = max(1, p.hp - d)
                            msg.append(f"The {mob['name']} hits you for {d} damage!")
                elif p.resting:
                    p.hp = min(p.max_hp, p.hp + (max(4, p.max_hp // 30) if getattr(sim, "gates", None) is not None else 4))
                    p.ma = min(p.max_ma, p.ma + (10 if getattr(p, "medit", False) else 2))
                    w("\n" + sim.prompt(p))
                    await writer.drain()
                if getattr(sim, "gates", None) is not None:
                    msg += sim.gates.tick(p)
                if not p.combat and SOUND_RATE and _snd.random() < SOUND_RATE:
                    exits = [k for k, e in sim.world.room(p.room).exits.items() if e.visible]
                    if exits:
                        dw = _snd.choice(exits)
                        word = {"U": "above you", "D": "below you"}.get(dw, "to the " + DIR_WORDS[dw])
                        # a chasing pile: the same direction several times in a row
                        msg += [f"You hear movement {word}."] * _snd.randint(1, 4)
                if msg:
                    w("\n" + "\n".join(msg) + "\n" + sim.prompt(p))
                    await writer.drain()

        tk = asyncio.create_task(ticker())
        while True:
            cmd = await line()
            low = cmd.strip().lower()
            out = []
            parts = low.split()
            d = norm_dir(parts[0]) if len(parts) == 1 else (norm_dir(parts[1]) if parts and parts[0] == "go" and len(parts) > 1 else None)
            text_ex = next((e for e in sim.world.room(p.room).exits.values() if e.accepts(low)), None) if low else None
            gl = sim.gates.command(p, cmd, low, parts, d, user) if (getattr(sim, "gates", None) is not None
                                                                     and low) else None
            drop = sim.drop_for(p.room, low, d) if (low and gl is None) else None
            if gl is not None:
                out += gl
            elif drop:
                # a random drop (the Warped Asylum's 'asylum', the uninvited portal): anywhere in its range
                p.room = drop
                out.append(sim.render(p))
            elif text_ex:
                p.room = text_ex.to
                out.append(sim.render(p))
            elif low in ("par", "party") and os.environ.get("SIM_PARTY"):
                hp1, hp2 = sim.rng.randint(40, 100), sim.rng.randint(60, 100)
                out.append("The following people are in your travel party:\n"
                           f"  {(user.split() or ['Tester'])[0].capitalize() + ' Abil':<30}(Druid)      [M:{int(100 * p.ma / p.max_ma):3d}%] [H:{int(100 * p.hp / p.max_hp):3d}%] - Backrank\n"
                           f"  Miserable Par                 (Mage)       [M:{sim.rng.randint(20, 100):3d}%] [H:{hp1:3d}%]M - Frontrank\n"
                           f"  Lyra Moonbrook                (Priest)     [M:{sim.rng.randint(20, 100):3d}%] [H:{hp2:3d}%]R - Backrank")
            elif low in ("par", "party"):
                out.append("You are not in a party at the present time.")
            elif low == "" or low in ("l", "look"):
                out.append(sim.render(p))
            elif len(parts) == 2 and parts[0] in ("l", "look") and norm_dir(parts[1]):
                e = sim.world.room(p.room).exits.get(norm_dir(parts[1]))
                if not e or not e.visible or e.to not in sim.world.rooms:
                    out.append("There is no exit in that direction!")
                else:
                    here = p.room
                    p.room = e.to
                    out.append(sim.render(p))
                    p.room = here
            elif d:
                if p.combat:
                    p.combat = None
                    out.append("*Combat Off*")
                r = sim.world.room(p.room)
                e = r.exits.get(d)
                hidden_open = e is not None and not e.visible and ((p.room, d) in p.open_doors
                                                                   or "passable" in (e.etype or "").lower())
                if not e or (not e.visible and not hidden_open) or e.to not in sim.world.rooms:
                    out.append("There is no exit in that direction!")
                elif e.door and (p.room, d) not in p.open_doors:
                    out.append("The door is closed in that direction!")
                elif e.kind in ("key", "item", "toll", "cast", "restricted", "action"):
                    out.append("Your path is blocked.")
                else:
                    p.resting = False
                    p.room = e.to
                    out.append(sim.render(p))
            elif parts and parts[0] == "search":
                r = sim.world.room(p.room)
                found = [dd for dd, e in r.exits.items() if e.kind == "hidden" and "search" in e.etype.lower()]
                for dd in found:
                    p.open_doors.add((p.room, dd))
                out.append("You found an exit!" if found else "You notice nothing different.")
            elif any(cmd.strip().lower() in [c.lower() for c in a.get("cmds") or []]
                     for _rk, _dd, e in sim.action_exits(p.room) for a in e.actions):
                # a lever / button here opens a hidden exit — in this room, or in another one (the scorpion
                # temple's gems on the dais open the wall downstairs)
                for rk, dd, e in sim.action_exits(p.room):
                    if any(cmd.strip().lower() in [c.lower() for c in a.get("cmds") or []] for a in e.actions):
                        p.open_doors.add((rk, dd))
                out.append("You hear a grinding noise as a passage opens!")
            elif parts and parts[0] in ("open",) and len(parts) > 1 and norm_dir(parts[-1]):
                d = norm_dir(parts[-1])
                e = sim.world.room(p.room).exits.get(d)
                if e and e.door:
                    p.open_doors.add((p.room, d))
                    back = sim.world.room(e.to)
                    for bd, be in (back.exits.items() if back else []):
                        if be.to == p.room:
                            p.open_doors.add((e.to, bd))
                    out.append("The door is now open.")
                else:
                    out.append("There is no door there.")
            elif parts and parts[0] in ("a", "attack", "aa") and len(parts) > 1:
                mobs = sim.spawn(p.room)
                tgt = next((m for m in mobs if parts[1] in m["name"].lower()), None)
                if not tgt:
                    out.append("You don't see that here.")
                else:
                    p.resting = False
                    p.combat = dict(tgt, _hp=tgt["hp"], _ref=tgt)
                    out.append("*Combat Engaged*")
            elif low == "pro":
                import os as _os
                fmt = _os.environ.get("PROFMT", "You are in map {m}, room {r}.")
                out.append(fmt.format(m=p.room[0], r=p.room[1]))
            elif low in ("spells", "spell"):
                out.append("You have the following spells:")
                out.append("Level Mana Short Spell Name")
                for x in sim.known:
                    out.append(f"{x['ReqLevel']:>5} {x['ManaCost']:>4} {x['Short']:<5} {x['Name']}")
            elif parts and any((x.get("Short") or "").lower() == parts[0] and is_attack_spell(x)
                               for x in sim.known):
                sp = next(x for x in sim.known if (x.get("Short") or "").lower() == parts[0] and is_attack_spell(x))
                mobs = sim.spawn(p.room)
                tgt = next((m for m in mobs if len(parts) > 1 and parts[1] in m["name"].lower()), None)
                if tgt is None and len(parts) == 1 and int(sp.get("Targets") or 0) in (9, 12) and mobs:
                    tgt = mobs[0]   # area spell: hits the room
                if not tgt:
                    out.append("You don't see that here.")
                else:
                    p.resting = False
                    if not p.combat or p.combat.get("_ref") is not tgt:
                        p.combat = dict(tgt, _hp=tgt["hp"], _ref=tgt)
                        out.append("*Combat Engaged*")
                    p.combat["_spell"] = sp
            elif parts and parts[0] in ("rest", "sit", "medi", "meditate"):
                if p.combat:
                    out.append("You can't rest during combat!")
                else:
                    p.resting = True
                    p.medit = parts[0].startswith("medi")
                    out.append("You are now meditating." if p.medit else "You are now resting.")
            elif parts and parts[0] in ("eq", "equip", "wear", "remove", "rem"):
                out.append(f"You {'remove' if parts[0].startswith('rem') else 'are now wearing'} {' '.join(parts[1:])}.")
            elif parts and parts[0] in ("get", "g") and getattr(sim, "gates", None) is not None:
                sim.gates.get(p, parts, out)
            elif parts and parts[0] in ("get", "g"):
                its = sim.items.get(p.room, [])
                if its:
                    q, n = its.pop(0)
                    out.append(f"You picked up {q} {n}.")
                else:
                    out.append("You don't see that here.")
            elif low in ("abil", "abil 145"):
                import time as _t
                live = [(n, v) for n, (exp, v) in p.regen.items() if exp > _t.time()]
                fx = bool(live)
                roll = live[-1][1] if live else 0
                sc = 100 if p.buffs.get("ntap", 0) > _t.time() else 0
                if low == "abil 145":
                    out.append("granted: ManaRegen(145)             0005")
                    out.append("worn:    ManaRegen(145)             0100")
                    if fx:
                        out.append(f"spells:  ManaRegen(145)             {roll:04d}" if roll >= 0 else
                                   f"spells:  ManaRegen(145)             {roll:04d}")
                else:
                    out += ["Race", "Rfir(5)                    10", "", "Worn Items",
                            "SpellCasting(70)           45", "ManaRegen(145)             100", "", "Spell effects"]
                    if fx:
                        out.append(f"ManaRegen(145)             {roll}")
                    if sc:
                        out.append(f"SpellCasting(70)           {sc}")
                    out += ["", "GrantedAbilities", "ManaRegen(145)             5", ""]
            elif low in ("ntap", "flux", "nity"):
                import time as _t
                rng = {"flux": (-100, 150), "ntap": (-100, 188), "nity": (-25, 75)}[low]
                p.regen = {low: (_t.time() + 40, sim.rng.randint(*rng))}   # recast replaces the old roll
                p.ma = max(0, p.ma - 20)
                out.append(f"You cast {low}!")
            elif low in ("i", "inv", "inventory"):
                out += ["You are carrying 247 copper farthings, a mithril longsword (Wielded),",
                        "woodland robes (Worn), a large sack, 3 healing potions, a torch,",
                        "an elven cloak (Worn), silver gloves (Worn), diamond earrings (Worn)",
                        "You have the following keys:  a silver key, a rusty key",
                        "Wealth: 247 copper farthings",
                        "Encumbrance: 812/2400 - Light [33%]"]
            elif parts and parts[0] in ("st", "stat"):
                out.append(f"Name: {(user.split() or ['Tester'])[0].capitalize() + ' Abil':<20}Lives/CP:      9/0\n"
                           f"Race: Dark-Elf      Exp: 123456     Perception:  60\n"
                           f"Class: Druid        Level: 38       Stealth:     40\n"
                           f"Hits:  {p.hp}/{p.max_hp}   Armour Class: 10/0   Strength: 60\n"
                           f"Mana:  {p.ma}/{p.max_ma}")
            elif low == "quit":
                w("Goodbye!\n")
                break
            else:
                if len(parts) == 2 and parts[1] in ("miserable", "lyra"):
                    out.append(f"You cast {parts[0]} on {parts[1].capitalize()}!")
                else:
                    out.append("Huh?")
            if locals().get("text_ex") and getattr(sim, "text_delay", 0):
                await asyncio.sleep(sim.text_delay)          # a laggy realm: the new room shows up late
            md = getattr(getattr(sim, "gates", None), "move_delay", 0)
            if md and (d or (gl and len(gl) and "Obvious exits" in gl[-1])):
                await asyncio.sleep(md)                      # (gates' move_delay: the real realm's pace per room)
            w("\n".join(out) + "\n" + sim.prompt(p))
            await writer.drain()
        tk.cancel()
    except (ConnectionError, asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def main_async(port, seed, mob_rate, world_path=None, gates=False):
    world = WorldDB(world_path or config.WORLD_DB)
    if not world.loaded:
        raise SystemExit("Import an MME database in MudPilot first (data/world.db missing).")
    sim = Sim(world, seed, mob_rate, gates=gates)
    server = await asyncio.start_server(lambda r, w: handle(sim, r, w), "127.0.0.1", port)
    print(f"Practice server on 127.0.0.1:{port}  ({len(world.rooms):,} rooms)")
    async with server:
        await server.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2323)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mob-rate", type=float, default=0.15)
    ap.add_argument("--gates", action="store_true", help="play keys / items / tolls / casts / level gates honestly")
    a = ap.parse_args()
    asyncio.run(main_async(a.port, a.seed, a.mob_rate, gates=a.gates))


if __name__ == "__main__":
    main()
