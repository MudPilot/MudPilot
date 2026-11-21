"""World database: imports an MME (MajorMUD Explorer) .mdb into a local SQLite
cache and answers room / exit / monster / item questions, MegaMUD room hashes,
and shortest-path routing across the whole realm."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time as _time
from collections import deque
from dataclasses import dataclass, field

# Planning on a worker thread (bgplan) still holds Python's lock while it crunches: the window stuttered ~2 s on
# every Go to (Dan, 2026-10-30). Every this many rooms looked at, the search sleeps 2 ms so the window gets a turn.
YIELD_EVERY = 1500

DATA_VERSION = 9          # bump when import_mdb stores something new (2: monster Type, 3: exit actions, 4: room commands,
                          # 5: every textblock + which room/monster runs it, 6: monster GameLimit,
                          # 7: lair refill delay, 8: room spells + items that negate them,
                          # 9: shop type / level / class limits / stock, item NotDroppable / DestroyOnDeath / uses)
DIRS = ["N", "S", "E", "W", "NE", "NW", "SE", "SW", "U", "D"]
DIR_WORDS = {
    "N": "north", "S": "south", "E": "east", "W": "west",
    "NE": "northeast", "NW": "northwest", "SE": "southeast", "SW": "southwest",
    "U": "up", "D": "down",
}
WORD_DIRS = {v: k for k, v in DIR_WORDS.items()}
WORD_DIRS.update({k.lower(): k for k in DIRS})
REVERSE = {"N": "S", "S": "N", "E": "W", "W": "E", "NE": "SW", "SW": "NE",
           "NW": "SE", "SE": "NW", "U": "D", "D": "U"}

# MegaMUD exit-code tables (from MME's Get_MegaMUD_ExitsCode)
_EXIT_VAL = {"N": 1, "S": 4, "E": 1, "W": 4, "NE": 1, "NW": 4, "SE": 1, "SW": 4, "U": 1, "D": 4}
_EXIT_POS = {"N": 5, "S": 5, "E": 4, "W": 4, "NE": 3, "NW": 3, "SE": 2, "SW": 2, "U": 1, "D": 1}

Room = tuple  # (map, room)


def norm_dir(word: str) -> str | None:
    """'north' / 'n' / 'N' -> 'N'; returns None if not a direction."""
    return WORD_DIRS.get(word.strip().lower())


@dataclass
class Exit:
    dir: str
    to: Room
    etype: str          # raw MME suffix, e.g. "(Door)", "(Hidden/Searchable)", "(Text: go path)"
    visible: bool       # shows in "Obvious exits"
    door: bool          # a door/gate (affects MegaMUD hash)
    kind: str           # normal|door|key|item|toll|hidden|text|action|trap|cast|restricted|other
    actions: list = field(default_factory=list)   # what to type to open a hidden exit: [{"n", "cmds", "item"}]

    @property
    def needs_actions(self) -> int:
        m = re.search(r"Needs (\d+) Actions?", self.etype, re.I)
        return int(m.group(1)) if m else 0

    def action_cmds(self) -> list:
        """One command per action, in order ('pull lever'), or [] if we don't know them all."""
        need = self.needs_actions
        acts = self.steps_needed()
        if not acts or (need and len(acts) < need and need <= 20):
            return []                     # (MME sometimes has a nonsense count like 1278 — trust the listed actions)
        return [a["cmds"][0] for a in acts if a.get("cmds")]

    def steps_needed(self) -> list:
        """One action per step, in order. MME lists some steps twice (the scorpion temple's 'push onyx'; the
        Graveyard's 'push button' from this side and from the far side) — doing one twice resets the sequence, so
        each step once, the one done from this exit's own room when there's a choice (sweep, 2026-10-29)."""
        by_n = {}
        for a in self.actions:
            n = a.get("n") or 0
            cur = by_n.get(n)
            if cur is None or (cur.get("at") and not a.get("at")):
                by_n[n] = a
        return [by_n[n] for n in sorted(by_n)]

    def action_items(self) -> list:
        return [a["item"] for a in self.actions if a.get("item")]

    @property
    def text_commands(self) -> list:
        m = re.search(r"\(Text:\s*([^)]+)\)", self.etype)
        return [c.strip() for c in m.group(1).split(",") if c.strip()] if m else []

    @property
    def text_command(self) -> str | None:
        c = self.text_commands
        return c[0] if c else None

    def accepts(self, cmd: str) -> bool:
        return cmd.strip().lower() in [c.lower() for c in self.text_commands]


@dataclass
class RoomInfo:
    key: Room
    name: str
    light: int = 0
    shop: int = 0
    npc: int = 0
    lair: str = ""
    placed: str = ""
    mega_hash: str = ""
    exits: dict = field(default_factory=dict)  # dir -> Exit
    delay: int = 0                             # MME lair refill delay (minutes)


ACTION_NOTE_RE = re.compile(r"Action(?:#(\d+))?\s*\[on the (\w+) exit of (?:this room|room (\d+)/(\d+))\]:\s*(.*)", re.I)


def parse_action_note(raw):
    """MME keeps what opens a hidden exit in a spare direction column:
    'Action#1 [on the S exit of this room]: pull lever, move lever'  → (S, room or None, {n, cmds, item})."""
    m = ACTION_NOTE_RE.match(str(raw or "").strip())
    if not m:
        return None
    d = norm_dir(m.group(2)) or m.group(2).upper()
    room = (int(m.group(3)), int(m.group(4))) if m.group(3) else None
    text = m.group(5)
    mi = re.search(r"\(Item:\s*(\d+)\)", text)
    text = re.sub(r"\(Item:\s*\d+\)", "", text)
    cmds = [c.strip() for c in text.split(",") if c.strip()]
    return d, room, {"n": int(m.group(1) or 1), "cmds": cmds, "item": int(mi.group(1)) if mi else None}


def parse_exit(dir_: str, raw) -> Exit | None:
    raw = str(raw or "").strip()
    if not raw or raw == "0":
        return None
    if ACTION_NOTE_RE.match(raw):
        return None                      # an action note, not an exit (attached to its exit on load)
    if raw.lower().startswith("action"):
        # e.g. "Action (needs 2 actions) 1/234" — target follows
        m = re.search(r"(\d+)/(\d+)", raw)
        if not m:
            return None
        return Exit(dir_, (int(m.group(1)), int(m.group(2))), raw, False, False, "action")
    m = re.search(r"(\d+)/(\d+)", raw)
    if not m:
        return None
    to = (int(m.group(1)), int(m.group(2)))
    if to[0] <= 0 or to[1] <= 0:
        return None
    etype = raw[m.end():].strip()
    head = etype[:5]
    visible, door, kind = True, False, "normal"
    if head == "(Key:":
        door, kind = True, "key"
    elif head == "(Door":
        door, kind = True, "door"
    elif head == "(Gate":
        door, kind = True, "door"
    elif head in ("(Item", "(Tick"):
        kind = "item"
    elif head == "(Toll":
        kind = "toll"
    elif head == "(Hidd":
        visible, kind = False, "hidden"
    elif head == "(Text":
        visible, kind = False, "text"
    elif head == "(Trap":
        kind = "trap"
    elif head == "(Cast":
        kind = "cast"
    elif head in ("(Clas", "(Race", "(Leve", "(Alig", "(Abil", "(Spel", "(Max ", "(Bloc", "(Time", "(Dela"):
        kind = "restricted"
    elif etype:
        kind = "other"
    return Exit(dir_, to, etype, visible, door, kind)


def megamud_name_hash(name: str, vortex: bool = False, obelisk: bool = False) -> str:
    total = sum((i + 1) * ord(c) for i, c in enumerate(name))
    if vortex:
        total += 1
    if obelisk:
        total += 2
    return "%03X" % (total & 0xFFF)


def megamud_exits_code(exits: dict) -> str:
    calc = {p: 0 for p in range(1, 6)}
    for d, ex in exits.items():
        if not ex.visible or ex.kind == "action":
            continue
        calc[_EXIT_POS[d]] += _EXIT_VAL[d] * (2 if ex.door else 1)
    return "".join("%X" % calc[p] for p in range(1, 6))


NOT_MOVES = {"pro", "look", "l", "par", "party", "i", "inv", "inventory", "st", "stat", "stats", "exp", "abil",
             "spells", "who", "rest", "medi", "meditate", "sn", "sneak", "hide", "search", "get", "drop", "eq",
             "equip", "rem", "remove", "wear", "cast", "invite", "join", "help", "time", "top", "score", "health",
             "bless", "blur", "mshi", "armr", "chao", "flux", "magm", "esto", "simp", "mist", "slep"}


def clean_move(move: str) -> str:
    """The room command inside a typed / path move: '.@party go vortex' and '@party go vortex' are both
    'go vortex' (the @party part is for the followers). Other @, / and ' commands aren't moves at all."""
    mv = (move or "").strip()
    mv = mv.lstrip(".").strip() if mv.startswith(".@") else mv
    low = mv.lower()
    for pre in ("@party ", "@do "):
        if low.startswith(pre):
            return mv[len(pre):].strip()
    if mv[:1] in ("@", "/", "'", '"', "."):
        return ""
    if low.split()[:1] and low.split()[0] in NOT_MOVES:
        return ""                                # 'pro', 'look', 'par'… — the tracker relocating isn't a way
    return mv


class WorldDB:
    """SQLite-backed realm data. Loads everything into memory for fast lookups."""

    def __init__(self, path: str):
        self.path = path
        self._plan_lock = threading.RLock()      # one route search at a time (a Go to plans on a worker thread)
        self._memo = {}                          # route results, remembered a while (Dan: 'remember that path')
        self.rooms: dict[Room, RoomInfo] = {}
        self.by_name: dict[str, list[Room]] = {}
        self.by_hash: dict[str, list[Room]] = {}
        self.monsters: dict[int, dict] = {}
        self.monster_names: dict[str, dict] = {}
        self.dup_names: dict = {}
        self.items: dict[int, dict] = {}
        self.item_names: dict[str, dict] = {}
        self.spells: dict[int, dict] = {}
        if os.path.exists(path):
            self.load()

    @property
    def loaded(self) -> bool:
        return bool(self.rooms)

    # ------------------------------------------------------------ import
    @staticmethod
    def import_mdb(mdb_path: str, out_path: str, progress=None) -> "WorldDB":
        from access_parser import AccessParser  # pure-python Access reader

        def note(msg):
            if progress:
                progress(msg)

        note("Reading MME database…")
        db = AccessParser(mdb_path)
        tables = set(db.catalog.keys())
        for need in ("Rooms", "Monsters", "Items"):
            if need not in tables:
                raise ValueError(f"{os.path.basename(mdb_path)} has no '{need}' table — is this an MME data file?")
        items = db.parse_table("Items")
        mons = db.parse_table("Monsters")
        note("Reading rooms…")
        rooms = db.parse_table("Rooms")

        tmp = f"{out_path}.{os.getpid()}.{threading.get_ident()}.tmp"   # two MudPilots importing at once can't collide
        if os.path.exists(tmp):
            os.remove(tmp)
        con = sqlite3.connect(tmp)
        con.executescript("""
            CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE rooms(map INT, room INT, name TEXT, light INT, shop INT, npc INT,
                               lair TEXT, placed TEXT, mega_hash TEXT, PRIMARY KEY(map, room));
            CREATE TABLE exits(map INT, room INT, dir TEXT, raw TEXT);
            CREATE TABLE monsters(num INT PRIMARY KEY, name TEXT, exp REAL, hp INT, align INT, in_game INT,
                                  mr INT, undead INT, abils TEXT, regen REAL, summoned TEXT, ac INT, dr INT,
                                  atk TEXT, glimit INT);
            CREATE TABLE spells(num INT PRIMARY KEY, data TEXT);
            CREATE TABLE gear(num INT PRIMARY KEY, data TEXT);
            CREATE TABLE classes(num INT PRIMARY KEY, data TEXT);
            CREATE TABLE races(num INT PRIMARY KEY, data TEXT);
            CREATE TABLE shops(num INT PRIMARY KEY, name TEXT, rooms TEXT);
            CREATE TABLE items(num INT PRIMARY KEY, name TEXT, price INT, currency INT, encum INT, gettable INT);
            CREATE TABLE room_cmds(map INT, room INT, cmds TEXT, PRIMARY KEY(map, room));
            CREATE TABLE textblocks(num INT PRIMARY KEY, action TEXT, link INT, called_from TEXT);
            CREATE TABLE room_tb(map INT, room INT, tb INT, PRIMARY KEY(map, room));
            CREATE TABLE room_delay(map INT, room INT, delay INT, PRIMARY KEY(map, room));
            CREATE TABLE room_spell(map INT, room INT, spell INT, PRIMARY KEY(map, room));
            CREATE TABLE item_negate(item INT PRIMARY KEY, spells TEXT);
            CREATE TABLE shop_info(num INT PRIMARY KEY, data TEXT);
        """)
        item_name = {}
        for i in range(len(items["Number"])):
            num = int(items["Number"][i])
            nm = str(items["Name"][i] or "")
            item_name[num] = nm
            neg = [int(items[f"NegateSpell-{x}"][i] or 0) for x in range(10) if items.get(f"NegateSpell-{x}")]
            neg = [x for x in neg if x]
            if neg:
                con.execute("INSERT OR REPLACE INTO item_negate VALUES(?,?)", (num, json.dumps(neg)))
            con.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?)", (
                num, nm, int(items.get("Price", [0] * (i + 1))[i] or 0),
                int(items.get("Currency", [0] * (i + 1))[i] or 0),
                int(items.get("Encum", [0] * (i + 1))[i] or 0),
                int(items.get("Gettable", [1] * (i + 1))[i] or 0)))
        def col(t, k, i, d=0):
            v = t.get(k)
            return d if v is None else (v[i] if v[i] is not None else d)

        # ---- data for the monster-attack simulator (port of MME PopulateMonsterDataToAttackSim)
        sp_t = db.parse_table("Spells") if "Spells" in tables else None
        nmr_ver = 0.0
        if "Info" in tables:
            try:
                info = db.parse_table("Info")
                m_ver = re.search(r"\d+(?:\.\d+)?", str((info.get("NMR Version") or [""])[0] or ""))
                nmr_ver = float(m_ver.group(0)) if m_ver else 0.0
            except Exception:
                nmr_ver = 0.0
        sim_spells = {}
        if sp_t is not None:
            sp_keys = ("Name", "AttType", "TypeOfResists", "Targets", "Dur", "DurInc", "DurIncLVLs", "Cap",
                       "ReqLevel", "MinBase", "MaxBase", "MinInc", "MinIncLVLs", "MaxInc", "MaxIncLVLs", "EnergyCost")
            for i in range(len(sp_t["Number"])):
                d = {k: (str(col(sp_t, k, i, "") or "") if k == "Name" else int(col(sp_t, k, i) or 0)) for k in sp_keys}
                d["abils"] = [[int(col(sp_t, f"Abil-{x}", i) or 0), int(col(sp_t, f"AbilVal-{x}", i) or 0)]
                              for x in range(10) if int(col(sp_t, f"Abil-{x}", i) or 0)]
                sim_spells[int(sp_t["Number"][i])] = d
        item_raw = {}
        for i in range(len(items["Number"])):
            item_raw[int(items["Number"][i])] = {
                "limit": int(col(items, "Limit", i) or 0), "ac": int(col(items, "ArmourClass", i) or 0),
                "dr": int(col(items, "DamageResist", i) or 0), "accy": int(col(items, "Accy", i) or 0),
                "abils": [(int(col(items, f"Abil-{x}", i) or 0), int(col(items, f"AbilVal-{x}", i) or 0))
                          for x in range(20)]}

        def item_has_ability(num, abil, gmud):          # MME ItemHasAbility (-31337 = none)
            it = item_raw.get(num)
            r = -31337
            if it is None or abil < -1 or num < 1:
                return r
            if gmud and abil > 0:
                fld = {2: "ac", 7: "dr", 22: "accy"}.get(abil)
                if fld and it[fld] != 0:
                    r = it[fld]
            for a, v in it["abils"]:
                if a == abil:
                    return (0 if r == -31337 else r) + v
            return r

        def item_bonus(i, abil_list, gmud):             # MME CalculateMonsterItemBonuses
            tot = 0
            wpn = int(col(mons, "Weapon", i) or 0)
            if wpn > 0 and item_raw.get(wpn, {"limit": -1})["limit"] == 0:
                for a in abil_list:
                    t = item_has_ability(wpn, a, gmud)
                    if t != -31337:
                        tot = round(tot + t)
            for x in range(10):
                it = int(col(mons, f"DropItem-{x}", i) or 0)
                if it > 0 and item_raw.get(it, {"limit": -1})["limit"] == 0:
                    pct = min(100, int(col(mons, f"DropItem%-{x}", i) or 0))
                    for a in abil_list:
                        t = item_has_ability(it, a, gmud)
                        if t != -31337:
                            tot = round(tot + t * (pct / 100))   # VB Integer assignment (banker's rounding)
            return int(tot)

        def attack_blob(i):
            att, mid, used = [], [], set()
            for x in range(5):
                a = {"type": int(col(mons, f"AttType-{x}", i) or 0), "name": str(col(mons, f"AttName-{x}", i, "") or ""),
                     "acc": int(col(mons, f"AttAcc-{x}", i) or 0), "pct": int(col(mons, f"Att%-{x}", i) or 0),
                     "true_pct": float(col(mons, f"AttTrue%-{x}", i) or 0),
                     "min": int(col(mons, f"AttMin-{x}", i) or 0), "max": int(col(mons, f"AttMax-{x}", i) or 0),
                     "energy": int(col(mons, f"AttEnergy-{x}", i) or 0),
                     "hit_spell": int(col(mons, f"AttHitSpell-{x}", i) or 0)}
                att.append(a)
                if 0 < a["type"] < 4:
                    used.add(a["acc"] if a["type"] == 2 else a["hit_spell"])
                mspell = int(col(mons, f"MidSpell-{x}", i) or 0)
                mid.append({"spell": mspell, "pct": int(col(mons, f"MidSpell%-{x}", i) or 0),
                            "lvl": int(col(mons, f"MidSpellLVL-{x}", i) or 0)})
                used.add(mspell)
            spells, todo = {}, [s for s in used if s > 0]
            while todo:                                   # include end-cast (ability 151) chains
                s = todo.pop()
                if s in spells or s not in sim_spells:
                    continue
                spells[str(s)] = sim_spells[s]
                todo += [v for ab, v in sim_spells[s]["abils"] if ab == 151 and v > 0 and str(v) not in spells]
            return {"v": 1, "nmr_ver": nmr_ver, "energy": int(col(mons, "Energy", i) or 0),
                    "mtype": int(col(mons, "Type", i) or 0),     # 0 solo, 1 leader, 2 follower, 3 stationary
                    "align": int(col(mons, "Align", i) or 0), "att": att, "mid": mid, "spells": spells,
                    "item_bonus": {"dmg": item_bonus(i, [4], False), "acc": item_bonus(i, [22, 105, 106], False),
                                   "dmg_gmud": item_bonus(i, [4], True), "acc_gmud": item_bonus(i, [22, 105, 106], True)},
                    "mme_avg": float(col(mons, "AvgDmg", i) or 0), "mme_avg_phys": float(col(mons, "AvgDmgPhys", i) or 0),
                    "mme_avg_spell": float(col(mons, "AvgDmgSpell", i) or 0)}

        for i in range(len(mons["Number"])):
            abils = {}
            for x in range(10):
                a = int(col(mons, f"Abil-{x}", i))
                if a:
                    abils[a] = int(col(mons, f"AbilVal-{x}", i))
            try:
                atk = json.dumps(attack_blob(i), separators=(",", ":"))
            except Exception:
                atk = None                                # sim just reports "no data" for this monster
            con.execute("INSERT OR REPLACE INTO monsters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                int(mons["Number"][i]), str(mons["Name"][i] or ""),
                float(col(mons, "EXP", i)) * float(col(mons, "ExpMulti", i, 1) or 1),
                int(col(mons, "HP", i)), int(col(mons, "Align", i)), int(col(mons, "In Game", i, 1)),
                int(col(mons, "MagicRes", i)), int(col(mons, "Undead", i)), json.dumps(abils),
                float(col(mons, "RegenTime", i) or 0), str(col(mons, "Summoned By", i, "") or "")[:4000],
                int(col(mons, "ArmourClass", i) or 0), int(col(mons, "DamageResist", i) or 0), atk,
                int(col(mons, "GameLimit", i) or 0)))
        if sp_t is not None:
            sp = sp_t
            keep = ["Number", "Name", "Short", "ReqLevel", "ManaCost", "EnergyCost", "MinBase", "MaxBase", "Diff",
                    "TypeOfResists", "AttType", "Magery", "Cap", "MaxIncLVLs", "MaxInc", "MinIncLVLs", "MinInc",
                    "Classes", "Learnable", "Targets", "MageryLVL", "Learned From", "Dur", "DurInc", "DurIncLVLs"]
            for i in range(len(sp["Number"])):
                d = {k: col(sp, k, i, 0 if k not in ("Name", "Short", "Classes", "Learned From") else "") for k in keep}
                d["abils"] = [[int(col(sp, f"Abil-{x}", i)), int(col(sp, f"AbilVal-{x}", i))] for x in range(10)
                              if int(col(sp, f"Abil-{x}", i))]
                con.execute("INSERT OR REPLACE INTO spells VALUES(?,?)", (int(sp["Number"][i]), json.dumps(d, default=str)))

        note("Reading items, classes and races…")
        for i in range(len(items["Number"])):
            ab = {}
            for x in range(20):
                a = int(col(items, f"Abil-{x}", i))
                if a:
                    ab[a] = ab.get(a, 0) + int(col(items, f"AbilVal-{x}", i))
            d = {k: col(items, k, i) for k in ("ItemType", "Worn", "ArmourType", "WeaponType", "ArmourClass",
                                               "DamageResist", "StrReq", "Encum", "Limit", "Price", "Currency",
                                               "Gettable", "In Game", "Min", "Max", "Accy", "Speed", "UseCount",
                                               "Not Droppable", "Destroy On Death", "Retain After Uses")}
            d["classes"] = [int(col(items, f"ClassRest-{x}", i)) for x in range(10) if int(col(items, f"ClassRest-{x}", i))]
            d["races"] = [int(col(items, f"RaceRest-{x}", i)) for x in range(10) if int(col(items, f"RaceRest-{x}", i))]
            d["abils"] = ab
            d["obtained"] = str(col(items, "Obtained From", i, "") or "")[:600]
            con.execute("INSERT OR REPLACE INTO gear VALUES(?,?)", (int(items["Number"][i]), json.dumps(d, default=str)))
        for tname, table in (("Classes", "classes"), ("Races", "races")):
            if tname not in tables:
                continue
            t = db.parse_table(tname)
            for i in range(len(t["Number"])):
                d = {k: (v[i] if not isinstance(v[i], bytes) else None) for k, v in t.items()}
                con.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?)", (int(t["Number"][i]), json.dumps(d, default=str)))
        shop_rooms = {}
        for i in range(len(rooms["Name"])):
            sh = int(rooms.get("Shop", [0] * len(rooms["Name"]))[i] or 0)
            if sh:
                shop_rooms.setdefault(sh, []).append([int(rooms["Map Number"][i]), int(rooms["Room Number"][i])])
        if "Shops" in tables:
            sp_t = db.parse_table("Shops")
            for i in range(len(sp_t["Number"])):
                num = int(sp_t["Number"][i])
                con.execute("INSERT OR REPLACE INTO shops VALUES(?,?,?)",
                            (num, str(sp_t["Name"][i] or ""), json.dumps(shop_rooms.get(num, [])[:40])))
                stock = []
                for x in range(20):
                    it = int(col(sp_t, f"Item-{x}", i) or 0)
                    if it:
                        stock.append([it, int(col(sp_t, f"Max-{x}", i) or 0), int(col(sp_t, f"Time-{x}", i) or 0),
                                      int(col(sp_t, f"Amount-{x}", i) or 0), int(col(sp_t, f"%-{x}", i) or 0)])
                con.execute("INSERT OR REPLACE INTO shop_info VALUES(?,?)", (num, json.dumps({
                    "type": int(col(sp_t, "ShopType", i) or 0), "min_lvl": int(col(sp_t, "MinLVL", i) or 0),
                    "max_lvl": int(col(sp_t, "MaxLVL", i) or 0), "markup": int(col(sp_t, "Markup%", i) or 0),
                    "class": int(col(sp_t, "ClassRest", i) or 0), "in_game": int(col(sp_t, "In Game", i, 1) or 0),
                    "stock": stock})))

        n = len(rooms["Name"])
        note(f"Indexing {n:,} rooms…")
        for i in range(n):
            mp, rm = int(rooms["Map Number"][i]), int(rooms["Room Number"][i])
            name = str(rooms["Name"][i] or "")
            placed = str(rooms.get("Placed", [""] * n)[i] or "")
            exits = {}
            for d in DIRS:
                raw = rooms[d][i]
                ex = parse_exit(d, raw)
                if ex:
                    exits[d] = ex
                    con.execute("INSERT INTO exits VALUES(?,?,?,?)", (mp, rm, d, str(raw)))
                elif parse_action_note(raw):
                    con.execute("INSERT INTO exits VALUES(?,?,?,?)", (mp, rm, d, str(raw)))   # opens a hidden exit
            vortex = obelisk = False
            for tok in re.findall(r"\d+", placed):
                nm = item_name.get(int(tok), "").lower()
                vortex |= "whirling vortex" in nm
                obelisk |= "obsidian obelisk" in nm
            mh = megamud_name_hash(name, vortex, obelisk) + megamud_exits_code(exits)
            con.execute("INSERT OR REPLACE INTO rooms VALUES(?,?,?,?,?,?,?,?,?)", (
                mp, rm, name, int(rooms.get("Light", [0] * n)[i] or 0),
                int(rooms.get("Shop", [0] * n)[i] or 0), int(rooms.get("NPC", [0] * n)[i] or 0),
                str(rooms.get("Lair", [""] * n)[i] or ""), placed, mh))
            rsp = int((rooms.get("Spell") or [0] * n)[i] or 0)
            if rsp:
                con.execute("INSERT OR REPLACE INTO room_spell VALUES(?,?,?)", (mp, rm, rsp))
            dl = int((rooms.get("Delay") or [0] * n)[i] or 0)
            if dl and str(rooms.get("Lair", [""] * n)[i] or "").strip() not in ("", "0"):
                con.execute("INSERT OR REPLACE INTO room_delay VALUES(?,?,?)", (mp, rm, dl))
        # room commands (MME "Room commands: say gazmuldduhaz"): the room's textblock, "trigger:effects" per line
        if "TBInfo" in tables and "CMD" in rooms:
            tbt = db.parse_table("TBInfo")
            tbs = {int(tbt["Number"][i]): (str(tbt["Action"][i] or ""), int(tbt["LinkTo"][i] or 0))
                   for i in range(len(tbt["Number"]))}
            for i in range(len(tbt["Number"])):
                con.execute("INSERT OR REPLACE INTO textblocks VALUES(?,?,?,?)", (
                    int(tbt["Number"][i]), str(tbt["Action"][i] or ""), int(tbt["LinkTo"][i] or 0),
                    str((tbt.get("Called From") or [""] * (i + 1))[i] or "")))
            for i in range(n):
                cmd = int(rooms["CMD"][i] or 0)
                if not cmd:
                    continue
                con.execute("INSERT OR REPLACE INTO room_tb VALUES(?,?,?)",
                            (int(rooms["Map Number"][i]), int(rooms["Room Number"][i]), cmd))
                lines, seen, num = [], set(), cmd
                while num and num in tbs and num not in seen and len(seen) < 10:
                    seen.add(num)
                    text, link = tbs[num]
                    for ln in text.replace("\r", "").split("\n"):
                        if ":" in ln and ln.split(":", 1)[0].strip():
                            trig, eff = ln.split(":", 1)
                            lines.append([trig.strip(), eff.strip()])
                    num = link
                if lines:
                    con.execute("INSERT OR REPLACE INTO room_cmds VALUES(?,?,?)",
                                (int(rooms["Map Number"][i]), int(rooms["Room Number"][i]), json.dumps(lines[:40])))
        con.execute("CREATE INDEX ix_exits ON exits(map, room)")
        con.execute("INSERT INTO meta VALUES('source', ?)", (os.path.basename(mdb_path),))
        con.execute(f"PRAGMA user_version={DATA_VERSION}")
        con.commit()
        con.close()
        os.replace(tmp, out_path)
        note("Import complete.")
        return WorldDB(out_path)

    # ------------------------------------------------------------ load
    def load(self):
        con = sqlite3.connect(self.path)
        try:
            self._load(con)
        finally:
            con.close()     # a damaged file mustn't stay open: Windows can't move an open file aside to heal it

    def _load(self, con):
        self.rooms.clear(); self.by_name.clear(); self.by_hash.clear()
        for mp, rm, name, light, shop, npc, lair, placed, mh in con.execute("SELECT * FROM rooms"):
            key = (mp, rm)
            # (0.8.201, walk check: 14 map-17 Mausoleum rooms are padded with spaces in MME — the game's line is
            #  stripped, so they never matched and the tracker put us in a look-alike)
            name = (name or "").strip()
            self.rooms[key] = RoomInfo(key, name, light, shop, npc, lair, placed, mh)
            self.by_name.setdefault(name.lower(), []).append(key)
            self.by_hash.setdefault(mh, []).append(key)
        self.room_spells, self.negates = {}, {}
        try:
            for mp, rm, sp in con.execute("SELECT * FROM room_spell"):
                self.room_spells[(mp, rm)] = int(sp)
            for it, js in con.execute("SELECT * FROM item_negate"):
                for spn in json.loads(js or "[]"):
                    self.negates.setdefault(int(spn), []).append(int(it))
        except sqlite3.Error:
            pass                                     # older import
        try:
            for mp, rm, dl in con.execute("SELECT * FROM room_delay"):
                r = self.rooms.get((mp, rm))
                if r:
                    r.delay = int(dl or 0)
        except sqlite3.Error:
            pass                                     # older import
        notes = []
        for mp, rm, d, raw in con.execute("SELECT * FROM exits"):
            r = self.rooms.get((mp, rm))
            ex = parse_exit(d, raw)
            if r and ex:
                r.exits[d] = ex
            elif r:
                an = parse_action_note(raw)
                if an:
                    notes.append(((mp, rm), an))
        for here, (d, room, act) in notes:
            r = self.rooms.get(room or here)
            ex = r.exits.get(d) if r else None
            if ex is not None:
                if room and room != here:
                    # done somewhere else: 'push block' in 12/1808 opens the N exit of 12/1811
                    act = dict(act, at=here)
                ex.actions.append(act)
        self.action_exits = len(notes)
        self._reconcile_key_doors()
        # hidden exits that MME opens with a room command ("say gazmuldduhaz" → remoteaction 1188):
        # the command typed in the room becomes the exit's action
        self.room_cmds = {}
        try:
            rows = con.execute("SELECT * FROM room_cmds").fetchall()
        except sqlite3.Error:
            rows = []
        for mp, rm, js in rows:
            try:
                lines = json.loads(js)
            except ValueError:
                continue
            self.room_cmds[(mp, rm)] = lines
            r = self.rooms.get((mp, rm))
            if not r:
                continue
            triggers = []
            for trig, eff in lines:
                if "teleport" in eff or re.search(r"\bcast\s+\d+", eff):
                    continue
                targets = [int(x) for x in re.findall(r"remoteaction\s+(\d+)", eff)]
                if not targets or rm in targets:
                    triggers.append(trig)
            if not triggers:
                continue
            for ex in r.exits.values():
                if ex.kind == "hidden" and not ex.actions and ex.needs_actions:
                    ex.actions.append({"n": 1, "cmds": triggers, "item": None, "room_cmd": True})
                    self.action_exits += 1
        try:
            self.version = con.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.Error:
            self.version = 0
        self.monsters = {}
        self._summ = {}                   # MME's "where it spawns" text per monster (the map's room panel reads it)
        self._wander_idx = None
        for row in con.execute("SELECT * FROM monsters"):
            num, nm, exp, hp, al, ig = row[:6]
            mr, und, ab = (row[6], row[7], row[8]) if len(row) > 8 else (50, 0, "{}")
            regen, summ = (row[9], row[10]) if len(row) > 10 else (0, "")
            m_ac, m_dr = (row[11], row[12]) if len(row) > 12 else (0, 0)
            atk = row[13] if len(row) > 13 else None
            glimit = int(row[14] or 0) if len(row) > 14 else 0
            spawn = [(int(a), int(b)) for a, b in re.findall(r"(?<![\w(])Room (\d+)/(\d+)", summ or "")]
            if summ:
                self._summ[num] = summ
            self.monsters[num] = {"num": num, "name": nm, "exp": exp, "hp": hp, "align": al, "in_game": ig,
                                  "mr": mr or 0, "undead": und or 0,
                                  "abils": {int(k): v for k, v in json.loads(ab or "{}").items()},
                                  "regen_h": float(regen or 0), "spawn_rooms": spawn,
                                  "boss": bool(regen) and bool(spawn) and "Group" not in (summ or ""),
                                  "ac": m_ac or 0, "dr": m_dr or 0,
                                  "limit": glimit}        # MME GameLimit: at most this many in the realm at once
            if atk:
                try:
                    self.monsters[num]["attack_data"] = json.loads(atk)
                    if "mtype" in self.monsters[num]["attack_data"]:
                        self.monsters[num]["type"] = self.monsters[num]["attack_data"]["mtype"]
                except ValueError:
                    pass
        self.spells = {}
        try:
            for num, data in con.execute("SELECT * FROM spells"):
                self.spells[num] = json.loads(data)
        except sqlite3.Error:
            pass
        self._load_textblocks(con)
        self._build_scatter()
        self._build_item_casts()
        self.gear, self.classes, self.races, self.shops = {}, {}, {}, {}
        try:
            for num, data in con.execute("SELECT * FROM gear"):
                d = json.loads(data)
                d["abils"] = {int(k): v for k, v in d.get("abils", {}).items()}
                d["num"] = num
                self.gear[num] = d
            for num, data in con.execute("SELECT * FROM classes"):
                self.classes[num] = json.loads(data)
            for num, data in con.execute("SELECT * FROM races"):
                self.races[num] = json.loads(data)
            for num, name, rms in con.execute("SELECT * FROM shops"):
                self.shops[num] = {"name": name, "rooms": [tuple(r) for r in json.loads(rms or "[]")]}
            try:
                for num, js in con.execute("SELECT * FROM shop_info"):
                    if num in self.shops:
                        self.shops[num].update(json.loads(js))
            except sqlite3.Error:
                pass                                 # older import
        except sqlite3.Error:
            pass        # older import: inventory calculator asks for a re-import
        self._name_gear()
        self.monster_names = {}
        for m in self.monsters.values():
            if m["name"]:
                cur = self.monster_names.get(m["name"].lower())
                if cur is None or (m["in_game"] and not cur["in_game"]):
                    self.monster_names[m["name"].lower()] = m
        by = {}
        for m in self.monsters.values():
            if m["name"]:
                by.setdefault(m["name"].lower(), []).append(m)
        # names shared by monsters that really differ (exp / HP) — those need the room to tell apart
        self.dup_names = {k: v for k, v in by.items()
                          if len(v) > 1 and len({(a.get("exp"), a.get("hp")) for a in v}) > 1}
        self.__dict__.pop("_map_lairs", None)
        self.items = {num: {"num": num, "name": nm, "price": pr, "currency": cu, "encum": en, "gettable": g}
                      for num, nm, pr, cu, en, g in con.execute("SELECT * FROM items")}
        self.item_names = {i["name"].lower(): i for i in self.items.values() if i["name"]}
        if getattr(self, "gear", None):
            self._name_gear()
        try:
            row = con.execute("SELECT v FROM meta WHERE k='source'").fetchone()
            self.source = row[0] if row else "?"
        except sqlite3.Error:
            self.source = "?"
        con.close()

    def _name_gear(self):
        for num, g in self.gear.items():
            g["name"] = self.items.get(num, {}).get("name") or f"item #{num}"

    # ------------------------------------------------------------ queries
    def room(self, key: Room) -> RoomInfo | None:
        return self.rooms.get(key)

    def is_room_name(self, text: str) -> bool:
        return text.strip().lower() in self.by_name

    def match_room(self, key: Room, name: str, shown_exits: set | None) -> bool:
        """Does the displayed room (name + obvious exits) fit this DB room?"""
        r = self.rooms.get(key)
        if not r or r.name.lower() != name.lower():
            return False
        if shown_exits is None:
            return True
        visible = {d for d, e in r.exits.items() if e.visible}
        allx = set(r.exits)
        # searched-open hidden exits can appear, so allow visible ⊆ shown ⊆ all
        return visible <= shown_exits <= allx

    def look_alike(self, key) -> bool:
        """Another room has the same name and the same exits you can see: the tracker can't tell them apart."""
        r = self.rooms.get(tuple(key)) if key else None
        if not r:
            return True
        shown = {d for d, e in r.exits.items() if e.visible}
        return sum(1 for k in self.by_name.get(r.name.lower(), []) if self.match_room(k, r.name, shown)) > 1

    def remove_learned(self, src, move, dst=None) -> bool:
        """A learned way that turned out wrong (the action failed): take it off the map and the list."""
        self.forget_routes()
        src = tuple(src)
        r = self.rooms.get(src)
        mv = clean_move(move)
        gone = False
        if r:
            keep = {k: e for k, e in r.exits.items()
                    if not (self.LEARNED_TAG in (e.etype or "") and (e.accepts(mv) or e.dir.lower() == mv.lower())
                            and (dst is None or e.to == tuple(dst)))}
            if len(keep) != len(r.exits):
                r.exits, gone = keep, True
        rows = getattr(self, "learned", [])
        new = [x for x in rows if not (tuple(x[0]) == src and clean_move(x[1]).lower() == mv.lower()
                                      and (dst is None or tuple(x[2]) == tuple(dst)))]
        if len(new) != len(rows):
            self.learned, gone = new, True
        if dst is not None:
            self.forgotten = getattr(self, "forgotten", set()) | {(src, mv.lower(), tuple(dst))}
        return gone

    def candidates(self, name: str, shown_exits: set | None) -> list[Room]:
        return [k for k in self.by_name.get(name.lower(), []) if self.match_room(k, name, shown_exits)]

    def neighbor(self, key: Room, d: str) -> Room | None:
        r = self.rooms.get(key)
        ex = r.exits.get(d) if r else None
        return ex.to if ex else None

    def boss_named(self, name: str) -> dict | None:
        """The boss record for a name (MME often has a plain monster with the same name)."""
        n = (name or "").strip().lower()
        hits = [m for m in self.monsters.values() if m["name"].lower() == n]
        hits.sort(key=lambda m: (not m.get("boss"), not m.get("spawn_rooms"), not m.get("in_game"), -m["exp"]))
        return hits[0] if hits else None

    LAIR_IDS_RE = re.compile(r"\(Max \d+\):\s*([\d,]+)")

    def room_spawns(self, key) -> list:
        """What can turn up in a room, from MME: [(monster, how)] — how is "lair" (it regenerates here, the room's
        own list), "group (lair)" or "wanders" (the area's monster groups), or "boss" (a set spawn room)."""
        key = tuple(key)
        if self._wander_idx is None:
            idx = {}
            for num, summ in self._summ.items():
                for kind, a, b in re.findall(r"(Group\(lair\)|Group|(?<![\w(])Room):? (\d+)/(\d+)", summ):
                    how = {"Group(lair)": "group (lair)", "Group": "wanders", "Room": "boss"}[kind]
                    idx.setdefault((int(a), int(b)), {}).setdefault(num, how)
            self._wander_idx = idx
        out, seen = [], set()
        r = self.room(key)
        m = re.match(r"\(Max \d+\):\s*([\d,]+)", (r.lair if r else "") or "")
        for n in (m.group(1).split(",") if m else []):
            if n.strip().isdigit() and int(n) in self.monsters and int(n) not in seen:
                seen.add(int(n))
                out.append((self.monsters[int(n)], "lair"))
        for num, how in (self._wander_idx.get(key) or {}).items():
            if num in self.monsters and num not in seen:
                seen.add(num)
                out.append((self.monsters[num], how))
        return out

    def monster_rooms(self, num, limit=12) -> list:
        """Where to find monster #num: [(room, how)] — the shop / NPC room it stands in, its set (boss) spawn
        room, then the rooms its lair regenerates in. Goto's monster search (Dan, 2026-10-30: 'sleazy shopkeeper')."""
        num = int(num)
        out, seen = [], set()

        def add(k, how):
            if k in self.rooms and k not in seen:
                seen.add(k)
                out.append((k, how))
        npc = self.__dict__.get("_npc_rooms")
        if npc is None:
            npc = {}
            for k, r in self.rooms.items():
                if r.npc:
                    npc.setdefault(int(r.npc), []).append(k)
            self._npc_rooms = npc
        for k in npc.get(num, []):
            add(k, "stands here")
        for a, b in re.findall(r"(?<![\w(])Room:? (\d+)/(\d+)", self._summ.get(num, "") or ""):
            add((int(a), int(b)), "spawns here")
        for k in self.lair_rooms(num):
            add(k, "lair")
        return out[:limit]

    def search_monsters(self, text: str, limit: int = 20) -> list:
        """Monsters whose name has every word typed, in-game ones first."""
        words = text.lower().split()
        if not words:
            return []
        hits = [m for m in self.monsters.values() if all(w in m["name"].lower() for w in words)]
        hits.sort(key=lambda m: (not m.get("in_game"), not m["name"].lower().startswith(words[0]), m["name"]))
        return hits[:limit]

    def places(self) -> list:
        """Rooms worth going to, straight from MME (so Goto has a list without MegaMUD's Rooms.md — Dan,
        2026-10-30: 'the rooms I'd like built into MudPilot'): [(group, name, room)] — every shop by its name, and
        every room an NPC stands in."""
        c = self.__dict__.get("_places")
        if c is not None:
            return c
        out, seen = [], set()
        for sh in self.shops.values():
            for k in sh.get("rooms") or []:
                k = tuple(k)
                if k in self.rooms and k not in seen and sh.get("name"):
                    seen.add(k)
                    out.append(("Shops", sh["name"], k))
        for k, r in self.rooms.items():
            if r.npc and k not in seen and int(r.npc) in self.monsters:
                seen.add(k)
                out.append(("NPCs", f"{self.monsters[int(r.npc)]['name']} ({r.name})", k))
        self._places = out
        return out

    def recipe_for(self, num):
        """{"room", "cmds", "needs", "nomonsters"} when MME says item #num comes from a room's commands
        ("obtained: Textblock #475" — the dragon key: put white, black, green, blue, red fang in the slot at the Unholy
        Temple, 3/606, with nobody else in the room — Dan, 2026-11-01). The chain is followed back from the line
        that gives the item: each step's room state is the one the step before it leaves."""
        g = (getattr(self, "gear", None) or {}).get(num) or {}
        m = re.search(r"Textblock #(\d+)", g.get("obtained") or "")
        tb = (getattr(self, "textblocks", None) or {}).get(int(m.group(1))) if m else None
        if not tb:
            return None
        rm = re.search(r"Room (\d+)/(\d+)", str(tb[2] or ""))
        if not rm:
            return None
        rows = []
        for ln in (tb[0] or "").splitlines():
            parts = ln.split(":")
            if len(parts) < 2:
                continue
            acts = parts[1:]
            get = lambda k: next((a.split()[1] for a in acts if a.startswith(k + " ") and len(a.split()) > 1), None)
            gives = [int(a.split()[1]) for a in acts if a.startswith("giveitem ") and a.split()[1].isdigit()]
            # 'takeitem 490 467': the device eats it (the Room of Change's three keys for the dark temple key —
            # Dan, 2026-11-06: it went there without them)
            takes = [int(a.split()[1]) for a in acts if a.startswith("takeitem ") and len(a.split()) > 1
                     and a.split()[1].isdigit()]
            rows.append({"cmd": parts[0].strip(), "state": get("roomitem"), "check": get("checkitem"),
                         "takes": takes, "gives": gives, "nomon": any(a.startswith("nomonsters") for a in acts)})
        last = next((r for r in rows if num in r["gives"]), None)
        if not last:
            return None
        chain, cur = [last], last
        for _ in range(20):
            if not cur["state"] or not cur["state"].isdigit():
                break
            givers = [r for r in rows if int(cur["state"]) in r["gives"] and r is not cur]
            states = {r["state"] for r in givers}
            if len(states) != 1:
                break                                # the start state (wrong-order lines all reset to it)
            cur = givers[0]                          # (the first spelling: 'put … in slot', not 'insert …')
            chain.insert(0, cur)
        needs = []
        for r in chain:
            for n in ([int(r["check"])] if r["check"] and r["check"].isdigit() else []) + r["takes"]:
                if n not in needs:
                    needs.append(n)
        return {"room": (int(rm.group(1)), int(rm.group(2))), "cmds": [r["cmd"] for r in chain], "needs": needs,
                "nomonsters": any(r["nomon"] for r in chain)}

    def lair_rooms(self, num) -> list:
        """Rooms whose lair spawns monster #num (dark cultists: 59 regen rooms round the Black House)."""
        idx = getattr(self, "_lair_rooms", None)
        if idx is None:
            idx = {}
            for k, r in self.rooms.items():
                if r.lair:
                    for n in self.lair_ids(k):
                        idx.setdefault(n, []).append(k)
            self._lair_rooms = idx
        return idx.get(int(num), [])

    def lair_ids(self, room) -> set:
        r = self.rooms.get(room) if room else None
        m = self.LAIR_IDS_RE.match((r.lair if r else "") or "")
        return {int(x) for x in m.group(1).split(",") if x} if m else set()

    def map_lair_ids(self, mp) -> set:
        cache = self.__dict__.setdefault("_map_lairs", {})
        if mp not in cache:
            ids = set()
            for k, r in self.rooms.items():
                if k[0] == mp and r.lair:
                    ids |= self.lair_ids(k)
                    if r.npc:
                        ids.add(int(r.npc))
            cache[mp] = ids
        return cache[mp]

    def identify_monster(self, shown: str, room=None, map_=None) -> dict | None:
        """'big angry kobold thief' -> kobold thief record (MajorMUD prefixes adjectives).
        Several MME monsters can share a name (Paradigm has 130-odd): given the room, prefer the one that lairs
        there (or is its NPC), then one that lairs on that map, then the in-game one."""
        words = shown.lower().strip().strip(".").split()
        for i in range(len(words)):
            nm = " ".join(words[i:])
            m = self.monster_names.get(nm)
            if m:
                alts = self.dup_names.get(nm) if (room or map_) and getattr(self, "dup_names", None) else None
                if alts:
                    r = self.rooms.get(room) if room else None
                    here = self.lair_ids(room) | ({int(r.npc)} if r and r.npc else set())
                    for pool in (here, self.map_lair_ids(map_ or (room[0] if room else None))):
                        hit = [a for a in alts if a["num"] in pool]
                        if hit:
                            return max(hit, key=lambda a: a.get("in_game") or 0)
                return m
        return None

    def search_rooms(self, text: str, limit: int = 200) -> list[RoomInfo]:
        t = text.lower().strip()
        m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", t)
        if m:
            r = self.rooms.get((int(m.group(1)), int(m.group(2))))
            return [r] if r else []
        out = [r for r in self.rooms.values() if t in r.name.lower()]
        out.sort(key=lambda r: r.key)
        return out[:limit]

    # ------------------------------------------------------------ routing
    PASSABLE_DEFAULT = {"normal", "door", "hidden", "text", "trap", "cast"}

    LEVEL_RE = re.compile(r"\(Level:\s*(\d+)\s*to\s*(\d+)\)", re.I)

    NEED_RE = re.compile(r"^\((Key|Item|Ticket/Item):\s*(\d+)", re.I)

    KEY_OR_RE = re.compile(r"^\(Key:\s*(\d+)\s*(\[or [^\]]+\])?\)", re.I)

    def _reconcile_key_doors(self):
        """pMUD: some key doors list 'or 151 picklocks' on one side only (15/862 N vs 15/863 S). Same door,
        same key — so the side that leaves it out can be picked / bashed too."""
        n = 0
        for k, r in self.rooms.items():
            for d, ex in r.exits.items():
                m = self.KEY_OR_RE.match(ex.etype or "")
                if not m or m.group(2):
                    continue
                other = self.rooms.get(ex.to)
                back = other.exits.get(REVERSE.get(d, "")) if other else None
                mb = self.KEY_OR_RE.match(back.etype or "") if back is not None and back.to == k else None
                if mb and mb.group(2) and mb.group(1) == m.group(1):
                    ex.etype = ex.etype.replace(m.group(0), f"(Key: {m.group(1)} {mb.group(2)})", 1)
                    n += 1
        self.reconciled_doors = n

    def exit_need(self, ex):
        """(item number, soft) an exit needs: a key or item (rope and grapple, golden idol…).
        soft = it can also be picked/bashed. None = needs nothing."""
        m = self.NEED_RE.match(ex.etype or "") if ex.kind in ("key", "item") else None
        if not m or int(m.group(2)) <= 0:
            return None
        it = self.items.get(int(m.group(2))) or {}
        if it and not it.get("gettable", 1) and m.group(1).lower() == "item":
            return None                              # a fixture in the room ("manhole"), not something you carry
        return int(m.group(2)), "pick" in ex.etype.lower()

    def ghost_keys(self) -> set:
        """Key numbers of pickable/bashable doors whose key isn't a real item (MME: 'Key: 1 [or 31
        picklocks/strength]') — there's no key to fetch; the door only gets picked or bashed."""
        g = getattr(self, "_ghost_keys", None)
        if g is None:
            g = set()
            for r in self.rooms.values():
                for ex in r.exits.values():
                    need = self.exit_need(ex) if ex.kind == "key" else None
                    if need and need[1] and need[0] not in self.items:
                        g.add(need[0])
            self._ghost_keys = g
        return g

    SPELL_ITEM_RE = re.compile(r"\b(failitem|checkitem)\s+(\d+)", re.I)

    def spell_items(self, sp, kind="failitem") -> frozenset:
        """Items a room / exit spell looks for on whoever it hits: 'river damage' and 'sea 1' do nothing to
        someone carrying a log raft (failitem 690), the golden idol teleport sends you the right way only with
        the idol (checkitem 1281). Any one of them will do."""
        c = getattr(self, "_spell_items", None)
        if c is None:
            c = self._spell_items = {}
        if (sp, kind) in c:
            return c[(sp, kind)]
        out = set()
        ab = {int(a[0]): a[1] for a in (self.spells.get(sp) or {}).get("abils") or []
              if len(a) >= 2 and a[0] is not None}
        tb = (getattr(self, "textblocks", {}) or {}).get(int(ab.get(148) or 0))
        for line in (tb[0] if tb else "").splitlines():
            if kind == "failitem" and not re.search(r"(?:^|:)\s*(?:cast|random|teleport)\s+\d", line):
                continue                     # 'failitem 339:droproomitem 339' places a quest item, does no harm
            for k, n in self.SPELL_ITEM_RE.findall(line):
                it = self.items.get(int(n)) or {}
                if k.lower() == kind and it and it.get("gettable", 1):
                    out.add(int(n))
            drinks = self.spell_drinks(sp) if kind == "failitem" else frozenset()
            if drinks and re.search(r"\bfailspell\s+\d", line, re.I):
                # Dan, 2026-11-04: the Scorching Desert ('failspell 711 …:random 2655') leaves alone whoever drank
                # from a waterskin — or wears the sunstone wristband (the item its rolls check further down)
                out |= drinks
                out |= self._nested_failitems(line)
        c[(sp, kind)] = frozenset(out)
        return c[(sp, kind)]

    FAILSPELL_RE = re.compile(r"\bfailspell\s+(\d+)", re.I)

    def spell_drinks(self, sp) -> frozenset:
        """Items you use to be under the spell a room spell skips ('failspell 711': the waterskin casts 711 when
        you drink from it)."""
        ab = {int(a[0]): a[1] for a in (self.spells.get(sp) or {}).get("abils") or []
              if len(a) >= 2 and a[0] is not None}
        tb = (getattr(self, "textblocks", {}) or {}).get(int(ab.get(148) or 0))
        want = {int(n) for n in self.FAILSPELL_RE.findall(tb[0] if tb else "")}
        if not want:
            return frozenset()
        out = set()
        for num, g in (getattr(self, "gear", None) or {}).items():
            casts = (g.get("abils") or {}).get(43) if isinstance(g.get("abils"), dict) else None
            if casts in want and (self.items.get(int(num)) or {}).get("gettable", 1):
                out.add(int(num))
        return frozenset(out)

    def _nested_failitems(self, line, depth=3) -> set:
        """failitems in the random blocks a line rolls ('random 2655' → 'random 2700' → 'failitem 1180')."""
        out = set()
        tbs = getattr(self, "textblocks", {}) or {}
        for n in re.findall(r"\brandom\s+(\d+)", line):
            tb = tbs.get(int(n))
            for sub in (tb[0] if tb else "").splitlines():
                for k, it in self.SPELL_ITEM_RE.findall(sub):
                    if k.lower() == "failitem" and (self.items.get(int(it)) or {}).get("gettable", 1):
                        out.add(int(it))
                if depth > 1:
                    out |= self._nested_failitems(sub, depth - 1)
        return out

    CAST_RE = re.compile(r"(?:pre|post)-(\d+)")

    def carry_needs(self, steps, skip_spell: int = 0) -> list:
        """[frozenset of item numbers] everyone walking these (room, exit) steps has to carry one of —
        rafts for the rivers and seas, the golden idol in the earthen catacombs. Each walker, not just the
        leader: one raft doesn't keep the party afloat. skip_spell: the first steps whose room spell doesn't count
        (the desert you're already standing in — walking out of it is all there is)."""
        out = []
        for i, (room, ex) in enumerate(steps):
            # an exit's own spell that checks for an item (the idol teleport); a room spell that an item
            # stops (a raft in the river) — not the quest rooms that check for the item you came to place
            sets = [self.spell_items(int(n), "checkitem") for n in self.CAST_RE.findall(ex.etype or "") if int(n)]                 if ex else []
            sp = getattr(self, "room_spells", {}).get(ex.to if ex else room)
            if sp and i >= skip_spell:
                sets.append(self.spell_items(sp))
            if ex is not None and id(ex) in (getattr(self, "carry_exits", None) or {}):
                sets.append(frozenset({self.carry_exits[id(ex)]}))      # a board fix: levitation potion
            if ex is not None and ex.kind == "item":
                need = self.exit_need(ex)
                if need and not need[1]:
                    sets.append(frozenset({need[0]}))  # 'Item: 942' — the mine pass gate: each walker shows one
            for s in sets:
                if s and s not in out:
                    out.append(s)
        return out

    def spell_damage(self, sp, have=frozenset(), depth=0) -> int:
        """The most a room / exit spell can hurt you for (MME's MaxBase), following its textblock's casts — 0 when
        something you carry stops it (a raft in the river, the item MME says negates it)."""
        cache = self.__dict__.setdefault("_spell_dmg", {})
        key = (int(sp), frozenset(have))
        if key in cache:
            return cache[key]
        s = self.spells.get(int(sp)) or {}
        ab = {int(a[0]): a[1] for a in s.get("abils") or [] if len(a) >= 2 and a[0] is not None}
        out = 0
        if have and ((set(self.spell_items(int(sp))) & set(have)) or
                     any(i in have for i in (getattr(self, "negates", {}) or {}).get(int(sp), []))):
            out = 0
        elif 1 in ab:
            out = int(s.get("MaxBase") or 0)
        elif int(ab.get(148) or 0) and depth < 4:
            from .mmetext import block_lines
            for segs in block_lines(getattr(self, "textblocks", {}) or {}, int(ab[148])):
                for sg in segs:
                    m = re.match(r"\s*cast\s+(\d+)", sg or "")
                    if m:
                        out = max(out, self.spell_damage(int(m.group(1)), have, depth + 1))
        cache[key] = out
        return out

    def room_damage(self, room, have=()) -> int:
        """What walking into this room can do to you (its room spell), 0 = nothing."""
        sp = (getattr(self, "room_spells", {}) or {}).get(tuple(room))
        return self.spell_damage(sp, frozenset(have or ())) if sp else 0

    def carry_item_set(self) -> frozenset:
        """Items an exit needs each walker to carry: the idol teleport's, 'Item: N' gates (the mine pass)."""
        c = getattr(self, "_carry_items", None)
        if c is None:
            out = set()
            for lst in (getattr(self, "item_casts", None) or {}).values():
                for _e, items in lst:
                    out |= set(items)
            for r in self.rooms.values():
                for ex in r.exits.values():
                    if ex.kind == "item":
                        need = self.exit_need(ex)
                        if need and not need[1]:
                            out.add(need[0])
            c = self._carry_items = frozenset(out)
        return c

    def is_fixture_exit(self, ex) -> bool:
        m = self.NEED_RE.match(ex.etype or "") if ex.kind == "item" else None
        return bool(m and self.exit_need(ex) is None)

    def gear_named(self, name) -> dict:
        it = self.item_names.get((name or "").strip().lower()) if getattr(self, "item_names", None) else None
        return (self.gear.get(it["num"]) or {}) if it and getattr(self, "gear", None) else {}

    def not_droppable(self, name) -> bool:
        """MME 'Not Droppable' (a quest item, a cursed one): dropping it does nothing — don't keep trying."""
        return bool(int(self.gear_named(name).get("Not Droppable") or 0))

    def item_name(self, num) -> str:
        return (self.items.get(num) or {}).get("name") or f"item #{num}"

    def bosses_by_room(self) -> dict:
        if getattr(self, "_boss_rooms", None) is None:
            out = {}
            for m in self.monsters.values():
                if m.get("boss") and m.get("in_game"):
                    for r in m.get("spawn_rooms") or []:
                        out.setdefault(tuple(r), []).append(m)
            self._boss_rooms = out
        return self._boss_rooms

    def why_no_route(self, start: Room, goal: Room, level=None, have=None, avoid=None, limit=3) -> list:
        """No route? The exits in the way: the cheapest path if blocked exits were allowed, and which
        of its exits normally aren't. [(room, dir, why)]"""
        import heapq

        def ok(r, d, ex):
            return self.can_use(ex, level=level, have=have, avoid=avoid, goal=goal)
        dist, prev, pq = {start: 0}, {}, [(0, start)]
        n = 0
        while pq and n < 400000:
            n += 1
            d0, c = heapq.heappop(pq)
            if c == goal:
                break
            if d0 > dist[c]:
                continue
            r = self.rooms.get(c)
            if not r:
                continue
            for dr, ex in r.exits.items():
                if ex.to not in self.rooms:
                    continue
                nd = d0 + (1 if ok(c, dr, ex) else 1000)
                if nd < dist.get(ex.to, 1e18):
                    dist[ex.to], prev[ex.to] = nd, (c, dr, ex)
                    heapq.heappush(pq, (nd, ex.to))
        if goal not in prev:
            return []
        out, node = [], goal
        while node != start:
            c, dr, ex = prev[node]
            if not ok(c, dr, ex):
                why = ex.etype or ex.kind
                if ex.kind == "hidden" and ex.needs_actions and not ex.action_cmds():
                    why = "a hidden exit that needs an action MME doesn't list"
                    far = [(rm, t) for rm, t in getattr(self, "remote_opens", {}).get(c, [])]
                    if far:
                        why = f"opened by typing '{far[0][1]}' in {far[0][0][0]}/{far[0][0][1]} first"
                elif getattr(ex, "req", None):
                    q = ex.req
                    wealth = (self.char or {}).get("wealth")
                    # 0.8.189: the fare too — Kingsport's 'secure passage to port blackwater' (2,000,000 copper) was
                    # reported as "needs level 1+" when the money was what was missing (realm walk sweep)
                    bits = ([f"level {q['level']}+"] if q["level"] and not (level and level >= q["level"]) else []) + \
                           [f"{self.item_name(i)}" for i in q["items"]] + \
                           [f"ability {a} ≥ {v}" for a, v in q["abil"]] + \
                           ([f"{q['price']:,} copper (you have {wealth:,})" if wealth is not None
                             else f"{q['price']:,} copper"] if q.get("price") else []) + \
                           (["a monster there first"] if q.get("monster") else [])
                    why = f"'{ex.text_command}' needs " + (", ".join(bits) or "something")
                    for a, v in q["abil"]:
                        h = self.quest_hint(a, v)
                        if h:
                            why += f" ({h})"
                            break
                elif ex.action_items():
                    why = "an action that needs " + ", ".join(self.item_name(i) for i in ex.action_items())
                elif ex.kind in ("key", "item"):
                    num = self.exit_need(ex)
                    why = f"needs {self.item_name(num[0])}" if num else why
                elif avoid and ex.to in avoid:
                    why = "goes through an area you avoid"
                elif self._sea(ex.to):
                    # 0.8.201, bug hunt: ~1,000 Crystal Lake rooms said "no route" with no reason at all
                    why = "open water — sea rooms throw you somewhere random; it needs a boat (or a sea spell)"
                elif (getattr(self, "refused_doors", None) or {}).get(id(ex), 0) > _time.time():
                    why = f"{ex.etype or 'a door'} — nobody in the party can open it (you said no to trying, or nobody was there to ask)"
                out.append((c, dr, why))
            node = c
        out = list(reversed(out))[:limit]
        for k in ([goal] if not isinstance(goal, (set, frozenset)) else []):
            for wv in (getattr(self, "npc_ways", {}).get(k) or [])[:1]:
                rm = wv["rooms"][0] if wv["rooms"] else None
                out.append((rm or k, "", f"{wv['name']} takes you there if you talk to it about '{wv['topic']}'"))
        return out

    ALIGN_ORDER = ["saint", "good", "lawful", "neutral", "seedy", "outlaw", "criminal", "villain", "fiend"]
    GATE_RE = re.compile(r"\((Class|Race):\s*(\d+)\s*OK,\s*(\d+)\s*NO\)", re.I)
    ALIGN_RE = re.compile(r"\(Alignment:\s*(\w+)\s*to\s*(\w+)\)", re.I)
    ABIL_GATE_RE = re.compile(r"\(Ability:\s*(\d+)\s*w/value\s*(-?\d+)\s*to\s*(-?\d+)\)", re.I)
    TOLL_RE = re.compile(r"\(Toll:\s*(\d+)\)", re.I)
    SMALL_TOLL = 100         # copper: payable while your cash isn't known yet (0.8.201)
    TRAP_RE = re.compile(r"\(Trap,\s*(\d+)\s*damage\)", re.I)
    # who is walking (the session fills it in): {"class", "race", "align", "abil": fn(id)->value|None,
    # "wealth", "party_classes", "party_races"} — gates with unknown answers stay closed
    char: dict = {}

    def gate_ok(self, ex) -> bool | None:
        """A class / race / alignment / ability gate: True = you (and your party) may pass, False = not,
        None = not a gate we understand."""
        c = self.char or {}
        if c.get("gate_any") and (self.GATE_RE.search(ex.etype) or self.ALIGN_RE.search(ex.etype)
                                  or self.ABIL_GATE_RE.search(ex.etype)):
            return True                              # ("is there a way in at all?" — the map, not this character)
        m = self.GATE_RE.search(ex.etype)
        if m:
            kind, ok_n, no_n = m.group(1).lower(), int(m.group(2)), int(m.group(3))
            mine = c.get("class" if kind == "class" else "race")
            group = [mine] + list(c.get("party_classes" if kind == "class" else "party_races") or [])
            if not mine:
                return False
            for who in group:
                if who is None:
                    continue
                if ok_n and who != ok_n:
                    return False
                if no_n and who == no_n:
                    return False
            return True
        m = self.ALIGN_RE.search(ex.etype)
        if m:
            al = (c.get("align") or "").lower()
            if not al:
                self.align_unknown = True            # (the walk checks 'who' and tries again)
                if getattr(self, "_align_any", False):
                    return True                      # (Go to's probe: is the alignment gate what's in the way?)
            lo, hi = m.group(1).lower(), m.group(2).lower()
            order = self.ALIGN_ORDER
            if al not in order or lo not in order or hi not in order:
                return False
            a, b = sorted((order.index(lo), order.index(hi)))
            if not a <= order.index(al) <= b:
                return False
            # every party member too, like class gates (0.8.201, bug hunt: a Seedy follower was refused at
            # "Saint to Good" and the Good leader walked on without them). Unknown alignments are skipped
            for pa in c.get("party_aligns") or ():
                pa = (pa or "").lower()
                if pa in order and not a <= order.index(pa) <= b:
                    return False
            return True
        m = self.ABIL_GATE_RE.search(ex.etype)
        if m:
            fn = c.get("abil")
            aid, lo, hi = int(m.group(1)), int(m.group(2)), int(m.group(3))
            val = fn(aid) if fn else None
            if val is None or not lo <= val <= hi:
                return False
            # every party member who's told us theirs too (Evolution, 2026-11-21: Jorah's NeutralQuest teleport)
            pf = c.get("party_abil")
            return all(lo <= pv <= hi for pv in (pf(aid) if pf else ()))
        return None

    def _load_textblocks(self, con):
        """Everything the room commands do, read through the whole textblock chain (mmetext): commands
        that take you somewhere ('dive sinkhole' → 12/2224) become exits you type; commands that open a
        hidden exit in this room become that exit's action; ones that open an exit in another room are
        kept as notes for 'why no route'."""
        from . import mmetext
        self.textblocks, self.room_actions, self.remote_opens = {}, {}, {}
        self.teleports = 0
        try:
            for num, act, link, cf in con.execute("SELECT * FROM textblocks"):
                self.textblocks[num] = (act, link, cf)
            room_tb = con.execute("SELECT * FROM room_tb").fetchall()
        except sqlite3.Error:
            return                                   # older import (v4): just the room_cmds lines
        # monsters you talk to that take you somewhere (a guide: 'visit' → 13/1) — shown in 'why no route'
        self.npc_ways = {}
        self.npc_gives = {}                      # item → [{"cmd", "room", "monster", "req"}]: 'ask commander orb'
        self.quest_steps = {}                    # ability → [{value, add, how, where, req}] from MME textblocks
        npc_rooms = {}
        for k, rr in self.rooms.items():
            if rr.npc:
                npc_rooms.setdefault(int(rr.npc), []).append(k)
        for num, (act, link, cf) in self.textblocks.items():
            for mn in re.findall(r"Monster #?(\d+)", cf or ""):
                m = self.monsters.get(int(mn))
                spawn = npc_rooms.get(int(mn)) or (m or {}).get("spawn_rooms") or []
                word = ((m or {}).get("name") or "").split()[-1:] or [""]
                # MajorMUD: 'ask <monster> <topic>' ("ask sphinx fire") — in the room where it stands
                for here in (npc_rooms.get(int(mn)) or [])[:3]:
                    rr = self.rooms.get(here)
                    for a in mmetext.npc_actions(self.textblocks, self.spells, num, here[0]):
                        cmd = f"ask {word[0]} {a['topic']}"
                        for tgt in a.get("opens") or []:
                            self._attach_open(here, tgt, [cmd], f"{cmd}", a.get("req"))
                        if a["to"] and a["to"] in self.rooms and a["to"] != here and rr is not None:
                            self._add_teleport(rr, {**a, "trigger": cmd, "triggers": [cmd]})
                for a in mmetext.npc_actions(self.textblocks, self.spells, num, spawn[0][0] if spawn else 0):
                    for it in a["req"].get("give_items") or []:
                        for at in spawn[:3]:
                            self.npc_gives.setdefault(it, []).append(
                                {"cmd": f"ask {word[0]} {a['topic']}", "room": tuple(at), "monster": int(mn),
                                 "req": a["req"]})
                    for ab, val, add in a["req"].get("gives") or []:
                        self.quest_steps.setdefault(ab, []).append(
                            {"value": val, "add": add, "how": f"talk to {(m or {}).get('name') or 'monster ' + mn} "
                                                              f"about '{a['topic']}'",
                             "where": spawn[:1], "req": a["req"]})
                    if a["to"] in self.rooms:
                        self.npc_ways.setdefault(a["to"], []).append(
                            {"monster": int(mn), "name": (m or {}).get("name") or f"monster {mn}",
                             "rooms": spawn[:4], **a})
        # room commands that call a monster up: 'touch statue' at the Black Steel Gate (8/461) → obsidian statue,
        # which drops the gate key. monster → [(room, command)]
        self.summons = {}
        self.summon_triggers = set()             # those commands, lower case: look right after one (session.send)
        for num, (act, link, cf) in self.textblocks.items():
            mm = re.match(r"Room (\d+)/(\d+)", cf or "")
            if not mm:
                continue
            for ln in str(act or "").splitlines():
                sm = re.match(r"\s*([^:]+?)\s*:.*\bsummon (\d+)", ln)
                if sm and mmetext.is_trigger(sm.group(1)):
                    lst = self.summons.setdefault(int(sm.group(2)), [])
                    at = (int(mm.group(1)), int(mm.group(2)))
                    if at not in [x[0] for x in lst]:
                        lst.append((at, sm.group(1)))
                    self.summon_triggers.add(sm.group(1).strip().lower())
        for mp, rm, tb in room_tb:
            here = (mp, rm)
            r = self.rooms.get(here)
            if not r:
                continue
            acts = mmetext.room_actions(self.textblocks, self.spells, tb, here)
            if acts:
                self.room_actions[here] = acts
            for a in acts:
                for ab, val, add in a["req"].get("gives") or []:
                    self.quest_steps.setdefault(ab, []).append(
                        {"value": val, "add": add, "how": f"'{a['trigger']}'", "where": [here], "req": a["req"]})
                if a["to"] and a["to"] in self.rooms:
                    self._add_teleport(r, a)
                for tgt in a["opens"]:
                    self._attach_open(here, tgt, list(a["triggers"]), a["trigger"], a.get("req"))
        # a monster's death spell moving a quest on ('pharaoh death' → DaoLordQuest 10, 'dao death' → 11): MME
        # doesn't say which monster casts it, the name does (Dan, 2026-11-04: the next step said Orfeo, who wants 11)
        for sn, sp in self.spells.items():
            md = re.match(r"^(.+?) death$", (sp.get("Name") or "").strip(), re.I)
            if not md:
                continue
            word = md.group(1).lower()
            # 'pharaoh' is Pharaoh Rastep, 'dao' the Dao Lord: the name holding the word, with a lair, most exp
            cands = [m for m in self.monsters.values()
                     if re.search(rf"\b{re.escape(word)}\b", (m.get("name") or "").lower())]
            m = max(cands, key=lambda m: (bool(m.get("spawn_rooms")), float(m.get("exp") or 0)), default=None)
            if not m:
                continue
            for req, _ch, _to, _op in mmetext.run(self.textblocks, self.spells, [f"cast {sn}"], 0):
                for ab, val, add in req.get("gives") or []:
                    self.quest_steps.setdefault(ab, []).append(
                        {"value": val, "add": add, "how": f"kill the {m['name']}",
                         "where": list(m.get("spawn_rooms") or [])[:1], "req": req})

    def _attach_open(self, here, tgt, cmds, label, req=None):
        """A command in `here` that opens room tgt's exit (remoteaction room … exit): the exit's action when
        it's this room; else a note for 'why no route' (you'd have to do it in `here` first). The item the command
        checks for comes along (0.8.189, realm walk sweep: 'show signet ring' opens the Heavy Iron Gates, 6/2619
        south, only with the signet ring — Go to walked a ringless character 944 rooms to them, and stood there
        showing a ring it didn't have)."""
        items = [int(i) for i in ((req or {}).get("items") or [])]
        room = (tgt[0], tgt[1])
        di = tgt[2] if len(tgt) > 2 else None
        d = DIRS[di] if isinstance(di, int) and 0 <= di < len(DIRS) else None
        if room != here:
            self.remote_opens.setdefault(room, []).append((here, label))
            return
        r = self.rooms.get(here)
        if not r:
            return
        exs = [r.exits[d]] if d and d in r.exits else list(r.exits.values())
        for ex in exs:
            if (ex.kind == "hidden" and ex.needs_actions and not ex.action_cmds()) or \
                    (ex.kind == "door" and d and not ex.actions):
                # (a door the room's command unlocks: 'turn stand' in the Golden Spire library opens the north
                # door — 1000 picklocks/strength, so bashing it never works)
                ex.actions.append({"n": 1, "cmds": list(cmds), "item": items[0] if items else None, "room_cmd": True})
                self.action_exits += 1

    SCATTER_COST = 8                     # a random drop: worth it only when there's no plain way

    def _range_spell(self, n):
        """(map, lo, hi) when spell n drops you in a random room of a range (the Warped Asylum's 'asylum':
        9/1183-1206; the Ancient Darkwood Tree's 'lower portal (uninvited)': the Caves of Chaos, 9/1292-1327)."""
        sp = self.spells.get(int(n)) or {}
        ab = {int(a[0]): a[1] for a in sp.get("abils") or [] if len(a) >= 2 and a[0] is not None}
        lo, hi = int(sp.get("MinBase") or 0), int(sp.get("MaxBase") or 0)
        if int(ab.get(141) or 0) > 0 and not int(ab.get(140) or 0) and 0 < lo <= hi and hi - lo <= 200                 and not int(ab.get(151) or 0):
            return int(ab[141]), lo, hi
        return None

    def _build_scatter(self):
        """Exits that drop you somewhere random in a range of rooms: one copy per room you might land in, so a
        route can use them (Dan, 2026-10-30, the phoenix quest). The walk takes the exit, finds out where it
        landed and plans again — in the asylum that's his 'n, s, n, s… till the old man shows'.
        self.scatter: {room: [(Exit, gate)]}; gate = [(verb, ability, value)] from the room command, or []."""
        self.scatter = {}

        def add(here, proto, cmd, rng, gate):
            mp, lo, hi = rng
            lst = self.scatter.setdefault(here, [])
            for n in range(lo, hi + 1):
                k = (mp, n)
                if k in self.rooms and k != here:
                    e = Exit(proto.dir if proto else f"@{cmd.lower()}", k,
                             proto.etype if proto else f"(Text: {cmd}) (Teleport)", False, False,
                             proto.kind if proto else "text")
                    e.scatter = rng
                    lst.append((e, gate))
        for k, r in self.rooms.items():
            for d, ex in r.exits.items():
                if ex.kind == "cast":
                    for n in self.CAST_RE.findall(ex.etype or ""):
                        rng = self._range_spell(n) if int(n) else None
                        if rng:
                            add(k, ex, None, rng, [])
        for num, (act, _link, cf) in (getattr(self, "textblocks", {}) or {}).items():
            mm = re.match(r"Room (\d+)/(\d+)", cf or "")
            if not mm:
                continue
            here = (int(mm.group(1)), int(mm.group(2)))
            if here not in self.rooms:
                continue
            for ln in str(act or "").splitlines():
                parts = [x.strip() for x in ln.split(":")]
                if len(parts) < 2 or not parts[0]:
                    continue
                gate, rng = [], None
                for v in parts[1:]:
                    w = v.split()
                    if not w:
                        continue
                    if w[0] in ("checkability", "testability") and len(w) >= 3:
                        gate.append((w[0], int(w[1]), int(w[2])))
                    elif w[0] == "failability" and len(w) >= 2:
                        gate.append(("failability", int(w[1]), 0))
                    elif w[0] == "cast" and len(w) >= 2 and w[1].isdigit():
                        rng = self._range_spell(w[1])
                        break
                    elif w[0] in ("teleport", "text", "random"):
                        break
                if rng and not any(e.text_command == parts[0] and g == gate
                                   for e, g in self.scatter.get(here, [])):
                    add(here, None, parts[0], rng, gate)

    def _build_item_casts(self):
        """0.8.180: a 'Cast:' exit whose spell sends you somewhere only if you carry an item. The earthen
        catacombs' idol teleport (16/2273 east, spell 857: 'checkitem 1281:teleport 2431', else 2228) is
        listed as leading to 2274, so it was thrown out as a teleport and a Go to from the Abandoned Temple to
        the Deranged Priest went 286 steps the long way instead of ~93 with the golden idol (Dan, 2026-11-12).
        self.item_casts: {room: [(Exit to where it really lands, frozenset of items, any one of which does)]}."""
        self.item_casts = {}
        try:
            from . import mmetext
        except ImportError:
            return
        tbs = getattr(self, "textblocks", {}) or {}
        for k, r in self.rooms.items():
            for ex in r.exits.values():
                if ex.kind != "cast":
                    continue
                for n in self.CAST_RE.findall(ex.etype or ""):
                    if not int(n):
                        continue
                    try:
                        branches = list(mmetext.run(tbs, self.spells, [f"cast {n}"], ex.to[0]))
                    except Exception:
                        continue
                    for req, _ch, to, _op in branches:
                        items = frozenset(int(i) for i in (req.get("items") or []))
                        if not to or not items or to not in self.rooms or to == k:
                            continue
                        if any(req.get(x) for x in ("abil", "abil_eq", "no_abil", "classes", "races", "monster")):
                            continue                 # more than an item decides it: leave it to can_use
                        e = Exit(ex.dir, to, ex.etype, ex.visible, ex.door, "cast")
                        e.item_cast = items
                        self.item_casts.setdefault(k, []).append((e, items))
                        break                        # the first branch that fires is the one that counts

    def scatter_ok(self, gate) -> bool:
        """Does a room command's quest check let you through? Unknown values: maybe — try it."""
        fn = (self.char or {}).get("abil")
        for verb, a, v in gate:
            val = fn(a) if fn else None
            if val is None:
                continue
            if verb == "checkability" and val < v:
                return False
            if verb == "testability" and val != v:
                return False
            if verb == "failability" and val:
                return False
        return True

    def _add_teleport(self, r, a):
        key = f"@{a['trigger'].lower()}"
        if key in r.exits or self.limited_use_item(a["trigger"], single=False):
            return                                   # (a limited-use item's teleport: only when you use it yourself)
        req = a["req"]
        trig = ", ".join(t for t in a["triggers"] if "," not in t and ")" not in t) or a["trigger"]
        tag = " ".join([f"(Text: {trig})", "(Teleport)"] +
                       [f"(Ability: {x} w/value {v} to 99999)" for x, v in req["abil"]] +
                       ([f"(Level: {req['level']} to {req['maxlevel'] or 9999})"] if req["level"] else []) +
                       (["(Chance)"] if a["chance"] and not req.get("voyage") else []) +
                       ([f"(Boat: {req['voyage']} rounds)"] if req.get("voyage") else []) +
                       ([f"(Price: {req['price']})"] if req.get("price") else []))
        ex = Exit(key, a["to"], tag, False, False, "text")
        ex.req = req
        ex.chance = a["chance"] and not req.get("voyage")
        r.exits = {**r.exits, key: ex}
        self.teleports += 1

    def quest_hint(self, ab, want, have=None) -> str:
        """Where MME says quest ability `ab` gets raised toward `want` (the next step from `have`)."""
        steps = getattr(self, "quest_steps", {}).get(int(ab)) or []
        if not steps:
            return ""
        cur = have or 0
        nxt = sorted((s for s in steps if not s["add"] and s["value"] > cur), key=lambda s: s["value"])
        if not nxt:
            return ""                                # nothing after this value: done (Revolution on 12)

        def doable(s):
            # a step that wants this flag at a value you're past or short of isn't yours yet (Orfeo wants 11 —
            # at 9 the next is the pharaoh)
            q = s["req"]
            return all(v <= cur for a, v in q.get("abil") or [] if int(a) == int(ab)) and                 all(v == cur for a, v in q.get("abil_eq") or [] if int(a) == int(ab))
        now = [s for s in nxt if doable(s)]
        pick = now[0] if now else nxt[0]
        where = pick["where"][0] if pick["where"] else None
        r = self.room(where) if where else None
        need = []
        q = pick["req"]
        if q.get("level"):
            need.append(f"level {q['level']}+")
        need += [self.item_name(i) for i in q.get("items") or []]
        need += [f"ability {a} = {v}" for a, v in q.get("abil") or []]
        loc = f" at {r.name} ({where[0]}/{where[1]})" if r else ""
        return f"next step: {pick['how']}{loc}" + (f" — needs {', '.join(need)}" if need else "")

    def _sea(self, room) -> bool:
        sp = getattr(self, "room_spells", {}).get(room)
        if not sp:
            return False
        c = getattr(self, "_sea_spells", None)
        if c is None:
            c = self._sea_spells = {n for n, v in self.spells.items() if re.match(r"^sea \d", (v.get("Name") or "").lower())}
        return sp in c

    # stateful puzzles MME can't describe: (from, to) → the moves that actually work (pMUD's pinned paths)
    PINNED = {((12, 2052), (12, 2077)): "w w n n n n e e s w s s e s e e n n n w s u"}

    def _pin(self, route, start):
        """Splice a pinned path in where the plain route crosses it (Great Pyramid level 4)."""
        if not route:
            return route
        nodes = [start] + [e.to for e in route]
        # pMUD-walked puzzle answers: Paradigm only (0.8.201, bug hunt — set by board_fixes.apply; unset = as before)
        for (a, b), moves in (self.PINNED if getattr(self, "paradigm", True) else {}).items():
            if a in nodes and b in nodes and nodes.index(a) < nodes.index(b):
                i, j = nodes.index(a), nodes.index(b)
                seg, cur = [], a
                for d in moves.upper().split():
                    ex = self.rooms[cur].exits.get(d) if cur in self.rooms else None
                    if not ex:
                        seg = None
                        break
                    seg.append(ex)
                    cur = ex.to
                if seg and cur == b:
                    route = route[:i] + seg + route[j:]
        return route

    def _cast_moves_you(self, ex) -> bool:
        """A 'Cast: pre-N, post-M' exit whose spell teleports you (gloomy teleport → the Black Moat): it
        doesn't really lead where the map says."""
        key = id(self.char)
        c = getattr(ex, "_moves", None)
        if c is not None and c[0] == key:
            return c[1]
        from . import mmetext
        moves = False
        for n in re.findall(r"(?:pre|post)-(\d+)", ex.etype or ""):
            if not int(n):
                continue
            sp = self.spells.get(int(n)) or {}
            ab = {int(a[0]): a[1] for a in sp.get("abils") or [] if len(a) >= 2 and a[0] is not None}
            if int(ab.get(141) or 0) or int(ab.get(140) or 0):
                moves = True                         # teleports you outright (gloomy teleport → the Black Moat)
                continue
            for req, _ch, to, _op in mmetext.run(getattr(self, "textblocks", {}), self.spells, [f"cast {n}"], ex.to[0]):
                if to and to != ex.to and self._branch_applies(req):
                    moves = True
        ex._moves = (key, moves)
        return moves

    def _branch_applies(self, req) -> bool:
        """Would this textblock branch fire for you? Quest values we don't know count as 'maybe not'."""
        fn = (self.char or {}).get("abil")
        for a, v in req.get("abil") or []:
            val = fn(a) if fn else None
            if val is not None and val < v:
                return False
        for a, v in req.get("abil_eq") or []:
            val = fn(a) if fn else None
            if val is None or val != v:
                return False
        for a, v in req.get("no_abil") or []:
            val = fn(a) if fn else None
            if val is None or val >= v:
                return False
        return True

    def wall(self, room, d, mins=120):
        """The game said "There is no exit in that direction!" twice from a room we're sure of: not an exit that
        missed, a wall (for now — a hidden or timed one may open later). Unlike a failed edge, a Go to doesn't
        clear it to try once more (PVE walked into 1/2104's south wall 16 times over two Go tos)."""
        import time as _t
        if not hasattr(self, "walls"):
            self.walls = {}
        self.walls[(room, d)] = _t.time() + mins * 60
        self.forget_routes()

    def fail_edge(self, room, d, mins=30):
        """An exit that just didn't work for us (door won't open, search keeps missing, 'no exit'):
        routes go round it for a while."""
        import time as _t
        if not hasattr(self, "failed_edges"):
            self.failed_edges = {}
        self.failed_edges[(room, d)] = _t.time() + mins * 60
        self.forget_routes()
        # a hidden exit opened by a command ('push block' / 'push square block' / 'move block'): the wording
        # we used didn't do it — next time try the next one MME lists
        r = self.rooms.get(room)
        ex = r.exits.get(d) if r else None
        for a in (getattr(ex, "actions", None) or []) if ex is not None and ex.kind == "hidden" else []:
            cm = a.get("cmds") or []
            if len(cm) > 1:
                a["cmds"] = cm[1:] + cm[:1]

    def req_ok(self, ex, level=None, have=None) -> bool:
        """A room command's conditions: level, class, race, quest abilities, items, cash. Something we
        can't check (an ability we haven't been told) counts as met — the walker asks with 'abil N'."""
        req = getattr(ex, "req", None)
        if not req:
            return True
        c = self.char or {}
        if c.get("gate_any"):                        # ("is there a way in at all?" — the map, not this character)
            if req["items"] and not all(i in (have or []) for i in req["items"]):
                return False
            return not req.get("monster")
        if req["level"] and (not level or level < req["level"]):
            return False
        if req["maxlevel"] and level and level > req["maxlevel"]:
            return False
        if req["classes"] and c.get("class") is not None and c["class"] not in req["classes"]:
            return False
        if req["races"] and c.get("race") is not None and c["race"] not in req["races"]:
            return False
        fn = c.get("abil")
        pf = c.get("party_abil")
        for a, v in req["abil"]:
            val = fn(a) if fn else None
            if val is not None and val < v:
                return False
            if any(pv < v for pv in (pf(a) if pf else ())):
                return False
        for a, v in req.get("no_abil", []):
            val = fn(a) if fn else None
            if val is not None and val >= v:
                return False
            if any(pv >= v for pv in (pf(a) if pf else ())):
                return False
        if req["items"]:
            names = {str(h).lower() for h in (have or [])}
            for i in req["items"]:
                if i not in (have or []) and self.item_name(i).lower() not in names:
                    return False
        if req["price"] and c.get("wealth") is not None and c["wealth"] < req["price"]:
            return False
        if req.get("monster"):
            return False                             # needs a particular monster there first
        return True

    # ------------------------------------------------------------ items with a few uses
    USE_VERBS = {"use", "rub", "read", "zap", "invoke", "activate", "wave", "blow", "break", "quaff", "drink",
                 "eat", "throw"}

    def limited_use_item(self, cmd, single=True) -> str:
        """'use silverm' → 'token of Silvermere': a command that spends an item with only a few uses (MME UseCount
        2–9998 — the token is 5 a day; with single, one-shot items too: a potion, a scroll). Never a way for a Go to or a route: only when you type it (Evolution,
        2026-11-09: 'use silverm' got learned as a way from 6/3109 to the Pier, and Go to used it). '' = no."""
        words = (cmd or "").strip().lower().lstrip(".").split()
        if len(words) < 2 or words[0] not in self.USE_VERBS:
            return ""
        args = [a_ for a_ in words[1:] if a_ not in ("of", "the", "a", "an")] or words[1:]
        if len(args[0]) < 3:
            return ""
        gear = getattr(self, "gear", None) or {}
        c = getattr(self, "_limited", None)
        if c is None or c[0] is not gear or c[2] != len(gear):
            lim = []
            for g in gear.values():
                try:
                    uses = int(g.get("UseCount") or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < uses < 9999 and g.get("name"):
                    lim.append((g["name"], [w_ for w_ in re.split(r"[\s-]+", g["name"].lower()) if w_], uses))
            c = self._limited = (gear, lim, len(gear))
        for name, ws, uses in c[1]:
            # every word typed starts a word of the name ('use silverm'; 'use potion of levitation' isn't the
            # cure poison potion)
            if (single or uses > 1) and all(any(w_.startswith(a_) for w_ in ws) for a_ in args):
                return name
        return ""

    def spends_item(self, ex) -> str:
        """The charged item (a few uses, not a one-shot) an exit's typed command or opening action spends ('' =
        none). One-shots stay plannable: the potion of levitation up to the catacombs is a carry need the party's
        check buys (board_fixes). Cached on the exit."""
        v = getattr(ex, "_spends", None)
        if v is None:
            v = ""
            for c in list(ex.text_commands) + [a_ for a in (ex.actions or []) for a_ in (a.get("cmds") or [])[:1]]:
                v = self.limited_use_item(c, single=False)
                if v:
                    break
            try:
                ex._spends = v
            except AttributeError:
                pass
        return v

    # ------------------------------------------------------------ exits MME doesn't have
    LEARNED_TAG = "(Learned)"

    def add_learned(self, src, move: str, dst) -> bool:
        """A way between two rooms that MME's map doesn't list, seen in a MegaMUD path or walked for real
        ('enter pyramid', a portal, a door MME forgot). Added to the map so routes can use it."""
        r = self.rooms.get(tuple(src))
        if not r or tuple(dst) not in self.rooms or not move:
            return False
        mv = clean_move(move)
        if not mv:
            return False                             # a party / telepath command, not a way to walk
        if self.limited_use_item(mv):
            return False                             # 'use silverm': the token has 5 uses a day — yours to spend
        if (tuple(src), mv.lower(), tuple(dst)) in getattr(self, "forgotten", set()):
            return False                             # tried and failed this session
        if self.look_alike(src) and self.look_alike(dst):
            # both ends look like other rooms (the pyramid): a MegaMUD path's hash or the tracker matched a
            # twin — 'ask sphinx fire' got pinned on the 12/1830 dead end that way. Not a fact; don't map it
            return False
        d = norm_dir(mv)
        for ex in r.exits.values():
            if ex.to == tuple(dst) and (ex.dir == d or ex.accepts(mv) or not d):
                return False                         # already known
        if d and d in r.exits and r.exits[d].to == tuple(dst):
            return False
        # (a new dict, not an insert: a route may be walking this room's exits on another thread)
        if d and d not in r.exits:
            # not 'visible': the game doesn't list it (that's why MME hasn't got it), and a visible one made the room
            # stop matching itself — the loop lost its place at 13/530, FRZNLOOP, ASTRLOOP (0.8.221, bug hunt)
            r.exits = {**r.exits, d: Exit(d, tuple(dst), self.LEARNED_TAG, False, False, "normal")}
        else:
            key = f"@{mv.lower()}"
            if key in r.exits:
                return False
            r.exits = {**r.exits, key: Exit(d or key, tuple(dst), f"(Text: {mv}) {self.LEARNED_TAG}", False, False, "text")}
        self.learned = getattr(self, "learned", []) + [[list(src), mv, list(dst)]]
        self.forget_routes()                         # a new way on the map
        return True

    TRAP_WALL = 1000         # a trap that could take you to the hang-up line: only when there's no other way
    DOOR_WALL = 300          # a door nobody in the party can pick or bash: only when there's no other way

    def trap_cost(self, dmg) -> float:
        """0.8.190 (Dan): a trap weighed against the walker's HP — the weakest member's max HP in a party (party sync),
        down to the hang-up line. One that could take you there (or kill you) is a wall; smaller ones scale in between.
        Your HP not known: the old 1 + damage/10, at most 21."""
        c = self.char or {}
        hp = int(c.get("max_hp") or 0)
        if hp <= 0:
            return 1 + min(20, dmg / 10)
        spare = hp * (1 - min(90, int(c.get("hangup_pct") or 0)) / 100)
        if dmg >= spare:
            return self.TRAP_WALL
        return 1 + round(150 * dmg / spare, 1)

    def door_beaten(self, ex, have=None):
        """Can the walker (or, leading, the party's best basher / picker — party sync) get through this locked
        door: True / False, or None when it doesn't say or your strength and picklocks aren't known yet."""
        if ex.kind not in ("door", "key") or ex.action_cmds():
            # (a door a room command or lever opens isn't picked or bashed. 0.8.201, walk check: action_cmds(), not
            #  ex.actions — 1/1104 N's warehouse door has one action with no command, which made it cost 1, not 60)
            return None
        m = re.search(r"\[(?:or\s+)?(any|\d+)\s+picklocks(/strength)?", ex.etype or "", re.I)
        if not m:
            return None
        if ex.kind == "key":
            need = self.exit_need(ex)
            if need and have and need[0] in have and need[0] not in self.ghost_keys():
                return True                          # the key's in hand (or on the way: a key run fetches it)
        if m.group(1).lower() == "any":
            return True
        n = int(m.group(1))
        if n >= 1000:
            return None                              # (timed / opened some other way: costed on its own)
        dp = (self.char or {}).get("door_power")
        if not dp:
            return None
        pick, strength = dp
        return (pick or 0) >= n or bool(m.group(2) and (strength or 0) >= n)

    def door_hopeless(self, ex, have=None) -> bool:
        """0.8.201 (Dan): a door nobody in the party can pick or bash, and no key for it in hand or to be fetched
        (have): door_beaten says no, or a '[1000 picklocks/strength]' door that isn't one of the known timed ones,
        on a walked segment, or opened by a room command. Routes ask before using one; dist_map never counts it."""
        if ex is None or ex.kind not in ("door", "key") or ex.actions:
            return False
        b = self.door_beaten(ex, have)
        # '[1000 picklocks/strength]' doors (door_beaten None) are NOT hopeless: those open some other way in the
        # game — a lever, a quest step, a room action MME doesn't spell out (Morukai's lair door, 9/1423 W, on the
        # phoenix trip) — and they keep their old cost-60 "probably opens" treatment. Only an ordinary locked door
        # that's plainly beyond everyone's picklocks/strength asks first.
        return b is False

    def refuse_door(self, ex, mins=180):
        """The player said No to a door nobody can open (or nobody answered): a wall for routing for a while."""
        import time as _t
        self.refused_doors = {k: u for k, u in (getattr(self, "refused_doors", None) or {}).items() if u > _t.time()}
        self.refused_doors[id(ex)] = _t.time() + mins * 60
        self.forget_routes()

    def door_refused(self, ex, have=None) -> bool:
        """dist_map: a refused door, or one nobody can open ("how far is X" / errands don't count rooms behind it)."""
        import time as _t
        if (getattr(self, "refused_doors", None) or {}).get(id(ex), 0) > _t.time():
            return True
        return ex.kind in ("door", "key") and self.door_hopeless(ex, have)

    ONE_WAY_DOOR = 2000                  # a '1000 picklocks/strength' door nothing we know opens: the last resort

    @staticmethod
    def one_way_door(ex) -> bool:
        return ex is not None and ex.kind == "door" and "1000 picklocks" in (ex.etype or "").lower() \
            and not ex.action_cmds()

    def exit_cost(self, ex, cur=None, have=None) -> float:
        """Steps an exit 'costs' for routing: traps and tolls are walked round when it's cheap to."""
        if ex.kind == "trap":
            m = self.TRAP_RE.search(ex.etype)
            return self.trap_cost(int(m.group(1)) if m else 30)
        if ex.kind == "toll":
            return 3
        if "spell trap" in ex.etype.lower():
            return 25
        req = getattr(ex, "req", None)
        if req and req.get("voyage"):
            return 1 + req["voyage"] * 5 / 1.6           # rounds at sea, in walking steps
        if getattr(ex, "chance", False):
            return 6
        at = self.action_at(ex)
        if at:
            # walk over to where it's opened from, and back: at its real length (0.8.190, Dan — the 6/861 four-lever
            # puzzle is ~150 rooms round, not 12)
            return self.remote_cost(cur, ex) if cur is not None else 12
        if self.door_beaten(ex, have) is False:
            # 0.8.190 (Dan): '[61 picklocks/strength]' with strength 60 and nobody stronger: another way when there is
            # one, instead of walking there and stopping at "the door is locked" (14/332 Harbor Road Gate)
            return self.DOOR_WALL
        if ex.kind == "door" and "1000 picklocks" in (ex.etype or "").lower() and not ex.action_cmds():
            # (0.8.201, walk check: an action with no command opens nothing we know — still a 1000 door)
            # nobody picks or bashes it and nothing we know opens it (the Slum Street Rusted Gate, 1/1169 E — Buddy's
            # Go to to the Tree House sat at it, 2026-11-01): only when there's no other way at all (the Great Pyramid's
            # timed doors have none). 0.8.213 (Dan, 2026-11-20): it was 60, so Buddy's Go to the Darkened Tunnels Throne
            # Room took 15/401 NE ('1000' this side, '41' the other — it never opens from here) over the real way in,
            # the two levers (15/604, 15/730) that open 15/477 N — about 295 steps round
            return self.ONE_WAY_DOOR
        if ex.kind == "cast":
            return 3                                 # casts something on you as you pass (MME 'Cast: pre/post')                                 # a skill roll / random: may take a few tries
        return 1

    def remote_cost(self, cur, ex) -> float:
        """The walk round an exit's actions done in other rooms and back to it (each in order), in steps — remembered.
        A room that can't be reached that way: 100."""
        cache = self.__dict__.setdefault("_remote_costs", {})
        key = (tuple(cur), ex.dir)
        if key in cache:
            return cache[key]
        steps = ex.steps_needed() if hasattr(ex, "steps_needed") else []
        stops = [tuple(a["at"]) if a.get("at") else tuple(cur) for a in steps] + [tuple(cur)]
        pos, total = tuple(cur), 0
        for room in stops:
            if room != pos:
                n = self._walk_len(pos, room)
                if n is None:
                    total = None
                    break
                total += n
                pos = room
        cache[key] = 100.0 if total is None else float(max(2, total + 1))
        return cache[key]

    def _walk_len(self, a, b, limit=20000):
        """Rooms from a to b over plain ways (no keys, gates, teleports or other remote-action walls), or None."""
        from collections import deque
        seen, q, n = {a: 0}, deque([a]), 0
        while q and n < limit:
            cur = q.popleft()
            n += 1
            if cur == b:
                return seen[cur]
            r = self.rooms.get(cur)
            for e in (r.exits.values() if r else ()):
                if e.to in seen or e.to not in self.rooms or getattr(e, "req", None) or \
                        e.kind not in ("normal", "door", "hidden", "text", "trap"):
                    continue
                if e.kind == "hidden" and "pass" not in (e.etype or "").lower() and \
                        "search" not in (e.etype or "").lower():
                    continue                         # (another wall opened from somewhere: not counted as a way)
                seen[e.to] = seen[cur] + 1
                q.append(e.to)
        return None

    @staticmethod
    def action_at(ex):
        """The room a hidden exit (or a lever door) is opened from, when that isn't the exit's own room (None
        otherwise). The Black Fortress gatehouse door (7/1173 E) is opened by the lever in the hidden room south of
        it (7/1175) — pulling 'lever' in the gatehouse does nothing (sweep, 2026-10-29)."""
        if ex is None or ex.kind not in ("hidden", "door"):
            return None
        steps = ex.steps_needed() if hasattr(ex, "steps_needed") else (getattr(ex, "actions", None) or [])
        for a in steps:
            if a.get("at"):
                return tuple(a["at"])
        return None

    def action_rooms(self, cmd) -> set:
        """Every room an exit-opening action ('twist hand', 'push eye') is done in; empty = not one we know."""
        if getattr(self, "_act_rooms_for", None) is not self.rooms:
            idx = {}
            for key, r in self.rooms.items():
                for ex in r.exits.values():
                    for a in getattr(ex, "actions", None) or []:
                        at = tuple(a["at"]) if a.get("at") else key
                        for c in a.get("cmds") or []:
                            idx.setdefault(c.strip().lower(), set()).add(at)
            self._act_rooms, self._act_rooms_for = idx, self.rooms
        return self._act_rooms.get((cmd or "").strip().lower(), set())

    def can_use(self, ex, passable=None, level=None, have=None, avoid=None, goal=None) -> bool:
        """Can we walk through this exit? (your level, keys/items, hidden exits we can open, class / race /
        alignment / ability gates, tolls you can pay, avoid list)"""
        passable = passable or self.PASSABLE_DEFAULT
        if not ex or ex.to not in self.rooms:
            return False
        on_segment = id(ex) in (getattr(self, "segment_exits", None) or ())
        if ex.kind not in passable and not self.is_fixture_exit(ex) and not on_segment:
            # (a walked-for-real segment's exits always plan: its key is picked up on the way — pyramid level 3)
            lm = self.LEVEL_RE.search(ex.etype) if (level and ex.kind == "restricted") else None
            need = self.exit_need(ex) if have is not None else None
            gate = self.gate_ok(ex) if ex.kind == "restricted" else None
            toll = self.TOLL_RE.search(ex.etype) if ex.kind == "toll" else None
            wl = (self.char or {}).get("wealth")
            # 0.8.201, bug hunt: cash not read yet (a Go to before the first stat line) — a small toll is assumed
            # payable (start_path checks the cash before walking), not a wall: 1/1381's 5-copper gate made 28 rooms 121
            paid = bool(toll and (int(toll.group(1)) <= self.SMALL_TOLL if wl is None else wl >= int(toll.group(1)))
                        and (self.char or {}).get("tolls", True))
            spell_trap = ex.kind == "restricted" and "spell trap" in ex.etype.lower() and \
                (bool((self.char or {}).get("spell_traps")) or getattr(self, "_trap_ok", False))
            if ex.kind == "restricted" and (self.char or {}).get("gate_any") and self.LEVEL_RE.search(ex.etype):
                gate = True                          # (the map-only "any way in?" check: a level gate isn't a wall)
            if not (lm and int(lm.group(1)) <= level <= (int(lm.group(2)) or 9999)) and not (need and need[0] in have) \
                    and not gate and not paid and not spell_trap:
                return False
        if avoid and ex.to in avoid and ex.to != goal and not (isinstance(goal, (set, frozenset)) and ex.to in goal):
            return False
        if ex.kind != "restricted" and ex.etype and (self.ABIL_GATE_RE.search(ex.etype) or self.ALIGN_RE.search(
                ex.etype) or self.GATE_RE.search(ex.etype)) and self.gate_ok(ex) is False:
            # a gate on a typed command, not just on a 'restricted' exit: 'ask Jorah teleport' (Ability 127 —
            # a quest Dan's good mage doesn't have) — PVE walked to the Blue Tower and asked him 8 times
            return False
        if getattr(self, "_no_chance", False) and "(Chance)" in (ex.etype or "") and ex.to != goal:
            return False                             # (a party's first try keeps off chance jumps — route())
        if getattr(self, "_no_danger", False) and ex.to != goal and not (isinstance(goal, (set, frozenset))
                                                                         and ex.to in goal):
            fn = getattr(self, "danger_fn", None)
            if fn is not None and fn(ex.to):
                return False                         # (a lair that would maul you — route() tries without first)
        if id(ex) in (getattr(self, "shut_doors", None) or ()):
            return False                             # pMUD: a pyramid 1000-door that never opens (board_fixes)
        rd = getattr(self, "refused_doors", None)
        if rd and rd.get(id(ex), 0) > _time.time():
            return False                             # nobody can open it and the player said No (0.8.201)
        if getattr(ex, "req", None) and not self.req_ok(ex, level, have):
            return False
        if ex.kind == "item" and getattr(self, "_party_carry", False):
            need = self.exit_need(ex)
            if need and not need[1] and need[0] not in ((self.char or {}).get("party_have") or ()):
                return False                         # every member shows one: not unless they all carry it
        if (ex.kind == "text" or ex.actions) and self.spends_item(ex):
            return False                             # spends a limited-use item (the token of Silvermere): never planned
        if ex.kind == "item" and "(Item: 185)" in (ex.etype or "") and ex.to[0] == 17 and 2901 <= ex.to[1] <= 2937:
            return False                             # pMUD: in the Golden Phoenix maze the 'manhole' links are walls
        if self._sea(ex.to) and not (ex.to == goal or (isinstance(goal, (set, frozenset)) and ex.to in goal)):
            return False                             # pMUD: sea rooms throw you somewhere random — boats only
        if ex.kind == "cast" and self._cast_moves_you(ex):
            return False                             # pMUD: the spell sends you somewhere else (Ebon Blade maze)
        if ex.kind == "hidden" and "pass" not in ex.etype.lower() and "search" not in ex.etype.lower():
            if not ex.action_cmds():
                return False                     # needs an action we don't know
            if ex.action_items() and not (have and all(i in have for i in ex.action_items())):
                return False                     # …or an item for it we don't carry
        if ex.kind == "door" and ex.actions and have is not None and ex.action_items() and \
                not all(i in have for i in ex.action_items()):
            return False                         # a door its room command opens only with an item (signet ring)
        return True

    MEMO_SECS = 600

    def forget_routes(self):
        """Something changed under the routes (a wall, a door that wouldn't open, the party, a quest step)."""
        self._memo = {}

    def _memo_key(self, *parts):
        c = self.char or {}
        abil = c.get("abil")
        segs = getattr(self, "segments", None)
        if segs:
            from .board_fixes import _progress
            prog = tuple(_progress(self, sg) for sg in segs)   # how far along the pyramid maze we are
        else:
            prog = None
        return parts + (prog, bool(c.get("party")), getattr(self, "danger_fn", None) is not None,
                        getattr(self, "danger_key", None), abil(133) if abil else None, c.get("abil_sig"),
                        c.get("party_abil_sig") or (),
                        tuple(c.get("party_classes") or ()), tuple(c.get("party_races") or ()),
                        tuple(c.get("party_aligns") or ()),
                        c.get("class"), c.get("race"), c.get("align"), c.get("tolls"), c.get("spell_traps"),
                        int(c.get("max_hp") or 0) // 25, c.get("hangup_pct"), c.get("door_power"), c.get("combat"),
                        frozenset(c.get("party_have")) if c.get("party_have") is not None else None,
                        getattr(self, "party_strict_only", False),
                        (c.get("wealth") or 0) // 500 if c.get("wealth") is not None else None, c.get("gate_any"))

    def route(self, start: Room, goal, passable: set | None = None, max_nodes: int = 200000,
              avoid: set | frozenset | None = None, level: int | None = None, have: set | None = None):
        """The way from start to goal (see _route), remembered for MEMO_SECS: the same Go to again — or the
        same leg asked by several planners in one Go to — doesn't search the map again (Dan, 2026-10-30:
        'it should remember that path… locking up like that on PvP is dangerous')."""
        import time as _t
        ua = getattr(self, "user_avoid", None)
        if ua:
            # rooms you struck off in the route preview for this Go to (0.8.208, Dan): never walked through
            g_ = goal if isinstance(goal, (set, frozenset)) else {tuple(goal)} if goal else set()
            avoid = (frozenset(avoid or ()) | frozenset(ua)) - frozenset(g_) - {tuple(start) if start else None}
        try:
            key = self._memo_key("r", start, goal if not isinstance(goal, set) else frozenset(goal),
                                 frozenset(passable) if passable else None, max_nodes,
                                 frozenset(avoid) if avoid else None, level, frozenset(have) if have else None)
        except TypeError:
            key = None
        with self._plan_lock:
            hit = self._memo.get(key) if key is not None else None
            if hit and _t.time() - hit[0] < self.MEMO_SECS:
                return list(hit[1]) if hit[1] is not None else None
            r = self._route_uncached(start, goal, passable, max_nodes, avoid, level, have)
            if key is not None:
                if len(self._memo) > 4000:
                    self._memo = {}
                self._memo[key] = (_t.time(), tuple(r) if r is not None else None)
            return r

    def _route_uncached(self, start: Room, goal, passable: set | None = None, max_nodes: int = 200000,
                        avoid: set | frozenset | None = None, level: int | None = None, have: set | None = None):
        # 0.8.190 (Dan): leading a party, an exit every walker needs their own item for (the golden idol teleport, a
        # mine pass) only when every follower is known to carry it — another way first; only if there's none, as
        # before (the party's '@have' round sorts it out)
        c = self.char or {}
        if c.get("party") and c.get("party_have") is not None:
            self._party_carry = True
            try:
                r = self._route_rules(start, goal, passable, max_nodes, avoid, level, have)
            finally:
                self._party_carry = False
            if r is not None or getattr(self, "party_strict_only", False):
                return r
        return self._route_rules(start, goal, passable, max_nodes, avoid, level, have)

    def _route_rules(self, start: Room, goal, passable: set | None = None, max_nodes: int = 200000,
                     avoid: set | frozenset | None = None, level: int | None = None, have: set | None = None):
        # soft rules, tried in order and dropped only when there's no way with them: keep out of lairs that would
        # maul you (the Webbed Mine Chamber's wraith spiders — Dan: "not wreckless shit like that"), and a party
        # keeps off '(Chance)' jumps (the Building Rooftops split the party)
        party = bool((self.char or {}).get("party"))
        dz = getattr(self, "danger_fn", None) is not None
        tries = [(c, d) for c, d in ((True, True), (False, True), (True, False), (False, False))
                 if (party or not c) and (dz or not d)]
        r = None
        loosest = None
        for i, (c, d) in enumerate(tries):
            if i == 1 and len(tries) > 2:
                # the strictest found nothing: if the loosest finds nothing either, none of the ones between will —
                # a failed search was 4 whole-map passes (Miserable PVE, 2026-11-06: 70 s on the mini PC)
                self._no_chance = self._no_danger = False
                try:
                    loosest = self._route(start, goal, passable, max_nodes, avoid, level, have)
                finally:
                    self._no_chance = self._no_danger = False
                if loosest is None:
                    break
            if (c, d) == (False, False) and i > 0 and loosest is not None:
                r = loosest
                break
            self._no_chance, self._no_danger = c, d
            try:
                r = self._route(start, goal, passable, max_nodes, avoid, level, have)
            finally:
                self._no_chance = self._no_danger = False
            if r is not None:
                if d:
                    r = self._danger_detour(r, c, start, goal, passable, max_nodes, avoid, level, have)
                break
        if r is None and getattr(self, "scatter", None):
            # no way at all without a random drop (the asylum's old man, the uninvited portal into the Caves of
            # Chaos): allow those — last, so every other route stays as it was
            self._use_scatter = True
            try:
                self._no_chance = self._no_danger = False
                any_way = self._route(start, goal, passable, max_nodes, avoid, level, have)  # (the loosest)
                for c, d in (tries if any_way is not None else ()):
                    self._no_chance, self._no_danger = c, d
                    try:
                        r = self._route(start, goal, passable, max_nodes, avoid, level, have)
                    finally:
                        self._no_chance = self._no_danger = False
                    if r is not None:
                        break
            finally:
                self._use_scatter = False
        if r and not (self.char or {}).get("spell_traps") and not getattr(self, "_trap_ok", False) and \
                any(self.one_way_door(e) for e in r):
            # the only way without spell traps is a '1000' door nothing we know opens (0.8.213, Dan 2026-11-20: Buddy's
            # Go to the Darkened Tunnels Throne Room sat at 15/401 NE, '1000' this side — the real way in disarms the
            # spell traps and pulls the levers at 15/604 and 15/730, his FMASDRKT path): the traps are the lesser
            # evil — the walker disarms them first
            self._trap_ok = True
            try:
                self._no_chance = self._no_danger = False
                r2 = self._route(start, goal, passable, max_nodes, avoid, level, have)
            finally:
                self._trap_ok = False
            if r2 and not any(self.one_way_door(e) for e in r2):
                r = r2
        if r is None and not (self.char or {}).get("spell_traps") and not getattr(self, "_trap_ok", False):
            # (0.8.201, walk check: with 'walk through spell-trap exits' off a trap was a wall — the Darkened Tunnels
            #  mark the trap only on the way OUT of six side pockets, so Go to walked in and then had no way back.
            #  Off now means "avoid": with no other way at all, plan again allowing them, still costed extra)
            self._trap_ok = True
            try:
                self._no_chance = self._no_danger = False
                r = self._route(start, goal, passable, max_nodes, avoid, level, have)
            finally:
                self._trap_ok = False
        if r and not isinstance(goal, (set, frozenset)):
            from .board_fixes import prefer_via
            r = prefer_via(self, start, r, lambda a, b: self._route(a, b, passable, max_nodes, avoid, level, have))
        if r and getattr(self, "segments", None):
            from .board_fixes import splice
            r = splice(self, start, r, have)       # walked-for-real ways MME gets wrong (pyramid level 3)
        return r

    DANGER_DETOUR = 30

    def _danger_detour(self, r, c, start, goal, passable, max_nodes, avoid, level, have):
        """Keeping out of a dangerous lair is worth a detour, not any detour: Buddy (Dan, 2026-11-03) set off on
        338 rooms to the Frozen Cavern, 28 rooms away past the skeletal acid beasts on the Dirt Path. The way
        round wins only while it's at most twice as long and no more than DANGER_DETOUR rooms extra."""
        self._no_chance, self._no_danger = c, False
        try:
            short = self._route(start, goal, passable, max_nodes, avoid, level, have)
        finally:
            self._no_chance = self._no_danger = False
        if short is not None and len(r) > len(short) + min(self.DANGER_DETOUR, len(short)):
            return short
        return r

    def dist_map(self, start: Room, level=None, have=None, avoid=None, reverse=False, max_nodes: int = 400000) -> dict:
        import time as _t
        ua = getattr(self, "user_avoid", None)
        if ua:
            avoid = (frozenset(avoid or ()) | frozenset(ua)) - {tuple(start) if start else None}
        key = self._memo_key("d", start, level, frozenset(have) if have else None,
                             frozenset(avoid) if avoid else None, reverse)
        with self._plan_lock:
            hit = self._memo.get(key)
            if hit and _t.time() - hit[0] < self.MEMO_SECS:
                return hit[1]
            d = self._dist_map(start, level, have, avoid, reverse, max_nodes)
            self._memo[key] = (_t.time(), d)
            return d

    def _dist_map(self, start: Room, level=None, have=None, avoid=None, reverse=False, max_nodes: int = 400000) -> dict:
        """{room: steps} for every room reachable from start (reverse=True: every room that can reach start),
        by the same rules as a route. One search instead of one per candidate: errands.source_for ranked every
        shop and lair room of an item with its own route — 391 searches for a log raft, the window stuck for a
        minute at the boatman (Revolution, 2026-10-30)."""
        import heapq
        import time as _t
        passable = self.PASSABLE_DEFAULT
        if reverse:
            inc = getattr(self, "_rev_exits", None)
            if inc is None:
                inc = {}
                for k, r in self.rooms.items():
                    for ex in r.exits.values():
                        inc.setdefault(ex.to, []).append((k, ex))
                self._rev_exits = inc
        walls = {k for k, u in (getattr(self, "walls", None) or {}).items() if u > _t.time()}
        failed = walls | {k for k, u in (getattr(self, "failed_edges", None) or {}).items() if u > _t.time()}
        dist, q = {start: 0}, [(0, start)]
        bg = threading.current_thread() is not threading.main_thread()
        # 0.8.201, bug hunt: the same rules as route() — dist_map said "unreachable" where route() found a way:
        #  * a sea room (or an avoided one) may be the END of a trip, just not walked through (17/1541);
        #  * item teleports (the golden idol) count when you carry the item, as route() takes them;
        #  * random drops (the asylum's cast exit 9/1182 → Warped Asylum) count only for rooms there's no other
        #    way to — route() also takes them only as the last resort (a second pass, below)
        terminal = set()
        ic = (getattr(self, "item_casts", None) or {}) if (have and not reverse) else {}
        sc = (getattr(self, "scatter", None) or {}) if not reverse else {}
        party_have = set((self.char or {}).get("party_have") or ())

        def extra(cur, scatter):
            for ex, items in ic.get(cur, ()):
                if getattr(self, "_party_carry", False) and not (items & party_have):
                    continue
                if items & set(have):
                    yield ex.to, ex
            for ex, gate in (sc.get(cur, ()) if scatter else ()):
                if self.scatter_ok(gate):
                    yield ex.to, ex

        def run(q, base, scatter):
            n = 0
            while q and n < max_nodes:
                d, cur = heapq.heappop(q)
                if d > dist.get(cur, 1 << 30):
                    continue
                n += 1
                if bg and not n % YIELD_EVERY:
                    _t.sleep(0.002)                  # let the window breathe (see YIELD_EVERY)
                if cur in terminal:
                    continue                         # a sea room: you can go there, not through it
                if reverse:
                    pairs = inc.get(cur, ())
                else:
                    r = self.rooms.get(cur)
                    pairs = [(ex.to, ex) for ex in r.exits.values()] if r else ()
                for nxt, ex in list(pairs) + list(extra(cur, scatter)):
                    frm = nxt if reverse else cur
                    if (frm, ex.dir) in failed or self.door_refused(ex, have):
                        continue
                    stop = False
                    is_extra = getattr(ex, "item_cast", None) is not None or getattr(ex, "scatter", None) is not None
                    if not is_extra and not self.can_use(ex, passable, level, have, avoid, start if reverse else None):
                        if reverse or not self.can_use(ex, passable, level, have, avoid, nxt):
                            continue
                        stop = True                  # only as the trip's end (route() lets the goal be one)
                    elif is_extra and avoid and nxt in avoid:
                        continue
                    if base is not None and nxt in base:
                        continue
                    if d + 1 < dist.get(nxt, 1 << 30):
                        dist[nxt] = d + 1
                        if stop:
                            terminal.add(nxt)
                        else:
                            terminal.discard(nxt)
                        heapq.heappush(q, (d + 1, nxt))

        run(q, None, False)
        seeds = [(dist[k], k) for k in sc if k in dist and k not in terminal]
        if seeds:
            # (every way out of the first pass's rooms to a new one is a random drop, so those rooms are the seeds)
            heapq.heapify(seeds)
            run(seeds, dict(dist), True)
        if not (self.char or {}).get("spell_traps") and not getattr(self, "_trap_ok", False):
            # (0.8.221, bug hunt: route() takes spell-trap exits when there's no other way (0.8.201 / 0.8.213), this
            #  didn't — the Darkened Tunnels Throne Room 15/416 and 251 more rooms read as unreachable, so errand
            #  sources and the scrolls / training lists skipped them.) Last pass: only rooms not reached yet
            def trap_side(k):
                exs = [ex for _, ex in inc.get(k, ())] if reverse else \
                    list(getattr(self.rooms.get(k), "exits", {}).values())
                return any(ex.kind == "restricted" and "spell trap" in (ex.etype or "").lower() for ex in exs)
            seeds = [(v, k) for k, v in dist.items() if k not in terminal and trap_side(k)]
            heapq.heapify(seeds)
            self._trap_ok = True
            try:
                run(seeds, dict(dist), True)
            finally:
                self._trap_ok = False
        return dist

    def _route(self, start: Room, goal, passable: set | None = None, max_nodes: int = 200000,
               avoid: set | frozenset | None = None, level: int | None = None, have: set | None = None):
        """BFS shortest path. goal: a Room or a set of Rooms. Returns list[Exit] or None.
        avoid: rooms never to walk through (the goal itself is still allowed).
        level: your level — level-restricted exits ("Level: 10 to 999") you qualify for become passable."""
        import heapq
        import time as _t
        passable = passable or self.PASSABLE_DEFAULT
        goals = goal if isinstance(goal, (set, frozenset)) else {goal}
        if start in goals:
            return []
        fe = getattr(self, "failed_edges", None)
        if fe:
            now = _t.time()
            for k in [k for k, until in fe.items() if until < now]:
                fe.pop(k, None)
        walls = {k: u for k, u in (getattr(self, "walls", None) or {}).items() if u > _t.time()}
        failed = ({**walls, **(fe or {})} if walls else fe) or None
        # cheapest path (traps, tolls and spell traps cost extra), ties broken by fewer steps
        prev: dict[Room, tuple] = {start: None}
        best = {start: 0.0}
        q = [(0.0, 0, start)]
        n = 0
        bg = threading.current_thread() is not threading.main_thread()
        while q and n < max_nodes:
            cost, _tie, cur = heapq.heappop(q)
            if cost > best.get(cur, 1e18):
                continue
            n += 1
            if bg and not n % YIELD_EVERY:
                _t.sleep(0.002)                      # let the window breathe (see YIELD_EVERY)
            if cur in goals:
                steps, node = [], cur
                while prev[node]:
                    p, e = prev[node]
                    steps.append(e)
                    node = p
                return self._pin(list(reversed(steps)), start)
            r = self.rooms.get(cur)
            if not r:
                continue
            for ex in r.exits.values():
                if not self.can_use(ex, passable, level, have, avoid, goals):
                    continue
                if failed and (cur, ex.dir) in failed:
                    continue                         # this exit just failed us (locked, search missed…)
                c2 = cost + self.exit_cost(ex, cur, have)
                if c2 < best.get(ex.to, 1e18):
                    best[ex.to] = c2
                    prev[ex.to] = (cur, ex)
                    heapq.heappush(q, (c2, id(ex.to) & 0xffff, ex.to))
            for ex, items in ((getattr(self, "item_casts", None) or {}).get(cur, ()) if have else ()):
                # a teleport that only goes there if you carry the item (the golden idol): you do — and leading a
                # party, every follower too (0.8.190, Dan: or the idol-less ones land in 16/2228)
                if getattr(self, "_party_carry", False) and \
                        not (items & set((self.char or {}).get("party_have") or ())):
                    continue
                if not (items & set(have)) or (avoid and ex.to in avoid and ex.to not in goals) or                         (failed and (cur, ex.dir) in failed):
                    continue
                c2 = cost + self.exit_cost(ex)
                if c2 < best.get(ex.to, 1e18):
                    best[ex.to] = c2
                    prev[ex.to] = (cur, ex)
                    heapq.heappush(q, (c2, id(ex.to) & 0xffff, ex.to))
            for ex, gate in ((getattr(self, "scatter", None) or {}).get(cur, ()) if getattr(self, "_use_scatter", False)
                             else ()):
                # a random drop (the asylum, the uninvited portal): planned as if it lands where it suits;
                # the walk finds out where it really did and plans again
                if (avoid and ex.to in avoid and ex.to not in goals) or (failed and (cur, ex.dir) in failed)                         or not self.scatter_ok(gate):
                    continue
                c2 = cost + self.SCATTER_COST
                if c2 < best.get(ex.to, 1e18):
                    best[ex.to] = c2
                    prev[ex.to] = (cur, ex)
                    heapq.heappush(q, (c2, id(ex.to) & 0xffff, ex.to))
        return None
