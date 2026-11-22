"""Realm walk sweep: whole Go tos, start to finish, all over the realm, on the practice server with honest gates
(simserver.Gates: locked doors, keys that wear out, items like the golden idol, tolls, traps, class / race /
alignment / ability / level gates, the spells exits and rooms cast on you, room commands from MME's textblocks,
hidden exits you search for or open, shops). A real Session walks each one; the practice server keeps its own
copy of the map, so nothing the bot learns on the way changes the 'real' realm.

Walks: fixed ones (the Lost City through the Earthen Catacombs with the golden idol, Kingsport and round it,
Tidepool's south entrance, the volcano / Undermountain, Dark-Elf City, the Great Pyramid), from towns (every bank),
and between random far-apart rooms. Per walk: planned length, rooms really walked, stuck / loop / timeout,
wrong-way legs (walked far more than planned), tracking drift, the room or exit where it went wrong, and what the
practice server saw (blocked exits, doors, teleports).

  python tests\\e2e_realm_walk.py --walks 40 --seed 1 --tag a              one worker
  python tests\\e2e_realm_walk.py --mode fixed --tag fixed
  python tests\\e2e_realm_walk.py --merge                                   tests\\realm_walk_report.txt from
                                                                           every tests\\realm_walk_*.json
Run several workers at once on different --port / --seed / --tag. Backburner tooling: exit 0 unless it breaks."""
import argparse, collections, json, os, random, re, sys, tempfile, threading, time, traceback
ROOT = os.environ.get("MUDPILOT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# MUDPILOT_SRC: walk with another copy of the mudpilot package (a before/after comparison); the map and the
# results stay here
sys.path.insert(0, os.environ.get("MUDPILOT_SRC") or ROOT)
DB = os.path.join(ROOT, "mudpilot", "bundled", "Paradigm.db")
ROOMS_MD = os.path.join(ROOT, "tests", "fixtures", "Paradigm_Rooms.md")
REPORT = os.path.join(ROOT, "tests", "realm_walk_report.txt")

# labelled places to go (group: rooms) — Rooms.md numbers, plus the ones Dan named
FIXED = [
    # (label, start, target)
    ("Lost City: Abandoned Temple → Deranged Priest (idol)", (16, 1412), (16, 356)),
    ("Lost City: Abandoned Temple → Bank of the Lost City", (16, 1412), (16, 320)),
    ("Lost City: Abandoned Temple → Temple Stairs", (16, 1412), (16, 311)),
    ("Lost City: Abandoned Temple → Catacombs, Outside Kuel", (16, 1412), (16, 2268)),
    ("Lost City: Silvermere → Deranged Priest", (1, 1), (16, 356)),
    ("Lost City: Bank of Albion → Lost City bank", (14, 1), (16, 320)),
    ("Lost City: Abandoned Temple → Practice Dummy", (16, 1412), (16, 541)),
    ("Lost City: Deranged Priest → Abandoned Temple", (16, 356), (16, 1412)),
    ("Catacombs: Outside Kuel → Lost City bank", (16, 2268), (16, 320)),
    ("Tidepool south entrance from the beach", (13, 337), (13, 503)),
    ("Tidepool south entrance from Silvermere", (1, 1), (13, 503)),
    ("Tidepool south entrance from Bank of Albion", (14, 1), (13, 503)),
    ("Kingsport: Bank of Albion → Throne of Albion", (14, 1), (14, 1290)),
    ("Kingsport: Bank of Albion → North Gate", (14, 1), (14, 987)),
    ("Kingsport: Bank of Albion → Harbor Ramp", (14, 1), (14, 815)),
    ("Kingsport: Bank of Albion → Castle Gates", (14, 1), (14, 1145)),
    ("Kingsport: Bank of Albion → North Pier", (14, 1), (14, 805)),
    ("Kingsport: Bank of Albion → Burial Vault", (14, 1), (14, 1077)),
    ("Kingsport: Bank of Albion → City Sewers, Ladder", (14, 1), (14, 1667)),
    ("Kingsport: Throne of Albion → Bank of Albion", (14, 1290), (14, 1)),
    ("Kingsport: Harbor Wharf → King's Gate", (14, 702), (14, 1015)),
    ("Kingsport → Northwick Village", (14, 1), (14, 2415)),
    ("Kingsport → Southwick Village", (14, 1), (14, 1895)),
    ("Kingsport → Captain Trendel", (14, 1), (14, 2814)),
    ("Kingsport → Albion Waterfall", (14, 1), (14, 2489)),
    ("Kingsport → Eastern Crossroads", (14, 1), (14, 1818)),
    ("Kingsport → Blackwater bank", (14, 1), (14, 267)),
    ("Volcano: Fiery Lair from Lost City bank", (16, 320), (16, 2118)),
    ("Undermountain from Lost City bank", (16, 320), (16, 1522)),
    ("Dark-Elf City Moatside from Silvermere", (1, 1), (8, 559)),
    ("Dark-Elf Castle Gatehouse from Silvermere", (1, 1), (8, 560)),
    ("Great Pyramid from Silvermere", (1, 1), (12, 1800)),
]
# towns' far places: from each bank to these
FAR = [("Lost City / Deranged Priest", (16, 356)), ("Kingsport / Bank of Albion", (14, 1)),
       ("Tidepool south entrance", (13, 503)), ("Volcano / Fiery Lair", (16, 2118)),
       ("Undermountain Caverns", (16, 1522)), ("Dark-Elf City Moatside", (8, 559)), ("Great Pyramid", (12, 1800)),
       ("Kingsport Throne of Albion", (14, 1290)), ("Lost City bank", (16, 320))]


def rooms_md_targets(world):
    out = []
    try:
        lines = open(ROOMS_MD, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return out
    for ln in lines:
        f = ln.split(":")
        if len(f) < 8:
            continue
        m = re.search(r"[\s+\-]*(\d{1,3})[ /](\d{1,5})\s*$", f[7])
        if m and (int(m.group(1)), int(m.group(2))) in world.rooms:
            out.append((f[6], f[7][:m.start()].strip(), (int(m.group(1)), int(m.group(2)))))
    return out


def rname(w, k):
    r = w.room(tuple(k)) if k else None
    return f"{k[0]}/{k[1]} {r.name}" if r else f"{k}"


def pick_walks(world, mode, n, seed, level, kit):
    rng = random.Random(seed)
    walks = []
    if mode in ("fixed", "all"):
        walks += [{"cat": "fixed", "label": l, "start": s, "target": t} for l, s, t in FIXED
                  if s in world.rooms and t in world.rooms]
    banks = sorted(k for k, r in world.rooms.items() if r.name.startswith("Bank of"))
    labelled = rooms_md_targets(world)
    have = set(kit)
    if mode in ("towns", "all"):
        for b in banks:
            for lab, t in FAR:
                walks.append({"cat": "town", "label": f"{world.room(b).name} → {lab}", "start": b, "target": t})
        rng.shuffle(walks)
    if mode in ("kingsport", "all"):
        kp = [x for x in labelled if x[0] in ("Kingsport", "Crownlands", "Albion River System")]
        for _ in range(n if mode == "kingsport" else max(10, n // 4)):
            a, b = rng.sample(kp, 2)
            walks.append({"cat": "kingsport", "label": f"{a[1]} → {b[1]}", "start": a[2], "target": b[2]})
    if mode in ("random", "labelled", "all"):
        pool = [k for k, r in world.rooms.items() if len([e for e in r.exits.values() if e.to in world.rooms]) >= 1
                and not world._sea(k)]
        tries = 0
        want = n if mode in ("random", "labelled") else max(10, n // 2)
        got = 0
        while got < want and tries < want * 30:
            tries += 1
            if mode == "labelled" or (mode == "all" and got % 2):
                a = rng.choice(labelled)[2] if rng.random() < 0.3 else rng.choice(pool)
                lab = rng.choice(labelled)
                b, tl = lab[2], f"{lab[0]}: {lab[1]}"
            else:
                a, b = rng.choice(pool), rng.choice(pool)
                tl = "random"
            if a == b:
                continue
            rt = world.route(a, b, level=level, have=have | world.ghost_keys())
            if rt is None or len(rt) < 60:
                continue
            got += 1
            walks.append({"cat": "labelled" if tl != "random" else "random", "label": tl, "start": a, "target": b,
                          "ideal": len(rt)})
    return walks



# ------------------------------------------------------------------ --party: a pretend party on the leader's side
# The practice server can't host a real party (no invite / follow / telepath between players), so --party plays the
# followers from the server end, the way MudPilot reads a party when it leads: their rows in 'par', their names in
# the room's "Also here" (they're always right behind you), their MudPilots' party sync over telepath ('@mpsync hi'
# answered, '@mpsync me lvl= hp= str= pick= cls= kit=' told), answers to '@have <item>' and '@flags <n>', items handed
# to them ('give log raft to Buddy') and asked of them ('@do give black star key to Tester'), and Game Data -> Players
# (race / alignment). Every exit the leader takes is checked for each follower too (level, class, race, alignment,
# quest flag, the item / toll / fare each walker pays, the rafts and idols each walker carries, a trap or room spell
# that could kill them, a chance jump that can split the party): whatever would have left someone behind is an issue.
#   --party "Revolution:lvl=30,hp=250,str=80,pick=0,cls=Warrior,race=Dwarf,align=Neutral,kit=golden idol+rope and grapple,abil=134.8,sync=1,cash=500"
#   --party-random 2      two followers, their level / HP / kit / class / race / alignment rolled again for every walk
PARTY_NAMES = ["Revolution", "Buddy", "Evolution", "Skittles", "Lyra"]
PARTY_KIT_POOL = ["golden idol", "rope and grapple", "log raft", "mine pass", "waterskin", "climbing harness"]


class FakeParty:
    def __init__(self, world, spec="", rand=0, seed=1, level=55, sim=None):
        self.w, self.sim, self.level = world, sim, level
        self.rng = random.Random(seed * 7919 + 13)
        self.rand = rand
        self.members = {}              # name -> {lvl, hp, str, pick, cls, race, align, kit: Counter, abil, sync, cash}
        self.base = {}                 # name -> the member as specified (each walk starts from it)
        self.events = []               # (what, member, room, detail) this walk
        self.sent = []                 # (member, what the leader telepathed them) this walk
        self.leader = "Tester"
        if spec:
            for chunk in [c for c in spec.split(";") if c.strip()]:
                name, _, rest = chunk.partition(":")
                m = {}
                for kv in [x for x in rest.split(",") if "=" in x]:
                    k, v = [y.strip() for y in kv.split("=", 1)]
                    if k in ("lvl", "hp", "str", "pick", "cash", "sync"):
                        m[k] = int(v)
                    elif k == "kit":
                        m["kit"] = [x.strip() for x in v.split("+") if x.strip()]
                    elif k == "abil":
                        m["abil"] = {int(x.split(".")[0]): int(x.split(".")[1]) for x in v.split("+") if "." in x}
                    else:
                        m[k] = v
                self.base[name.strip().capitalize()] = m
        for i in range(rand):
            nm = PARTY_NAMES[i % len(PARTY_NAMES)]
            self.base.setdefault(nm, {"sync": 1 if self.rng.random() < 0.75 else 0})
        self.reset()

    def _member(self, m):
        out = {"lvl": self.level, "hp": 13 * self.level, "str": 60, "pick": 0, "cls": "Warrior", "race": "Human",
               "align": "Good", "kit": ["golden idol", "rope and grapple"], "abil": {}, "sync": 1, "cash": 5000000}
        out.update(m)
        return out

    def roll(self):
        """A random follower: anything from 40 levels under the leader to the leader's level, any class / race /
        alignment, some of the walkers' own items."""
        r = self.rng
        lvl = max(1, self.level - r.choice([0, 0, 0, 0, 5, 10, 15, 25]))
        cls = r.choice([v.get("Name") for v in self.w.classes.values()])
        race = r.choice([v.get("Name") for v in self.w.races.values()])
        align = r.choice(["Saint", "Good", "Good", "Lawful", "Neutral", "Neutral", "Seedy", "Outlaw", "Criminal",
                          "Villain"])
        kit = [k for k in PARTY_KIT_POOL if r.random() < (0.6 if k in ("golden idol", "rope and grapple") else 0.25)]
        hp = int(lvl * r.uniform(8, 18))
        return {"lvl": lvl, "hp": hp, "str": r.choice([40, 60, 80, 100, 120]), "pick": r.choice([0, 0, 0, 60, 120]),
                "cls": cls, "race": race, "align": align, "kit": kit,
                "abil": ({134: r.choice([0, 7, 8, 9, 13])} if r.random() < 0.3 else {}),
                "cash": r.choice([200, 5000, 5000000, 5000000])}

    def reset(self):
        self.events, self.sent = [], []
        self.members = {}
        for n, b in self.base.items():
            m = self._member({**(self.roll() if self.rand else {}), **b})
            m["kit"] = collections.Counter(int((self.w.item_names.get(k.lower()) or {}).get("num") or 0)
                                           for k in m["kit"])
            m["kit"].pop(0, None)
            self.members[n] = m

    def describe(self):
        return "; ".join(f"{n} L{m['lvl']} {m['hp']}hp {m['cls']}/{m['race']}/{m['align']} str{m['str']} "
                         f"pick{m['pick']} cash{m['cash']} kit[{', '.join(self.w.item_name(k) for k in sorted(m['kit']) if m['kit'][k] > 0)}]"
                         + (f" abil{m['abil']}" if m['abil'] else "") + ("" if m["sync"] else " (MegaMUD)")
                         for n, m in self.members.items())

    def find(self, word):
        word = (word or "").strip().lower()
        return next((n for n in self.members if n.lower() == word), None)

    # ---- what their MudPilots say
    def me_line(self, n):
        m = self.members[n]
        kit = sorted(k for k, q in m["kit"].items() if q > 0 and k in self.w.carry_item_set())
        return (f"@mpsync me lvl={m['lvl']} hp={m['hp']} ma={m['hp'] // 2} ac=40 dr=8 dmg=150 "
                f"cls={m['cls'].replace(' ', '-')} str={m['str']}" + (f" pick={m['pick']}" if m['pick'] else "")
                + f" kit={'.'.join(str(k) for k in kit)}")

    def party_rows(self, p):
        rows = ["The following people are in your travel party:",
                f"  {self.leader + ' Leader':<30}{'(Mage)':<13} [M:{int(100 * p.ma / max(p.max_ma, 1)):3d}%] "
                f"[H:{int(100 * p.hp / max(p.max_hp, 1)):3d}%] - Frontrank"]
        for n, m in self.members.items():
            rows.append(f"  {n + ' Follower':<30}{'(' + m['cls'] + ')':<13} [M:100%] [H:100%] - Backrank")
        return rows

    def telepath(self, n, msg):
        """The leader telepathed member n: the lines the game shows back."""
        m, w = self.members[n], self.w
        self.sent.append((n, msg))
        out = []
        low = msg.strip().lower()
        if low.startswith("@mpsync hi"):
            if m["sync"]:
                out += [f"{n} telepaths: {{mpsync ok 0.8.222 tune lvl={m['lvl']}}}", f"{n} telepaths: {self.me_line(n)}"]
            else:
                out.append(f"{n} telepaths: {{command invalid or not allowed}}")
        elif low.startswith("@mpsync"):
            pass
        elif low.startswith("@have "):
            want = low[6:].strip()
            hits = [w.item_name(k) for k, q in m["kit"].items() if q > 0 and want in w.item_name(k).lower()]
            out.append(f"{n} telepaths: {{yes: {', '.join(hits)}}}" if hits else f"{n} telepaths: {{no {want}}}")
        elif low.startswith("@flags"):
            a = low[6:].strip()
            if not m["sync"]:
                out.append(f"{n} telepaths: {{command invalid or not allowed}}")
            elif a.isdigit():
                v = m["abil"].get(int(a))
                nm = (getattr(w, "abil_names", {}) or {}).get(int(a))
                head = f"{nm} ({a})" if nm else f"ability {a}"
                out.append(f"{n} telepaths: {{{head} = {v if v is not None else 'not set'}}}")
        elif re.match(r"@do (bash|pick) \w+", low) and self.sim is not None and self.sim.players:
            # they bash / pick the door too (standing right behind you), each try a roll on their own stats
            g, p = self.sim.gates, self.sim.players[-1]
            saved = (g.strength, g.picklocks)
            g.strength, g.picklocks = m["str"], m["pick"]
            try:
                for piece in re.split(r"\^M", msg.strip()[4:]):
                    got = []
                    g.door_cmd(p, piece.lower().split(), got)
                    if any(x.startswith(("You bashed the door open", "You successfully unlocked")) for x in got):
                        self.events.append(("member opened door", n, tuple(p.room), piece))
                        out.append(f"{n} {piece.split()[0]}s the door open!")
                        break
            finally:
                g.strength, g.picklocks = saved
        elif low.startswith("@do give ") or low.startswith("@do .give "):
            mm = re.match(r"@do \.?give (.+?) to (\w+)", low)
            if mm:
                num = next((k for k, q in m["kit"].items() if q > 0 and mm.group(1) in w.item_name(k).lower()), None)
                if num is not None and self.sim is not None and self.sim.players:
                    m["kit"][num] -= 1
                    self.sim.players[-1].items[num] += 1
                    self.events.append(("handed over", n, None, w.item_name(num)))
                    out.append(f"{n} gives you {w.item_name(num)}.")
        return out

    def give(self, p, item_words, n):
        """'give log raft to Buddy' from the leader."""
        g = self.sim.gates
        num = g.item_named(p, item_words.split())
        if num is None:
            return [f"You don't have {item_words} to give!"]
        p.items[num] -= 1
        self.members[n]["kit"][num] += 1
        self.events.append(("given", n, None, self.w.item_name(num)))
        return [f"You give {self.w.item_name(num)} to {n}."]

    # ---- would each follower have got through the exit the leader just took?
    def follow(self, g, here, ex, landed):
        from mudpilot import simserver as ss
        w = self.w
        et = ex.etype or ""
        saved = (g.cls_num, g.race_num, g.align)
        for n, m in self.members.items():
            fp = type("F", (), {})()
            fp.level, fp.abil, fp.items, fp.cash = m["lvl"], dict(m["abil"]), m["kit"], m["cash"]
            fp.hp = fp.max_hp = m["hp"]
            g.cls_num = next((k for k, v in w.classes.items() if (v.get("Name") or "").lower() == m["cls"].lower()), None)
            g.race_num = next((k for k, v in w.races.items() if (v.get("Name") or "").lower() == m["race"].lower()), None)
            g.align = m["align"]
            why = None
            try:
                why = g.gate_why(fp, ex)
                if why == "blocked":
                    why = None                       # (the leader got past a block: it's the room's, not theirs)
                if not why and ex.kind == "item":
                    mm = ss.GATE_ITEM_RE.match(et)
                    num = int(mm.group(2)) if mm else 0
                    if num and (w.items.get(num) or {}).get("gettable", 1) and m["kit"].get(num, 0) <= 0:
                        why = f"needs {w.item_name(num)}"
                    elif num and mm.group(1).lower().startswith("ticket") and m["kit"].get(num, 0) > 0:
                        m["kit"][num] -= 1
                if not why and ex.kind == "toll":
                    mm = ss.TOLL_EX_RE.search(et)
                    t = int(mm.group(1)) if mm else 0
                    if m["cash"] < t:
                        why = f"toll {t}, has {m['cash']}"
                    else:
                        m["cash"] -= t
                if not why and (ex.kind == "text" or getattr(ex, "req", None)):
                    req = dict(getattr(ex, "req", None) or {})
                    req.pop("monster", None)
                    why = g.req_why(fp, req)
                    if not why and req.get("price"):
                        m["cash"] -= int(req["price"])
                if not why:
                    for st_ in w.carry_needs([(here, ex)]):
                        if st_ and not any(m["kit"].get(i, 0) > 0 for i in st_):
                            why = "carries none of " + " / ".join(w.item_name(i) for i in sorted(st_)[:3])
                            break
            finally:
                g.cls_num, g.race_num, g.align = saved
            if why:
                self.events.append(("left behind", n, here, f"{ex.dir} {why}"))
                continue
            if ex.kind == "trap":
                mm = ss.TRAP_EX_RE.search(et)
                if mm and int(mm.group(1)) >= m["hp"]:
                    self.events.append(("trap could kill", n, here, f"{ex.dir} up to {mm.group(1)} vs {m['hp']} hp"))
            try:
                dmg = w.room_damage(ex.to, have=[k for k, q in m["kit"].items() if q > 0])
            except Exception:
                dmg = 0
            if dmg and dmg >= m["hp"]:
                self.events.append(("room could kill", n, here,
                                    f"{ex.dir} -> {ex.to[0]}/{ex.to[1]} up to {dmg} vs {m['hp']} hp"))
        if getattr(ex, "chance", False) or "(Chance)" in et:
            self.events.append(("chance jump", "party", here, f"{ex.dir} {getattr(ex, 'text_command', '') or ''}".strip()))
        if landed is not None and tuple(landed) != tuple(ex.to):
            self.events.append(("teleported", "party", here, f"{ex.dir} -> {landed[0]}/{landed[1]}"))


class _PartyReader:
    """The server's view of what the bot types: lines meant for the pretend followers are answered here."""
    def __init__(self, reader, writer, sim, party):
        self.r, self.wr, self.sim, self.party = reader, writer, sim, party

    def _say(self, lines):
        p = self.sim.players[-1]
        txt = "\n".join(lines) + "\n" + self.sim.prompt(p)
        self.wr.write(txt.replace("\n", "\r\n").replace("\r\r", "\r").encode("cp437", "replace"), raw=True)

    async def readline(self):
        while True:
            data = await self.r.readline()
            if not data:
                return data
            cmd = data.decode("cp437", "replace").strip("\r\n").strip()
            low = cmd.lower()
            fp, p = self.party, (self.sim.players[-1] if self.sim.players else None)
            if p is None:
                return data
            m = re.match(r"^/(\w+)\s+(.*)$", cmd)
            if m and fp.find(m.group(1)):
                self._say(fp.telepath(fp.find(m.group(1)), m.group(2)))
                continue
            if low in ("par", "party"):
                self._say(fp.party_rows(p))
                continue
            m = re.match(r"^invite (\w+)$", low)
            if m and fp.find(m.group(1)):
                self._say([f"{fp.find(m.group(1))} started to follow you."])
                continue
            m = re.match(r"^give (.+?) to (\w+)$", low)
            if m and fp.find(m.group(2)):
                self._say(fp.give(p, m.group(1), fp.find(m.group(2))))
                continue
            m = re.match(r"^(?:l|look) (\w+)$", low)
            if low.startswith(".") or (m and fp.find(m.group(1))):
                fp.sent.append(("party", cmd))
                self._say([])
                continue
            return data


class _PartyWriter:
    """Room shows: the followers in "Also here" (always right behind you)."""
    ALSO = re.compile(r"Also here: ")

    def __init__(self, writer, party):
        self.wr, self.party = writer, party

    def write(self, b, raw=False):
        if not raw and self.party.members:
            t = b.decode("cp437", "replace")
            if "Obvious exits:" in t and "very dark" not in t:
                names = ", ".join(self.party.members)
                if self.ALSO.search(t):
                    t = self.ALSO.sub(f"Also here: {names}, ", t, count=1)
                else:
                    t = re.sub(r"((?:\x1b\[[\d;]*m)*Obvious exits:)",
                               lambda mm: f"\x1b[35mAlso here: {names}.\x1b[0m\r\n" + mm.group(1), t, count=1)
                b = t.encode("cp437", "replace")
        self.wr.write(b)

    def __getattr__(self, k):
        return getattr(self.wr, k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all", help="fixed / towns / kingsport / random / labelled / all")
    ap.add_argument("--walks", type=int, default=30)
    ap.add_argument("--target", default="", help="--mode to: the room every walk goes to, e.g. 6/994")
    ap.add_argument("--starts", default="banks,towns",
                    help="--mode to: starting rooms (map/room, comma separated; 'banks' = every bank, 'towns' = the "
                         "Rooms.md towns' first rooms)")
    ap.add_argument("--repeat", type=int, default=1, help="--mode to: walk each start this many times")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--level", type=int, default=55)
    ap.add_argument("--port", type=int, default=2450)
    ap.add_argument("--tag", default="")
    ap.add_argument("--kit", default="golden idol,rope and grapple",
                    help="items carried at the start of each walk; 'keyring' adds every key / item an exit needs")
    ap.add_argument("--cash", type=int, default=5000000, help="copper at the start of each walk")
    ap.add_argument("--abil", default="", help="quest abilities, e.g. 134=9,204=1")
    ap.add_argument("--strength", type=int, default=75)
    ap.add_argument("--cls", default="Mage")
    ap.add_argument("--move-delay", type=float, default=0.0, help="seconds per room on the practice server (real pace)")
    ap.add_argument("--bash-rate", type=float, default=0.35, help="practice server: chance a bash opens a door")
    ap.add_argument("--search-rate", type=float, default=0.5, help="practice server: chance a search finds an exit")
    ap.add_argument("--party", default="",
                    help="followers to pretend to lead: 'Name:lvl=30,hp=250,str=80,pick=0,cls=Warrior,race=Dwarf,"
                         "align=Neutral,kit=golden idol+log raft,abil=134.8,sync=1,cash=500;Name2:...' (sync=0: "
                         "MegaMUD, no party sync / @flags); a bare 'Name,Name2' = members like you")
    ap.add_argument("--party-random", type=int, default=0,
                    help="this many followers, their level / HP / kit / class / race / alignment rolled each walk")
    ap.add_argument("--outdir", default=os.environ.get("REALM_WALK_OUT") or os.path.join(ROOT, "tests"),
                    help="where realm_walk_<tag>.json goes")
    ap.add_argument("--picklocks", type=int, default=0)
    ap.add_argument("--dark", type=int, default=None, help="rooms with MME light at or below this are dark")
    ap.add_argument("--light", default="", help="the character's light command (auto-light on), e.g. 'light torch'")
    ap.add_argument("--combat", type=int, default=0, help="1 = auto-combat on (fights what is in the way)")
    ap.add_argument("--only", default="", help="walks whose label has this text")
    ap.add_argument("--skip", type=int, default=0, help="skip the first N picked walks")
    ap.add_argument("--max-secs", type=int, default=900)
    ap.add_argument("--merge", action="store_true", help="write the report from tests/realm_walk_<tag>*.json")
    ap.add_argument("--out", default=REPORT, help="--merge: the report file")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.merge:
        return merge(a.tag, a.out)
    tag = a.tag or f"{a.mode}{a.seed}L{a.level}"
    os.environ.setdefault("MUDPILOT_NO_RECORD", "1")
    if not os.environ.get("MUDPILOT_DATA_DIR"):
        os.environ["MUDPILOT_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "mudpilot_realm_walk", tag)
    os.makedirs(os.environ["MUDPILOT_DATA_DIR"], exist_ok=True)
    import asyncio
    from mudpilot import simserver, config
    from mudpilot.session import Session
    from mudpilot.worlddb import WorldDB
    from mudpilot.ansi import plain

    real = WorldDB(DB)                       # the practice realm's own map: never touched by the bot
    from mudpilot import board_fixes
    kit_names = [k.strip() for k in a.kit.split(",") if k.strip()]
    kit = [int((real.item_names.get(k.lower()) or {}).get("num") or 0) for k in kit_names if k != "keyring"]
    kit = [k for k in kit if k]
    if "keyring" in kit_names:
        for r_ in real.rooms.values():
            for ex in r_.exits.values():
                need = real.exit_need(ex)
                if need and need[0] in real.items and need[0] not in kit:
                    kit.append(need[0])
    abil = {int(x.split("=")[0]): int(x.split("=")[1]) for x in a.abil.split(",") if "=" in x}
    if a.mode == "to":
        tgt = tuple(int(x) for x in a.target.split("/"))
        starts = []
        for s_ in a.starts.split(","):
            s_ = s_.strip()
            if s_ == "banks":
                starts += sorted(k for k, r in real.rooms.items() if r.name.startswith("Bank of"))
            elif "/" in s_:
                starts.append(tuple(int(x) for x in s_.split("/")))
        walks = [{"cat": "to", "label": f"{rname(real, st_)} -> {rname(real, tgt)}", "start": st_, "target": tgt}
                 for _ in range(max(1, a.repeat)) for st_ in starts if st_ in real.rooms and st_ != tgt]
    else:
        walks = pick_walks(real, a.mode, a.walks, a.seed, a.level, kit)
    if a.only:
        walks = [x for x in walks if a.only.lower() in x["label"].lower()]
    walks = walks[a.skip:]
    if a.mode not in ("fixed", "to"):
        walks = walks[:a.walks]
    if a.list:
        for x in walks:
            print(x["cat"], rname(real, x["start"]), "→", rname(real, x["target"]), x["label"])
        return 0
    print(f"[{tag}] {len(walks)} walks, level {a.level}, kit {kit_names} ({len(kit)} items), cash {a.cash}, "
          f"abil {abil}", flush=True)
    timed = list(board_fixes.TIMED_DOORS)
    sim = simserver.Sim(real, seed=a.seed, mob_rate=0, start=walks[0]["start"] if walks else (1, 1),
                        gates={"kit": kit, "level": a.level, "cls": a.cls, "race": "Human", "align": "Good",
                               "timed": timed, "seed": a.seed, "cash": a.cash, "abil": abil,
                               "strength": a.strength, "picklocks": a.picklocks, "dark_at": a.dark,
                               "move_delay": a.move_delay, "bash_rate": a.bash_rate,
                               "search_rate": a.search_rate})
    g = sim.gates
    party = None
    if a.party or a.party_random:
        spec = a.party if ":" in a.party else ";".join(f"{n.strip()}:" for n in a.party.split(",") if n.strip())
        party = FakeParty(real, spec, a.party_random, a.seed, a.level, sim)
        _cross = g.cross

        def cross(p, ex, out):
            here = tuple(p.room)
            ok_ = _cross(p, ex, out)
            if ok_ and sim.players and p is sim.players[-1]:
                party.follow(g, here, ex, tuple(p.room))
            return ok_
        g.cross = cross
        _room_cmd = g.room_command

        def room_command(p, low, out):
            # a room command run from its textblock ('jump east' off the rooftops) moves you without cross()
            here = tuple(p.room)
            rc = _room_cmd(p, low, out)
            if rc == "moved" and sim.players and p is sim.players[-1]:
                r_ = real.room(here)
                ex = next((e for e in (r_.exits.values() if r_ else ()) if e.accepts(low)), None)
                if ex is not None:
                    party.follow(g, here, ex, tuple(p.room))
            return rc
        g.room_command = room_command
        _ask = g.ask

        def ask(p, parts, out):
            # 'ask barmaid adventure': a monster's talk block moves you, without cross() either
            here = tuple(p.room)
            ok_ = _ask(p, parts, out)
            if tuple(p.room) != here and sim.players and p is sim.players[-1]:
                r_ = real.room(here)
                ex = next((e for e in (r_.exits.values() if r_ else ()) if e.accepts(" ".join(parts))), None)
                if ex is not None:
                    party.follow(g, here, ex, tuple(p.room))
            return ok_
        g.ask = ask
        print(f"[{tag}] party: {party.describe()}", flush=True)

    def serve(r, w_):
        if party is None:
            return simserver.handle(sim, r, w_)
        pw = _PartyWriter(w_, party)
        party.writer, party.loop = pw, asyncio.get_running_loop()
        return simserver.handle(sim, _PartyReader(r, pw, sim, party), pw)

    up = {}

    def run_server():
        async def go():
            try:
                srv = await asyncio.start_server(serve, "127.0.0.1", a.port)
            except OSError as ex:
                up["err"] = ex
                return
            up["ok"] = True
            async with srv:
                await srv.serve_forever()
        asyncio.run(go())
    threading.Thread(target=run_server, daemon=True).start()
    for _ in range(100):
        if up:
            break
        time.sleep(0.05)
    if not up.get("ok"):
        print(f"[{tag}] practice server didn't start on port {a.port}: {up.get('err')}", flush=True)
        os._exit(2)
    st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
    st.host, st.port, st.username = "127.0.0.1", a.port, "Tester"
    st.my_name = "Tester"
    st.auto_reconnect = False; st.auto_combat = bool(a.combat); st.char_level = a.level
    st.char_class, st.char_race, st.char_alignment = a.cls, "Human", "Good"
    if a.light:
        st.auto_light, st.light_cmd = True, a.light
    s = Session(st, world_path=DB); s.password = "x"; s._no_log_file = True
    s.on_alert = lambda m: None
    s.on_no_route = lambda m: None
    seq = []
    _ol = s.on_line
    s.on_line = lambda segs: (seq.append(("<", plain(segs), None)), _ol(segs))
    _o = s.send
    s.send = lambda c, from_bot=False: (seq.append((">", c, sim.players[-1].room if sim.players else None)),
                                        _o(c, from_bot))[1]
    s.connect()

    def run(secs, until=None, each=None):
        end = time.time() + secs
        while time.time() < end:
            s.poll()
            if each:
                each()
            if until and until():
                return True
            time.sleep(0.02)
        return False
    run(8, lambda: s.state.room is not None and s._entered)
    s.state.level = a.level
    if party is not None:
        s.party_sim = party
        s.sim_prompt = lambda: sim.prompt(sim.players[-1])
        party_setup(s, party, run, first=True)
        print(f"[{tag}] party sync: {s.partysync.info()} levels {s.partysync.levels()}", flush=True)
    os.makedirs(a.outdir, exist_ok=True)
    out_json = os.path.join(a.outdir, f"realm_walk_{tag}.json")
    results = []
    for i, wk in enumerate(walks):
        try:
            res = walk_one(s, sim, g, real, wk, seq, run, a)
        except Exception:
            res = {**wk, "ok": False, "issues": [("harness", traceback.format_exc(limit=5))], "secs": 0}
        res["level"] = a.level
        res["tag"] = tag
        results.append(res)
        json.dump(results, open(out_json, "w", encoding="utf-8"), default=list, indent=0)
        iss = res.get("issues") or []
        print(f"[{tag} {i + 1:3d}/{len(walks)}] {'ok   ' if res.get('ok') else 'FAIL '} {rname(real, wk['start'])} → "
              f"{rname(real, wk['target'])} [{wk['label'][:46]}] {res.get('walked', 0)}/{res.get('planned', '-')} rooms "
              f"{res.get('secs')} s" + (f"  — {iss[0][0]}: {str(iss[0][1])[:150]}" if iss else ""), flush=True)
    print(f"[{tag}] done: {sum(1 for r in results if r.get('ok'))}/{len(results)} ok → {out_json}", flush=True)
    os._exit(0)


def party_setup(s, party, run, first=False):
    """A walk's start with --party: the followers as they are this walk (rolled again with --party-random), in
    'par', in Game Data -> Players, and their MudPilots telling theirs again; nothing the leader learned about their
    kit / flags last walk carries over."""
    if not first:
        party.reset()
    b = s.bot
    pd = s.players.data
    for n, m in party.members.items():
        rec = pd.get(n.lower()) or {"name": n, "surname": "", "relationship": "Unknown", "class": "", "race": "",
                                    "gang": "", "level": 0, "last_seen": 0, "last_online": 0}
        rec.update({"name": n, "class": m["cls"], "race": m["race"], "alignment": m["align"], "level": m["lvl"],
                    "last_seen": time.time()})
        pd[n.lower()] = rec
    for sub, attr in (("partyflags", "known"), ("partyflags", "_asked"), ("errands", "known_have"),
                      ("errands", "_rounds")):
        d = getattr(getattr(b, sub, None), attr, None)
        if isinstance(d, dict):
            d.clear()
    b.__dict__.pop("_way_memo", None)
    s.send("par")
    run(3, lambda: all(n in (s.state.party or {}) for n in party.members))
    if first:
        run(6, lambda: all(n.lower() in {k.lower() for k in s.partysync.info()}
                           for n, m in party.members.items() if m["sync"]))
    else:
        # their (new) stats, as their MudPilots would tell a change
        lines = [f"{n} telepaths: {party.me_line(n)}" for n, m in party.members.items() if m["sync"]]
        for ln in lines:
            # (one at a time, a prompt after each, the way the game shows a telepath)
            txt = ("\r\n" + ln + "\r\n" + s.sim_prompt()).encode("cp437", "replace")
            party.loop.call_soon_threadsafe(party.writer.write, txt, True)
            run(1)
    missing = [n for n in party.members if n not in (s.state.party or {})]
    if missing:
        s.log(f"[harness] party: {missing} not in state.party after 'par'")
    party.events, party.sent = [], []


def walk_one(s, sim, g, w, wk, seq, run, a):
    b = s.bot
    start, target = tuple(wk["start"]), tuple(wk["target"])
    res = {**wk, "issues": [], "notes": [], "ok": False}
    try:
        b.stop("Stopped by you"); b.errands.cancel(); b.drop_parked()
    except Exception:
        pass
    run(0.5)
    if not s.telnet.connected:
        # hung up last walk (HP below the hang-up line, …): back in, as a fresh login
        res["notes"].append("reconnected (the last walk ended hung up)")
        s.connect()
        run(10, lambda: s.telnet.connected and s._entered and s.state.room is not None)
        s.state.level = a.level
    s.settings.auto_combat = bool(a.combat)          # (an errand turns it on for a monster's drop)
    party = getattr(s, "party_sim", None)
    pl = sim.players[-1]
    pl.room = start; pl.combat = None; pl.resting = False
    g.setup(pl)
    if getattr(b, "_boat", None):
        b._boat = None                               # (teleported off a boat the last walk was on)
    b.pilot.done.clear()                             # (and levers pulled on the last walk don't count here)
    if s.state.in_combat:
        # the last walk ended mid-fight and the teleport here never said '*Combat Off*': a fresh start
        s.state.in_combat = False
        res["notes"].append("cleared a fight left over from the last walk")
    bw = s.world
    for attr in ("failed_edges", "walls"):
        if getattr(bw, attr, None):
            getattr(bw, attr).clear()
    bw.forget_routes()
    s.state.candidates = [start]
    s.send("")
    run(4, lambda: s.state.room == start)
    if s.state.room != start:
        s.send("pro")                                # a look-alike start: the board's room number
        run(4, lambda: s.state.room == start)
    s.send("i")
    run(2)
    if s.state.room != start:
        res["issues"].append(("setup", f"bot thinks it's in {rname(w, s.state.room) if s.state.room else None}"))
        return res
    if party is not None:
        party_setup(s, party, run)
        res["party"] = party.describe()
        res["party_seen"] = {"levels": s.partysync.levels(), "hp": b._weakest_hp(),
                             "door_power": b.door_power(True), "carry": sorted(b.party_carry()), "peers": {n: (p.get("lvl"), p.get("me")) for n, p in s.partysync.peers.items()}}
    ev0, sq0, lg0 = len(g.events), len(seq), len(s.logs)
    g.events.clear(); ev0 = 0
    trail, t0 = [start], time.time()
    last_move = [time.time()]
    stuck = [0.0, None]
    drift = {"since": None, "events": [], "room": None}

    def each():
        now = time.time()
        if pl.room != trail[-1]:
            trail.append(pl.room)
            last_move[0] = now
        elif b.walking or b.errands.active:
            if now - last_move[0] > stuck[0]:
                stuck[0], stuck[1] = now - last_move[0], pl.room
        br = s.state.room
        if br and tuple(br) != pl.room:
            if drift["since"] is None:
                drift["since"], drift["room"] = now, (tuple(br), pl.room)
            elif now - drift["since"] > 8 and (not drift["events"] or drift["events"][-1][2] != drift["since"]):
                drift["events"].append((drift["room"][0], drift["room"][1], drift["since"]))
        else:
            drift["since"] = None
    try:
        tg0 = time.time()
        if os.environ.get("REALM_WALK_PROFILE"):
            import cProfile, pstats, io
            pr = cProfile.Profile()
            ok = pr.runcall(b.goto, target)
            sio = io.StringIO()
            pstats.Stats(pr, stream=sio).sort_stats("cumulative").print_stats(35)
            print(sio.getvalue()[:9000], flush=True)
        else:
            ok = b.goto(target)
        res["plan_secs"] = round(time.time() - tg0, 1)
    except Exception:
        res["issues"].append(("exception", traceback.format_exc(limit=6)))
        return res
    res["planned"] = len(b.path.steps) if (b.path and b.walking) else None
    plan_rooms = [st_.room for st_ in (b.path.steps if b.path else [])] + ([b.path.steps[-1].dest] if b.path and b.path.steps else [])
    if not ok and not b.walking and not b.parked():
        res["issues"].append(("no route", b.no_route_msg or b.status))
        res["secs"] = 0
        res["log"] = s.logs[lg0:][-8:]
        return res
    # (with a party: the '@have' / '@flags' rounds before setting off hold the walk too)
    busy = lambda: (b.walking or b.errands.active or b.parked() or getattr(b, "_await_inv", None)
                    or getattr(b.errands, "asking", None) or getattr(b.errands, "asking_key", None)
                    or getattr(getattr(b, "partyflags", None), "asking", None) or getattr(b, "_planning", False))
    limit = a.max_secs
    monster = [False]
    stall = [False]
    dropped = set()

    def until():
        hold = getattr(b, "_boss_hold", None)
        if hold:
            # stopped before a boss (stop_before_boss, Alt+R to go in): noted, then in we go, as Dan would — with the
            # boss gone from its room on the practice server (someone else killed it), so a walk isn't decided by a
            # fight it wasn't asked to have (the aged earth dragon on the way to Undermountain)
            res["notes"].append(f"stopped before a boss at {rname(w, pl.room)} — went in (Alt+R)")
            res["boss_stops"] = res.get("boss_stops", 0) + 1
            g._residents_idx()
            for boss_ in w.bosses_by_room().get(tuple(hold), []):
                num_ = next((n_ for n_, x in w.monsters.items() if x is boss_), None)
                for rm_ in [tuple(k_) for k_ in boss_.get("spawn_rooms") or []]:
                    # (one of it in the realm, in any of its rooms: gone from all of them)
                    if boss_ in sim.mobs.get(rm_, []):
                        sim.mobs[rm_].remove(boss_)
                    if num_ is not None:
                        g._dead[(rm_, num_)] = time.time() + 3600
            b.resume_boss()
        er = b.errands.active
        cur = ((er or {}).get("todo") or [None])[0] if er else None     # (an errand whose todo is done: [])
        if isinstance(cur, dict) and cur.get("kind") == "monster" and b.walking is False and \
                tuple(pl.room) == tuple(cur.get("room") or ()) and cur.get("num") not in dropped:
            # at the monster the errand wants a drop from: the practice server doesn't run lairs or drop
            # chances, so the harness hands the item over (as if it dropped and was picked up) and the walk goes on
            dropped.add(cur.get("num"))
            monster[0] = cur
            g.give(pl, cur["num"])
            res["notes"].append(f"monster drop handed over: {w.item_name(cur['num'])} ({cur.get('what')}) at "
                                f"{rname(w, pl.room)}")
            s.send("i")
        if time.time() - last_move[0] > 150 and not pl.combat:
            stall[0] = True                          # nothing moved for 2 1/2 minutes: give it up
            return True
        if res["planned"] is None and b.walking and b.path:
            res["planned"] = len(b.path.steps)
        return time.time() - t0 > 2 and not busy()
    done = run(limit, until, each)
    res["secs"] = round(time.time() - t0, 1)
    res["walked"] = len(trail) - 1
    res["trail"] = [list(k) for k in trail]
    res["end"] = list(pl.room)
    logs = s.logs[lg0:]
    res["log"] = logs[-14:]
    tg = f"Go to {target[0]}/{target[1]} "
    wp = [int(m.group(1)) for l in logs for m in [re.search(r"Walking path: (?:Go to \S+ .*?)\((\d+) steps\)", l)]
          if m and tg in l]
    if wp:
        res["planned"] = wp[0]                       # the first plan to the target (errand legs aside)
    res["errand_legs"] = sum(1 for l in logs if "Walking path: Go to" in l and tg not in l)
    legs = {}
    for l in logs:
        m = re.search(r"Walking path: Go to (\d+/\d+) .*?\((\d+) steps\)", l)
        if m and m.group(1) not in legs:
            legs[m.group(1)] = int(m.group(2))       # each leg's first plan (an errand's detour, then the target)
    res["planned_total"] = sum(legs.values()) or res.get("planned")
    ev = g.events[ev0:]
    res["sim"] = collections.Counter(e[0] for e in ev).most_common()
    res["sim_events"] = [(e[0], list(e[1]) if e[1] else None, str(e[2])) for e in ev[:40]]
    goal = target
    if monster[0]:
        res["monster_drops"] = sorted(dropped)
    if stall[0]:
        res["issues"].append(("stalled", f"no move for 150 s at {rname(w, pl.room)} (status: {b.status})"))
        b.stop("Stopped by you"); b.errands.cancel()
    elif not done:
        res["issues"].append(("timeout", f"still going after {limit:.0f} s at {rname(w, pl.room)} (status: {b.status})"))
        b.stop("Stopped by you"); b.errands.cancel()
    elif pl.room != goal:
        nr = next((l for l in reversed(logs) if "Not walking" in l or "No walkable" in l or "Stopped" in l), "")
        res["issues"].append(("stopped short", f"at {rname(w, pl.room)} (status: {b.status}) {nr[:300]}"))
    res["ok"] = pl.room == goal and not res["issues"]
    if stuck[0] > 25:
        res["issues"].append(("stuck", f"no move for {stuck[0]:.0f} s at {rname(w, stuck[1])}"))
    cnt = collections.Counter(trail)
    k, c = max(cnt.items(), key=lambda x: x[1])
    if c >= 5:
        res["issues"].append(("loop", f"{rname(w, k)} {c} times"))
    if drift["events"]:
        th, re_, _t = drift["events"][0]
        res["issues"].append(("tracking", f"{len(drift['events'])}x — thought {rname(w, th)}, really {rname(w, re_)}"))
    planned = res.get("planned_total") or res["planned"] or 0
    if planned and res["walked"] > planned * 1.4 + 12:
        res["issues"].append(("wrong way", f"walked {res['walked']} rooms for {planned} planned"
                              + (f" (errand legs included)" if res["errand_legs"] else "")))
    detours = [l for l in logs if "going round" in l or "Went round" in l or "way round" in l]
    if detours:
        res["notes"].append(f"{len(detours)} detours: {detours[0][:200]}")
    res["detours"] = len(detours)
    # first room off the plan
    if plan_rooms:
        on = set(plan_rooms)
        off = next((i for i, k in enumerate(trail) if k not in on), None)
        if off is not None:
            res["off_plan"] = [list(trail[off - 1]), list(trail[off])]
    if party is not None:
        pe = list(party.events)
        res["party_events"] = [(e[0], e[1], list(e[2]) if e[2] else None, e[3]) for e in pe[:60]]
        res["party_sent"] = [f"{n}: {m}" for n, m in party.sent[:60]]
        left = [e for e in pe if e[0] == "left behind"]
        if left:
            e = left[0]
            res["issues"].insert(0, ("follower left behind", f"{len(left)}x - {e[1]} at {rname(w, e[2])}: {e[3]}"))
            res["ok"] = False
        for kind in ("trap could kill", "room could kill"):
            bad_ = [e for e in pe if e[0] == kind]
            if bad_:
                res["issues"].append((kind, f"{len(bad_)}x - {bad_[0][1]} at {rname(w, bad_[0][2])}: {bad_[0][3]}"))
        jumps = [e for e in pe if e[0] == "chance jump"]
        if jumps:
            res["party_jumps"] = len(jumps)
            res["notes"].append(f"{len(jumps)} chance jump(s) with the party: " +
                                "; ".join(f"{rname(w, e[2])} {e[3]}" for e in jumps[:3]))
        asks = [m for n, m in party.sent if n != "party" and not m.lower().startswith("@mpsync")]
        if asks:
            res["notes"].append(f"party asks: {len(asks)} - " + "; ".join(asks[:6]))
    blocked = [e for e in ev if e[0] in ("blocked", "walked into a closed door", "command refused", "bash failed",
                                         "pick failed", "search missed", "chance failed", "would have died")]
    if blocked:
        res["notes"].append("sim: " + "; ".join(f"{e[0]} {e[1][0]}/{e[1][1]} {e[2]}" for e in blocked[:5]))
    if a.debug:
        for x in seq[-80:]:
            print("   ", x[0], (x[1] or "")[:110], x[2] if x[2] else "")
        for l in logs[-30:]:
            print("    LOG", l[:200])
    return res


def merge(prefix="", out=REPORT):
    import glob
    from mudpilot.worlddb import WorldDB
    w = WorldDB(DB)
    rows = []
    for f in sorted(glob.glob(os.path.join(os.environ.get("REALM_WALK_OUT") or os.path.join(ROOT, "tests"),
                                           f"realm_walk_{prefix}*.json"))):
        try:
            rows += json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            pass
    bad = [r for r in rows if not r.get("ok")]
    kinds = collections.Counter(i[0] for r in rows for i in r.get("issues") or [])
    first = collections.Counter((r.get("issues") or [("ok",)])[0][0] for r in rows)
    L = [f"MudPilot realm walk sweep (practice server, honest gates) — {time.strftime('%Y-%m-%d %H:%M')}",
         f"{len(rows)} walks: {len(rows) - len(bad)} reached the target (some flagged below: loop / stuck / wrong way), "
         f"{len(bad)} didn't",
         "first issue per walk: " + ", ".join(f"{k} {n}" for k, n in first.most_common()),
         "all issues: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()),
         "rooms walked / planned: " + f"{sum(r.get('walked') or 0 for r in rows)} / "
         f"{sum(r.get('planned') or 0 for r in rows)}", ""]
    by_cat = collections.defaultdict(list)
    for r in rows:
        by_cat[(r.get("cat"), r.get("level"))].append(r)
    for (c, lv), rs in sorted(by_cat.items(), key=lambda x: str(x[0])):
        L.append(f"  {c} level {lv}: {sum(1 for r in rs if r.get('ok'))}/{len(rs)} ok")
    L.append("")
    L.append("Problems:")
    for r in bad:
        L.append(f"- [{r.get('tag')}] {rname(w, r['start'])} → {rname(w, r['target'])}  [{r.get('label')}]  "
                 f"walked {r.get('walked')}/{r.get('planned')} in {r.get('secs')} s, ended {rname(w, r.get('end')) if r.get('end') else '-'}")
        for k, what in r.get("issues") or []:
            L.append(f"    {k}: {str(what)[:400]}")
        for n_ in r.get("notes") or []:
            L.append(f"    note: {n_[:300]}")
        if r.get("off_plan"):
            L.append(f"    left the plan: {rname(w, r['off_plan'][0])} → {rname(w, r['off_plan'][1])}")
        for l in (r.get("log") or [])[-6:]:
            L.append(f"    log: {l[:220]}")
    L.append("")
    L.append("All walks:")
    for r in rows:
        L.append(f"  {'ok' if r.get('ok') else '!!'} L{r.get('level')} {rname(w, r['start'])[:38]:<38} → "
                 f"{rname(w, r['target'])[:38]:<38} {str(r.get('walked')):>4}/{str(r.get('planned')):<4} "
                 f"{str(r.get('secs')):>6} s  {r.get('cat')}" + (f"  ({r['issues'][0][0]})" if r.get("issues") else ""))
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:12 + len(by_cat)]))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)
