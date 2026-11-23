"""Get what a path needs before walking it — like MegaMUD going after Thrag's keys.

A path (or Go to) needs keys and items its doors ask for in MME: "(Key: 475)", "(Item: 191)".
When one is missing, MudPilot looks up where MME says it comes from:
  - dropped by a monster  → walk to its room, kill it (it keeps coming back if it respawns),
                            pick the item up
  - sold in a shop        → walk there and buy it
and when everything is in hand it walks the path it was asked to. Quest/scripted items
(MME "Textblock") can't be fetched automatically; MudPilot says so and stops.
Tolls: the gate wants cash. If you're short MudPilot says how much and stops.
"""
from __future__ import annotations

import re
import time
from types import SimpleNamespace

WAIT_MINS = 20            # give up on a monster that hasn't dropped the item after this long in its room
SHOP_TRIES = 3
ASK_SECS = 15             # how long the party gets to answer '@have log raft'
GIVE_TRIES = 2            # a member too heavy to take the raft: this many more tries after they drop coins
ROOM_SECS = 8             # ...giving them this long to drop and re-read their pack
NO_RE = re.compile(r"\b(?:no|not|none|nope|don'?t|doesn'?t)\b", re.I)
# what the game says back to the leader's buy-and-hand-over (Evolution, 2026-11-09: 'You cannot afford wooden
# skiff.' then 'You don't have wooden skiff to give!' — and it logged 'Gave a wooden skiff to Revolution')
AFFORD_RE = re.compile(r"\byou cannot afford\b", re.I)
NOGIVE_RE = re.compile(r"\byou don'?t have (.+?) to give\b", re.I)
GAVE_RE = re.compile(r"\byou give (.+?) to (\w+)", re.I)


class Errands:
    def __init__(self, bot):
        self.bot = bot
        self.active = None       # {"todo": [step], "then": (mp, loop), "started": t}
        self.asking_key = None   # '@have <key>' to the party before going after a key (_from_party)
        self.asking = None       # party '@have' round: {"mp", "loop", "picks", "q": {member: [num]}, "ans", "t"}
        self.party_boats = False  # the party carries rafts (a raft @have round): '@stash' on the next loop
        self._rounds = {}        # path title -> (rounds asked, when)
        self.giving_up = None    # (why, mp, after, target): a walk that won't go — bot.give_up on the next tick
        self.known_have = {}     # (member lower, item) -> (has it, when): '@have' answers, for routing a party (0.8.190)

    @property
    def s(self):
        return self.bot.s

    # ------------------------------------------------------------ planning
    def source_for(self, num, toward=None, extra=(), frm=None, near=None, without=()):
        """Best way to get item #num: {"kind": shop / ask / monster, "room", "what", maybe "cmd" / "summon"} or None.
        Every room of every source counts (MME's raft shop is both Arlysia's docks and Silvermere's pier — taking
        the first sent a raft run 236 rooms to Arlysia); with a destination, by the whole detour there and on.
        extra: items fetched before this one (the gate key's statue is past the bloodstone orb's door).
        without: items still to be fetched — never assumed in hand on the way to this one."""
        w = self.s.world
        g = w.gear.get(num) if getattr(w, "gear", None) else None
        here = frm or self.bot.st.room
        cands = []                                   # (kind, room, what, extra)
        for m in re.finditer(r"(Shop|Monster) #(\d+)(?:\(([\d.]+)%\))?", (g or {}).get("obtained", "")):
            kind, n, pct = m.group(1), int(m.group(2)), m.group(3)
            if kind == "Shop":
                sh = w.shops.get(n, {})
                empty = getattr(self, "_empty_shops", None) or {}
                for rm in sh.get("rooms") or []:
                    if time.time() - empty.get((num, tuple(rm)), 0) < 1800:
                        continue                     # out of stock a moment ago (0.8.201, bug hunt)
                    cands.append(("shop", tuple(rm), f"sold: {sh.get('name') or f'shop #{n}'} ({rm[0]}/{rm[1]})", {}))
            else:
                mon = w.monsters.get(n) or {}
                what = f"drop: {mon.get('name') or f'monster #{n}'}" + (f" {pct}%" if pct else "")
                tsf = getattr(self.bot, "_fight_too_strong", None)
                est = tsf([mon], here=False) if (mon and callable(tsf)) else 0
                if isinstance(est, (int, float)) and est > 0:
                    # (0.8.223, m149 N1: an L10 sent to kill Sheriff Lionheart for the jail key — not a fight to plan)
                    self.__dict__.setdefault("too_strong", {})[num] = (mon.get("name") or f"monster #{n}", est)
                    continue
                for rm in mon.get("spawn_rooms") or []:
                    cands.append(("monster", tuple(rm), what, {}))
                if not mon.get("spawn_rooms") and not (getattr(w, "summons", {}) or {}).get(n):
                    # no spawn room in MME, but lairs that spawn it (dark cultists: the regen rooms round the
                    # Black House door) — the nearest few; else hunt it where we need its drop
                    ref = tuple(near or here or (0, 0))
                    lairs = sorted(w.lair_rooms(n), key=lambda k: (k[0] != ref[0], abs(k[1] - ref[1])))[:6]
                    for rm in lairs:
                        cands.append(("monster", tuple(rm), what + " (its lair)", {}))
                    if not lairs and near:
                        cands.append(("monster", tuple(near), what + " (wanders)", {"roam": True}))
                for rm, trig in (getattr(w, "summons", {}) or {}).get(n, []):
                    # nothing lives there until you call it up: 'touch statue' at the Black Steel Gate (gate key)
                    cands.append(("monster", tuple(rm), what, {"summon": trig}))
        stash = getattr(self.bot, "stash", None)
        if stash and num in stash.stashed() and stash.room():
            # our own, hidden at the loop (Dan, 2026-11-05: reuse them rather than rebuying — they're heavy)
            r = stash.room()
            cands.append(("stash", r, f"stashed at {r[0]}/{r[1]}", {}))
        for a in (getattr(w, "npc_gives", {}) or {}).get(num, []):
            if not w.req_ok(SimpleNamespace(req=a["req"]), self.bot.st.level or None, self.bot.held_items()):
                continue
            cands.append(("ask", tuple(a["room"]), f"'{a['cmd']}' at {a['room'][0]}/{a['room'][1]}", {"cmd": a["cmd"]}))
        if not cands:
            return None
        lvl = self.bot.route_level()
        avoid = self.bot.avoid_set() or None          # a fetch never walks you through an avoided area
        if avoid and here and tuple(here) in avoid:
            # already inside it: walk out the short way, as a Go to does (Dan, 2026-11-09: Miserable in the
            # Negative Power Plane — 'no known place to get' the golden lion key the floating key drops)
            avoid = None
        have = set(self.bot.held_items() or set()) | set(extra)
        best = self._rank(cands, here, toward, num, lvl, avoid, have)
        if best is None and here and (self.s.settings.auto_get_items or self.s.settings.bash_key_doors):
            # nothing in reach with the keys you carry — you're behind a door you pick (Evolution, 2026-11-03, in the
            # guardian golem's rooms: 'no known place to get' a log raft): as a Go to plans it, through those doors
            best = self._rank(cands, here, toward, num, lvl, avoid,
                              (set(self.bot.every_item()) | set(extra)) - set(without) - {num})
            # (never the item being fetched itself: the way to the rope shop went down Storm Mountain's rope exits, the red
            #  rock key's lair is behind its own key door — m1617 #3)
        if not best:
            return None
        return {"num": num, "kind": best[1], "room": best[2], "what": best[3], "dist": best[0][1], **best[4]}

    def _rank(self, cands, here, toward, num, lvl, avoid, have):
        """The nearest source by the walk there and on (shops and asks before monsters): (score, kind, room, what,
        extra) or None if none can be reached."""
        w = self.s.world
        best = None
        # two searches for all of them (how far each is from here, and on to where we're going), not two each
        d_here = w.dist_map(tuple(here), level=lvl, have=have, avoid=avoid) if here and len(cands) > 1 else None
        d_on = w.dist_map(tuple(toward), level=lvl, have=set(have) | {num}, avoid=avoid, reverse=True) \
            if here and toward and len(cands) > 1 else None
        for kind, room, what, extra in cands:
            dist = 0
            if here and d_here is not None:
                if room not in d_here:
                    continue
                dist = d_here[room]
                if toward and tuple(toward) != room:
                    dist += d_on.get(room, 500) if d_on is not None else 500
            elif here:
                rt = w.route(here, room, level=lvl, have=have, avoid=avoid)
                if rt is None:
                    continue
                dist = len(rt)
                if toward and tuple(toward) != room:
                    on = w.route(room, tuple(toward), level=lvl, have=set(have) | {num}, avoid=avoid)
                    dist += len(on) if on is not None else 500
            # no fighting first (shop / ask), then by the walk
            score = (0 if kind in ("shop", "ask", "stash") else 1, dist)
            if kind == "stash":
                score = (0, max(0, dist - 60))       # yours already: worth a longer walk than a shop
            if best is None or score < best[0]:
                best = (score, kind, room, what, extra)
        return best

    COPPER = (1, 10, 100, 10000, 1000000)         # copper, silver, gold, platinum, runic

    def _bank_for(self, cur, a) -> bool:
        """Bought nothing after a few tries — short of cash (Dan, 2026-11-03: the boatman's log raft is 15 gold;
        no cash, get it at the Bank of Godfrey next to the pier). To the nearest bank for plenty (shops mark the
        price up — 3 gold in MME, 15 at the boatman), then the walk starts over and buys it. False = no bank run."""
        w, st = self.s.world, self.bot.st
        it = w.items.get(cur["num"]) or {}
        base = int(it.get("price") or 0) * self.COPPER[min(int(it.get("currency") or 0), 4)]
        need = max(base * 10, 2000)
        cash = st.wealth or 0
        mp, loop = a["then"]
        if mp is None:
            return False
        # (0.8.201, realm walk: read where the Go to was going BEFORE withdraw_for — its own goto(bank) sets
        #  _goto_target to the bank, so the walk back went to the bank and the real target was forgotten. The
        #  errand's own target first: _goto_target is only the leg to the shop by now)
        tgt = a.get("target") or getattr(self.bot, "_goto_target", None)
        if not self.s.trips.withdraw_for(mp, loop, max(need - cash, need // 2), why=f"a {w.item_name(cur['num'])}"):
            return False
        t = self.s.trips.trip
        if t is not None:
            t["recheck"] = True                    # back from the bank through the item check: it buys it this time
            if mp.title.startswith("Go to ") and tgt and not isinstance(tgt, (set, frozenset)):
                t["goto"] = tuple(tgt)
        self.active = None                         # the bank first
        return True

    def _toward(self, mp):
        """Where the walk goes after the errand: the Go to's target, else the path's first room."""
        t = getattr(self.bot, "_goto_target", None) if mp.title.startswith("Go to ") else None
        if t:
            return tuple(t)
        return next((x.room for x in mp.steps if x.room), None)

    def _detour_note(self, todo, mp):
        """Dan: say where it's going and why — 'Detouring to the Pier (1/1813) for a log raft, then on to …'."""
        w = self.s.world
        bits = []
        for t in todo:
            if t["kind"] == "party":
                bits.append(f"asking the party for the {w.item_name(t['num'])}")
                continue
            if t["kind"] in ("farm", "recipe"):
                bits.append(t["what"])
                continue
            r = w.room(t["room"])
            where = f"{r.name if r else 'there'} ({t['room'][0]}/{t['room'][1]})"
            bits.append(f"{where} for {'a ' if t['kind'] == 'shop' else 'the '}{w.item_name(t['num'])}"
                        + (f" ({t['cmd']})" if t.get("cmd") else "") + (f" for {t['for']}" if t.get("for") else ""))
        dest = self._toward(mp)
        dr = w.room(dest) if dest else None
        on = mp.title[6:] if mp.title.startswith("Go to ") else f"'{mp.title}'"
        if dr and not mp.title.startswith("Go to "):
            on += f" (starts {dest[0]}/{dest[1]})"
        if all(t["kind"] in ("party", "farm", "recipe") for t in todo):
            return ", ".join(bits).capitalize() + f" — then on to {on}"
        return "Detouring to " + ", then ".join(bits) + f" — then on to {on}"

    def _one_source(self, num) -> bool:
        """Sold somewhere, or dropped by a single monster that has its own room (a boss)."""
        w = self.s.world
        ob = ((getattr(w, "gear", None) or {}).get(num) or {}).get("obtained") or ""
        if re.search(r"Shop #\d+", ob):
            return True
        mons = re.findall(r"Monster #(\d+)", ob)
        return len(mons) == 1 and bool((w.monsters.get(int(mons[0])) or {}).get("spawn_rooms"))

    def _recipe_todo(self, num, have):
        """The dragon key's way: its parts first (anything you don't carry — the party is asked for each, then their
        droppers' rooms are farmed, looping, Dan: "looping the couple rooms by the prismatic dragon including its
        room is the best way"), then the room's commands in order."""
        w = self.s.world
        rc = w.recipe_for(num) if hasattr(w, "recipe_for") else None
        if not rc:
            return None
        out = []
        me = (self.s.settings.my_name or "").lower()
        if [n for n in (self.s.state.party or {}) if n.lower() != me]:
            # someone may already have the key itself: ask before farming
            out.append({"num": num, "kind": "party", "soft": True, "key": num, "room": None,
                        "what": "from the party", "dist": 0})
        # one boss drops it (the dark bishop's cross key, the wizard's runed key, the assassin's skull key) or a
        # shop sells it: go and get it like any other key, nearest first — farming is for the fangs' many droppers
        direct, at = [], tuple(self.bot.st.room) if self.bot.st.room else None
        left = [n for n in rc["needs"] if n not in have and self._one_source(n)]
        while left:
            srcs = [(s_["dist"], i, n, s_) for i, n in enumerate(left)
                    for s_ in [self.source_for(n, None, set(direct_n["num"] for direct_n in direct), at)] if s_]
            if not srcs:
                break
            _d, _i, n, s_ = min(srcs)
            direct.append(dict(s_, key=num))
            left.remove(n)
            at = s_["room"]
        got_ = {t["num"] for t in direct}
        for need in rc["needs"]:
            ob_ = ((getattr(w, "gear", None) or {}).get(need) or {}).get("obtained") or ""
            if need not in have and need not in got_ and not re.search(r"Monster #\d+", ob_):
                # nothing drops it and no source we use sells it (the parchment deeds, MME 'Shop(nogen) #300'): it
                # can't be farmed — 0.8.221, bug hunt: Go to the Iron House Room stood 'farming' in 6/569 for 45 min
                return []
        rooms = []
        for need in [n for n in rc["needs"] if n not in got_]:
            g = (getattr(w, "gear", None) or {}).get(need) or {}
            for m in re.finditer(r"Monster #(\d+)", g.get("obtained") or ""):
                mon = w.monsters.get(int(m.group(1))) or {}
                # a boss: its own room; the rest: their lairs (the dragon serpents' six round the prismatic dragon)
                for rm in list(mon.get("spawn_rooms") or []) or list(w.lair_rooms(int(m.group(1)))):
                    if tuple(rm) not in rooms and w.room(tuple(rm)):
                        rooms.append(tuple(rm))
        boss = next((tuple(rm) for n_ in rc["needs"] if n_ not in got_
                     for m in re.finditer(r"Monster #(\d+)", ((getattr(w, "gear", None) or {}).get(n_) or {}).get("obtained") or "")
                     for rm in ((w.monsters.get(int(m.group(1))) or {}).get("spawn_rooms") or [])), None)
        if boss and hasattr(w, "dist_map"):
            # the few rooms round the boss that drops them all (Dan: "the couple rooms by the prismatic dragon,
            # including its room") — not every lair on the map
            near_ = w.dist_map(boss) or {}
            close = [k for k in rooms if near_.get(k, 99) <= 6]
            if len(close) >= 2:
                rooms = close
        if rooms:
            # walk them as a loop: nearest next, not in list order
            dm = w.dist_map(rooms[0]) if hasattr(w, "dist_map") else {}
            tour, left = [rooms[0]], rooms[1:]
            while left:
                d_ = w.dist_map(tour[-1]) if hasattr(w, "dist_map") else dm
                nxt = min(left, key=lambda k: (d_ or {}).get(k, 10 ** 6))
                tour.append(nxt)
                left.remove(nxt)
            rooms = tour
        out += direct
        for need in rc["needs"]:
            if need not in have and need not in got_:
                out.append({"num": need, "kind": "farm", "key": num, "room": rooms[0] if rooms else rc["room"], "rooms": rooms,
                            "what": f"farm the {w.item_name(need)} ({len(rooms)} rooms)", "dist": 0})
        names = ", ".join(w.item_name(n) for n in rc["needs"])
        at_ = f"{w.room(rc['room']).name} ({rc['room'][0]}/{rc['room'][1]})"
        # (0.8.201, realm walk: a recipe with no parts — the golden idol comes from the room's commands — read
        #  "put the  in at …")
        what_ = f"put the {names} in at {at_}" if names else f"get it at {at_}"
        out.append({"num": num, "kind": "recipe", "key": None, "room": rc["room"], "cmds": rc["cmds"], "needs": rc["needs"],
                    "nomonsters": rc["nomonsters"], "dist": 0, "what": what_})
        return out

    def _hp_wall_why(self, nums, near=None):
        """Why an item can't be fetched when it's only the HP wall (a trap or room that can do your whole max HP —
        0.8.222): "can't fetch X: the way to it crosses …". None when that isn't it."""
        w, b = self.s.world, self.bot
        c = getattr(w, "char", None)
        hp = int((c or {}).get("max_hp") or 0)
        here = b.st.room
        if hp <= 0 or not here or not nums:
            return None
        from .worlddb import DIR_WORDS
        for num in nums:
            c["max_hp"] = 0                          # (no max HP known = no HP wall: is that all that's in the way?)
            try:
                src = self.source_for(num, None, set(), None, near=near)
                rt = w.route(tuple(here), src["room"], level=b.route_level(),
                             have=(set(b.every_item()) - {num})) if src else None
            except Exception:
                src = rt = None
            finally:
                c["max_hp"] = hp
            cur = tuple(here)
            for ex in rt or []:
                dmg = w.hp_wall(ex)
                if dmg:
                    return (f"can't fetch {w.item_name(num)}: the way to it ({src['what']}) crosses the "
                            f"{DIR_WORDS.get(ex.dir, ex.dir).lower()} exit of {cur[0]}/{cur[1]}, which can do {dmg} "
                            f"damage — your whole max HP ({hp})")
                cur = tuple(ex.to)
        return None

    def plan(self, mp, loop, missing: list, near=None) -> tuple[bool, str]:
        w = self.s.world
        todo, bad = [], []
        self.too_strong = {}                          # (item droppers source_for left out this time: too strong)
        have_ = self.bot.held_items() or set()
        for num in list(missing):
            if self.source_for(num, None, set(), None, near=near):
                continue
            rt = self._recipe_todo(num, have_)
            if rt:
                todo += rt                            # (the parts and the slot: done in order, before the rest)
                missing = [n for n in missing if n != num]
        toward = self._toward(mp)
        got, left, at = set(), list(missing), None
        while left:
            # nearest next (from where the last one was got), so the run doesn't zig-zag; one that's only
            # reachable with another's item (the statue past the orb's door) waits its turn
            # (the every-key fallback mustn't count on the others still to get: 0.8.189, realm walk sweep — the gate
            #  key's statue went first, through the orb's door, before the orb)
            srcs = [(n, self.source_for(n, None, got, at, near=near, without=set(left) - {n})) for n in left]
            ok_ = [(x[1]["dist"], i, x) for i, x in enumerate(srcs) if x[1]]
            if not ok_:
                bad += [w.item_name(n) for n in left]
                break
            num = min(ok_)[2][0]
            # standing in what the item keeps off (the desert without a waterskin): the nearest one, not one on the
            # way (Dan, 2026-11-04: the General Store at Khazarad, 204 steps, over Nekojin's 50 or so)
            hurting = num in w.spell_items(self.s.world.room_spells.get(self.s.state.room))                 if self.s.state.room and (getattr(self.s.world, "room_spells", {}) or {}).get(self.s.state.room) else False
            src = self.source_for(num, toward if len(left) == 1 and not hurting else None, got, at, near=near,
                                  without=set(left) - {num})
            todo.append(src)
            got.add(num)
            left.remove(num)
            at = src["room"]
        me = (self.s.settings.my_name or "").lower()
        if bad and [n for n in (self.s.state.party or {}) if n.lower() != me]:
            # nowhere we know of to get it — but someone in the party may carry one (Dan, 2026-11-01: Buddy's Go to
            # the Iceforge stopped dead at "can't fetch dragon key" without asking Revolution or Evolution)
            for n in [n for n in missing if w.item_name(n) in bad]:
                todo.insert(0, {"num": n, "kind": "party", "room": None, "what": "from the party", "dist": 0})   # (asked first: partyA #2)
            bad = []
        if bad:
            # an NPC carries it (the moldy key: the sleazy shopkeeper, 8/486 — m58 #2): say who; MudPilot never kills
            # an NPC for it (Dan, 0.8.223)
            npc = [(w.item_name(n), w.npc_holder(n)) for n in missing if w.item_name(n) in bad
                   and hasattr(w, "npc_holder") and w.npc_holder(n)]
            rest = [b_ for b_ in bad if b_ not in {x[0] for x in npc}]
            ts_ = getattr(self, "too_strong", None) or {}
            strong = [(w.item_name(n), ts_[n]) for n in missing if n in ts_ and w.item_name(n) in rest]
            rest = [b_ for b_ in rest if b_ not in {x[0] for x in strong}]
            parts = ([", ".join(f"{who} has the {nm}" for nm, who in npc) + " — MudPilot won't kill an NPC for it; "
                      "get it yourself, then Go to again"] if npc else []) + \
                ([", ".join(f"the {nm} drops off the {m_}, too strong for you (~{e_:.0f} damage to you)"
                            for nm, (m_, e_) in strong) + " — not going to fight it for that"] if strong else []) + \
                ([self._hp_wall_why([n for n in missing if w.item_name(n) in rest], near) or
                  f"can't fetch {', '.join(rest)} automatically (quest item, or no known source you can walk to)"]
                 if rest else [])
            # (the HP wall alone in the way — a trap / room that can do your whole max HP: say that, not "quest item";
            #  m14c M14C-3, the large brass key past 14/8542 W's 400-damage trap at 390 HP)
            return False, "; ".join(parts)
        outer = self.active
        if outer and outer.get("todo") and self._is_leg(outer, mp):
            # (0.8.201, realm walk: the errand's own walk to its item room needs something too — the bloodstone orb
            #  on the way to the bracelet, a key door on the way to the black star key. Replacing `active` lost the
            #  first item and the real Go to: it got the orb, "on to 'Go to 8/689'", arrived and stood there. Now the
            #  new items go in front and the errand keeps its own then/target)
            have_nums = {t_["num"] for t_ in outer["todo"]}
            todo = [t_ for t_ in todo if t_["num"] not in have_nums]
            if not todo:
                return False, "it's the item this errand is already getting"
            outer["todo"] = todo + outer["todo"]
            outer["at"], outer["tries"] = None, 0
            names = "; ".join(f"{w.item_name(t['num'])} ({t['what']})" for t in todo)
            self.bot.log(f"'{mp.title}' needs {names} too — getting {'it' if len(todo) == 1 else 'them'} first, then "
                         f"on with the errand")
            return True, ""
        self.active = {"todo": todo, "then": (mp, loop), "started": time.time(), "at": None, "tries": 0,
                       "after": self.bot.after_goto, "target": getattr(self.bot, "_goto_target", None)
                       if mp.title.startswith("Go to ") else None}
        names = "; ".join(f"{w.item_name(t['num'])} ({t['what']})" for t in todo)
        self.bot.log(f"'{mp.title}' needs {names} — getting {'it' if len(todo) == 1 else 'them'} first")
        note = self._detour_note(todo, mp)
        self.bot.log(note)
        self.active["note"] = note                    # @status tells whoever asks (Dan: not to the whole gang)
        return True, ""

    def _is_leg(self, a, mp) -> bool:
        """Is `mp` this errand's own walk to the room of its current item (the Go to errands.tick started)?"""
        if not mp.title.startswith("Go to "):
            return False
        tgt = getattr(self.bot, "_goto_target", None)
        if not tgt or isinstance(tgt, (set, frozenset)):
            return False
        cur = a["todo"][0]
        rooms = {tuple(cur["room"])} if cur.get("room") else set()
        rooms |= {tuple(r_) for r_ in cur.get("rooms") or []}
        return tuple(tgt) in rooms

    def wanted(self) -> set:
        """Item names to pick up while on an errand (lower case)."""
        if not self.active:
            return set()
        w = self.s.world
        out = {w.item_name(t["num"]).lower() for t in self.active["todo"]}
        for t in self.active["todo"]:
            out |= {w.item_name(n).lower() for n in t.get("needs") or []}
        return out

    def _unhunt(self):
        if self.active and self.active.get("hunt") and self.bot.hunt_target is self.active["hunt"]:
            self.bot.hunt_target = None

    # ------------------------------------------------------------ the party's own rafts / idols
    def party_check(self, mp, loop, carry, leg=False) -> bool:
        """Leading a party down a path where each walker needs their own item (a raft for the river, the golden
        idol): ask everyone '@have <item>' and buy one for whoever hasn't. True = holding the walk for it.
        leg: `mp` is an errand's own walk (party3 #2) — what's bought goes in front of the errand, which carries on,
        and a give-up names the errand's walk, not the leg."""
        bot, w = self.bot, self.s.world
        me = (self.s.settings.my_name or "").lower()
        members = [n for n in (self.s.state.party or {}) if n.lower() != me]
        if not members or not self.s.comeback.leading():
            return False
        n, t = self._rounds.get(mp.title, (0, 0))
        if time.time() - t > 600:
            n = 0
        picks = [bot.carry_pick(c, own=False) for c in carry]   # (the members' own: they buy, not our stash)
        sets = [frozenset(c) for c in carry]
        ea = self.active if (leg and self.active) else None
        g_mp = (ea.get("then") or (mp, loop))[0] if ea else mp
        g_after = ea.get("after") if ea else bot.after_goto
        g_target = ea.get("target") if ea else (getattr(bot, "_goto_target", None) if mp.title.startswith("Go to ")
                                                else None)
        if n >= 2:
            # not 'walking on' without them (Evolution, 2026-11-09: to the Ancient Ruin with no rafts for the
            # party after two rounds of hand-overs that never happened): don't go, say why — a boss hunt or a Go to
            # off a loop goes back to the loop (next tick: start_path holds the walk when this returns True)
            what = "; ".join(" or ".join(w.item_name(i) for i in [p] + sorted(c - {p})) for p, c in zip(picks, sets))
            self.giving_up = (f"Not walking '{g_mp.title}': asked the party twice for {what} and someone still has "
                              f"none", g_mp, g_after, g_target)
            bot.status = "Not walking — the party is missing what the way needs"
            return True
        # (a round counts only once it comes back short — _asking_tick: a round everyone passed, or one you
        # stopped before the answers came in, isn't 'asked twice' (Dan, 2026-11-19: Pavilion of Hides, all three
        # said yes, Stop mid-ask, the next Go to refused without asking))
        # ask about everything that would do, not just the one we'd buy: Revolution wears the sunstone wristband
        # and got a waterskin bought for him (Dan, 2026-11-04)
        asks = list(picks) + sorted({i for c in sets for i in c} - set(picks))
        self.asking = {"mp": mp, "loop": loop, "picks": picks, "sets": sets, "t": time.time(), "ans": {},
                       "q": {m: list(asks) for m in members}, "after": g_after, "target": g_target,
                       "leg": ea is not None, "gmp": g_mp}
        names = "; ".join(" or ".join(w.item_name(i) for i in [p] + sorted(c - {p})) for p, c in zip(picks, sets))
        for m in members:
            for p in asks:
                bot.send(f"/{m} @have {w.item_name(p)}")
        bot.log(f"'{mp.title}' needs everyone to carry: {names} — asking {', '.join(members)} (@have)")
        bot.status = "Asking the party what they carry…"
        return True

    def note_line(self, text):
        """'Evolution cannot accept your offer.' — the raft we just handed over: they're too heavy for it."""
        a = self.active
        if not a or not a.get("todo"):
            return
        cur = a["todo"][0]
        t = text.strip()
        if cur.get("kind") != "shop":
            return
        if AFFORD_RE.search(t):
            if (cur.get("bought") and not cur.get("given")) or not cur.get("for"):
                cur["broke"] = True                   # 'You cannot afford log raft.' (our own buy too: 0.8.201)
            return
        if not cur.get("for") or not cur.get("given"):
            return
        if NOGIVE_RE.search(t):
            cur["nogive"] = True                      # "You don't have log raft to give!": the buy never happened
            return
        m = GAVE_RE.search(t)
        if m and m.group(2).lower() == cur["for"].lower():
            cur["gave_ok"] = True                     # 'You give log raft to Buddy.'
            return
        # (the prompt can come first on the same line: search, not match)
        if not cur.get("refused") and re.search(rf"\b{re.escape(cur['for'])}\b.*\bcannot (?:accept your offer|"
                                                r"carry)", t, re.I):
            cur["refused"] = True

    def have_answer(self, sender, msg) -> bool:
        """'{yes: log raft}' / '{no log raft}' back from a member we asked @have (MegaMUD or MudPilot)."""
        ak = getattr(self, "asking_key", None)
        if ak and any(m.lower() == sender.lower() for m in ak["members"]):
            body = msg.strip().strip("{}").strip()
            name = self.s.world.item_name(ak["num"]).lower()
            if name in body.lower() or re.match(r"(?:yes|no)\b", body, re.I):
                who = next(m for m in ak["members"] if m.lower() == sender.lower())
                ak["ans"][who] = not NO_RE.search(body)
                self.known_have[(who.lower(), ak["num"])] = (ak["ans"][who], time.time())
                return True
        a = self.asking
        if not a:
            return False
        who = next((m for m in a["q"] if m.lower() == sender.lower()), None)
        q = a["q"].get(who) if who else None
        if not q:
            return False
        w = self.s.world
        body = msg.strip().strip("{}").strip()
        num = next((n for n in q if w.item_name(n).lower() in body.lower()), None)
        if num is None:
            if not re.match(r"(?:yes|no)\b", body, re.I):
                return False                         # something else they said (a quest flag note)
            num = q[0]
        q.remove(num)
        a["ans"][(who, num)] = not NO_RE.search(body)
        self.known_have[(who.lower(), num)] = (a["ans"][(who, num)], time.time())
        return True

    def _asking_tick(self) -> bool:
        a, bot, w = self.asking, self.bot, self.s.world
        if any(a["q"].values()) and time.time() - a["t"] < ASK_SECS:
            bot.status = "Asking the party what they carry…"
            return True
        self.asking = None
        mp, loop = a["mp"], a["loop"]
        quiet = [m for m, q in a["q"].items() if q]
        sets = a.get("sets") or [frozenset([p]) for p in a["picks"]]
        if any(c & bot.stash.boats() for c in sets):
            self.party_boats = True              # they have rafts now (or get them bought): stashed on the loop
        short = [(m, p) for m in a["q"] for p, c in zip(a["picks"], sets)
                 if not any(a["ans"].get((m, i)) for i in c)]
        if not short:
            self._rounds.pop(mp.title, None)
            bot.log("Party items: everyone has " + "; ".join(" or ".join(w.item_name(i) for i in [p] + sorted(c - {p}))
                                                             for p, c in zip(a["picks"], sets)))
            # (asked before your own errand — the idol, party3 #4: plan the walk again, the errand comes next)
            if not a.get("recheck") and bot.partyflags.check(mp, loop):
                return True                      # (0.8.224 — wparty W2: 'checked' skipped the party's quest-flag check;
                                                 #  the pyramid walk left Revolution at the 12/1189 gate)
            bot.start_path(mp, loop, checked=not a.get("recheck"))
            return True
        n, t = self._rounds.get(mp.title, (0, 0))
        self._rounds[mp.title] = ((0 if time.time() - t > 600 else n) + 1, time.time())
        if quiet:
            bot.log(f"Party items: {', '.join(quiet)} didn't answer @have — getting them one anyway")
        todo, bad = [], []
        for m, p in short:
            src = self.source_for(p, self._toward(mp))
            if src and src["kind"] == "shop":
                todo.append({**src, "for": m})
            else:
                bad.append(f"{w.item_name(p)} for {m}")
        if bad:
            # not stood there idle (Evolution, 2026-11-09, 06:02: after the crimson mist, on the way back): a Go to
            # with a loop after goes back to it, a boss hunt is given up; nothing to go back to — stop and say why
            gmp = a.get("gmp") or mp
            bot.give_up(f"Not walking '{gmp.title}': the party needs {', '.join(bad)} — no shop we can get to sells "
                        f"it, get it by hand", gmp, a.get("after"), a.get("target"))
            return True
        outer = self.active
        if a.get("leg") and outer and outer.get("todo"):
            # an errand's own leg (party3 #2): buy theirs first, then on with the errand — it keeps its then / target
            outer["todo"] = todo + outer["todo"]
            outer["at"], outer["tries"] = None, 0
            bot.log("Party items: buying " + "; ".join(f"{w.item_name(t['num'])} for {t['for']} ({t['what']})"
                                                      for t in todo) + " — then on with the errand")
            bot.set_mode("auto")
            return True
        self.active = {"todo": todo, "then": (mp, loop), "started": time.time(), "at": None, "tries": 0,
                       "after": a["after"], "target": a["target"]}
        bot.log("Party items: buying " + "; ".join(f"{w.item_name(t['num'])} for {t['for']} ({t['what']})"
                                                  for t in todo))
        a_note = self._detour_note(todo, mp)
        bot.log(a_note)
        self.active["note"] = a_note
        bot.set_mode("auto")
        return True

    def _from_party(self, cur, now) -> bool:
        """Before going after a key: does someone in the party carry one? ('@have black star key' →
        '@do give black star key to Miserable'.) True = waiting on them."""
        bot, w = self.bot, self.s.world
        if cur.get("for") or cur.get("party_done") or cur["kind"] in ("shop", "recipe", "stash"):
            return False
        me = (self.s.settings.my_name or "").lower()
        members = [n for n in (self.s.state.party or {}) if n.lower() != me]
        if not members:
            return False
        name = w.item_name(cur["num"])
        pa = cur.setdefault("party", {"t": now, "ans": {}, "asked": False, "given": None})
        if not pa["asked"]:
            pa["asked"] = True
            self.asking_key = {"num": cur["num"], "ans": pa["ans"], "members": members}
            for m in members:
                bot.send(f"/{m} @have {name}")
            bot.log(f"Asking the party for a {name} first ({', '.join(members)})")
            bot.status = f"Asking the party for a {name}"
            return True
        yes = next((m for m, v in pa["ans"].items() if v), None)
        if yes and not pa["given"]:
            pa["given"] = now
            bot.send(f"/{yes} @do give {name} to {self.s.settings.my_name}")
            bot.log(f"{yes} has a {name} — asking them to hand it over")
            return True
        if pa["given"]:
            if now - pa["given"] < 15:
                if bot.ready("errand_inv_give", 5):
                    bot.send("i")
                return True
            cur["party_done"] = True              # didn't arrive: go and get one
            return False
        if now - pa["t"] < ASK_SECS and len(pa["ans"]) < len(self.asking_key.get("members", [])):
            bot.status = f"Asking the party for a {name}"
            return True
        cur["party_done"] = True
        self.asking_key = None
        bot.log(f"Nobody in the party has a {name} — going to get one")
        return False

    FARM_MINS = 45

    def _farm(self, cur, now) -> bool:
        """Loop the droppers' rooms, fighting whatever's there and picking up the parts (wanted() has them all),
        till this one's in the pack."""
        bot, st, w = self.bot, self.bot.st, self.s.world
        a = self.active
        cur.setdefault("t0", now)
        if now - cur["t0"] > self.FARM_MINS * 60:
            return self._give_up(f"Stopped: no {w.item_name(cur['num'])} after {self.FARM_MINS} min farming")
        cfg = self.s.settings
        if not cfg.auto_combat:
            cfg.auto_combat = True
            self.s.on_settings_changed()
        if st.in_combat or (st.view and st.view.monsters) or bot.walking:
            return False                              # fight it / loot it / let the walk go on
        if bot.ready("errand_inv", 20):
            bot.send("i")
        rooms = cur.get("rooms") or [cur["room"]]
        if not bot.ready("farm_step", 3):
            return True
        i = cur.get("i", -1)
        nxt = rooms[(i + 1) % len(rooms)] if st.room in rooms or i >= 0 else \
            min(rooms, key=lambda k: (k[0] != (st.room or k)[0], abs(k[1] - (st.room or k)[1])))
        cur["i"] = rooms.index(nxt)
        bot.status = f"Farming for the {w.item_name(cur['num'])} — {nxt[0]}/{nxt[1]} next"
        if st.room != nxt and not bot.goto(nxt):
            cur["i"] = cur["i"] + 1                   # can't get there: the next one
        return True

    def _recipe(self, cur, now) -> bool:
        """At the room: wait till it's clear (MME: 'nomonsters'), then the commands in order — the five fangs."""
        bot, st, w = self.bot, self.bot.st, self.s.world
        a = self.active
        if st.room != cur["room"]:
            if not bot.walking and bot.ready("errand_go", 5) and not bot.goto(cur["room"]):
                self._give_up(f"Stopped: no way to {w.room(cur['room']).name} for the {w.item_name(cur['num'])}")
            return True
        if st.in_combat or (cur.get("nomonsters") and st.view and st.view.monsters):
            bot.status = f"Clearing the room before the {w.item_name(cur['num'])}"
            return False                              # fight first: the slot only works with nobody else here
        have = bot.held_items() or set()
        missing = [n for n in cur["needs"] if n not in have] if cur.get("step", 0) == 0 else []
        if missing:
            return self._give_up(f"Stopped: need {', '.join(w.item_name(n) for n in missing)} for the "
                                 f"{w.item_name(cur['num'])}")
        k = cur.setdefault("step", 0)
        if k < len(cur["cmds"]):
            if bot.ready("recipe_step", 1.5):
                bot.send(cur["cmds"][k])
                cur["step"] = k + 1
                if k == 0:
                    bot.log(f"{', '.join(cur['cmds'])} — for the {w.item_name(cur['num'])}")
            bot.status = f"Making the {w.item_name(cur['num'])} ({k + 1}/{len(cur['cmds'])})"
            return True
        if not cur.get("checked"):
            cur["checked"] = now
            bot.send("i")
            return True
        if now - cur["checked"] > 8:
            self._give_up(f"Stopped: the {w.item_name(cur['num'])} didn't come (the commands went in at "
                          f"{w.room(cur['room']).name})")
        return True

    def _give_up(self, why):
        """The errand can't be done: the walk it was for doesn't go (bot.give_up: back to the loop if there is
        one, else stop with the reason)."""
        a = self.active or {}
        mp = (a.get("then") or (None, None))[0]
        self.bot.give_up(why, mp, a.get("after"), a.get("target"))
        return True

    def cancel(self, why=""):
        self.asking = None
        self.giving_up = None
        if self.active:
            self._unhunt()
            self.active = None
            if why:
                self.bot.log(why)

    # ------------------------------------------------------------ running
    def tick(self) -> bool:
        """Called when the bot isn't walking. True = took the tick."""
        if self.giving_up:
            g, self.giving_up = self.giving_up, None
            self.bot.give_up(*g)
            return True
        if self.asking:
            return self._asking_tick()
        a = self.active
        if not a:
            return False
        bot, st, w, cfg = self.bot, self.bot.st, self.s.world, self.s.settings
        now = time.time()
        have = bot.held_items() or set()
        if any(t.get("key") in have for t in a["todo"]):
            # the key turned up (the party handed one over, or it dropped): no farming or slot for it
            a["todo"] = [t for t in a["todo"] if t.get("key") not in have]
        while a["todo"] and not a["todo"][0].get("for") and a["todo"][0]["num"] in have and not (
                a["todo"][0]["kind"] == "stash" and (self.bot.stash.busy() or now - a["todo"][0].get("started", 0) < 6)):
            got = a["todo"].pop(0)
            bot.log(f"Got the {w.item_name(got['num'])}")
            a["at"], a["tries"] = None, 0
        if not a["todo"]:
            mp, loop = a["then"]
            self._unhunt()
            self.active = None
            bot.log(f"Have everything — on to '{mp.title}'")
            here = st.room
            if a.get("target"):                       # it was a Go to: route again, now with the keys
                bot.goto(a["target"], then=a.get("after"))
            elif mp.steps and mp.steps[0].room and here and not any(x.room == here for x in mp.steps):
                bot.goto(mp.steps[0].room, then=mp)
            else:
                bot.start_path(mp, loop)
            return True
        cur = a["todo"][0]
        if self._from_party(cur, now):
            return True
        if cur["kind"] == "farm":
            return self._farm(cur, now)
        if cur["kind"] == "recipe":
            return self._recipe(cur, now)
        if cur["kind"] == "party" and cur.get("soft"):
            a["todo"].pop(0)                          # nobody had it: on to making it
            a["at"], a["tries"] = None, 0
            return True
        if cur["kind"] == "party":
            # only the party could have had it, and nobody does
            mp, _loop = a["then"]
            name = w.item_name(cur["num"])
            return self._give_up(f"Not walking '{mp.title}': you need a {name} — nobody in the party has one, and "
                                 "there's no known place to get one (quest item?)")
        floor = " ".join(n for _q, n in (st.view.items if st.view else [])).lower()
        if w.item_name(cur["num"]).lower() in floor and not cur.get("for"):
            if bot.ready("errand_floor", 3):
                bot.send(f"get {w.item_name(cur['num'])}")      # lying right here (the black star key was)
                bot.send("i")
            return True
        if st.in_combat:
            return False
        if st.room != cur["room"]:
            if bot.ready("errand_go", 5):
                if not bot.goto(cur["room"]):
                    mp_ = a["then"][0]
                    self._give_up(f"Not walking '{getattr(mp_, 'title', '?')}': no way from here to "
                                  f"{cur['what']} for the {w.item_name(cur['num'])}")
                return True
            return False
        # in the room
        if a["at"] is None:
            a["at"] = now
        if cur["kind"] == "stash":
            # search, get it, and the party picks up theirs too (they're following, so they're here)
            stash = self.bot.stash
            if not cur.get("started"):
                if stash.get_here(tell_party=True):
                    cur["started"] = now
                    bot.status = f"Picking up the stashed {w.item_name(cur['num'])}"
                    return True
                cur["started"] = now                 # nothing recorded any more: buy one (below)
            if stash.busy():
                return True
            if now - cur["started"] < 6:
                return True                          # the party's '@unstash' too, before '@have' asks them
            if cur["num"] not in have:
                # gone (cleared, or taken): the shop after all
                mp, loop = a["then"]
                self.active = None
                bot.start_path(mp, loop)
                return True
            a["todo"].pop(0)
            a["at"], a["tries"] = None, 0
            return True
        if cur["kind"] == "shop" and cur.get("for"):
            # one for a party member: buy it, hand it over (they're following, so they're in the shop too)
            name = w.item_name(cur["num"])
            title = getattr(a["then"][0], "title", "?")
            if cur.get("broke"):
                # 'You cannot afford log raft.' — the bank (if there's one near and money in it), else don't go
                cur["broke"] = False
                if self._bank_for(cur, a):
                    bot.log(f"Can't afford a {name} for {cur['for']} — to the bank first")
                    return True
                return self._give_up(f"Not walking '{title}': can't afford a {name} for {cur['for']} (not enough "
                                     f"cash on you, and no bank run)")
            if not cur.get("bought"):
                if bot.ready("errand_buy", 3):
                    cur["bought"] = now
                    bot.send(f"buy {name}")
            elif not cur.get("given"):
                if now - cur["bought"] >= 2:
                    cur.update(given=now, refused=False, nogive=False, gave_ok=False)
                    bot.send(f"give {name} to {cur['for']}")
            elif cur.get("nogive"):
                # "You don't have log raft to give!": the buy didn't happen — buy again, a couple of times
                n = cur.get("rebuys", 0)
                if n >= SHOP_TRIES - 1:
                    return self._give_up(f"Not walking '{title}': couldn't buy a {name} for {cur['for']} (the game "
                                         f"says there's none to give)")
                cur.update(bought=None, given=None, nogive=False, rebuys=n + 1)
                bot.log(f"The {name} for {cur['for']} wasn't bought — buying it again")
            elif cur.get("refused"):
                # "Evolution cannot accept your offer.": too heavy — they drop coins (@makeroom), then again
                n = cur.get("regives", 0)
                if n >= GIVE_TRIES:
                    return self._give_up(f"Not walking '{title}': {cur['for']} can't carry the {name} — too heavy "
                                         f"even after dropping coins. Lighten their pack, then Rego")
                if not cur.get("room_asked"):
                    cur["room_asked"] = now
                    bot.send(f"/{cur['for']} @makeroom {name}")
                    bot.log(f"{cur['for']} couldn't take the {name} (too heavy) — asking them to drop coins for it")
                elif now - cur["room_asked"] >= ROOM_SECS:
                    cur.update(given=None, refused=False, room_asked=None, regives=n + 1)
            elif cur.get("gave_ok") or now - cur["given"] >= 3:
                bot.log(f"Gave a {name} to {cur['for']}" + ("" if cur.get("gave_ok") else
                                                           " (the game didn't say so — the @have round checks)"))
                a["todo"].pop(0)
                a["at"], a["tries"] = None, 0
                if not a["todo"]:
                    bot.send("i")
            return True
        if cur["kind"] == "ask":
            # 'ask commander orb' — the gnome commander hands over the bloodstone orb
            if bot.ready("errand_ask", 6):
                if a["tries"] >= SHOP_TRIES:
                    return self._give_up(f"Stopped: '{cur['cmd']}' didn't give the {w.item_name(cur['num'])}")
                a["tries"] += 1
                bot.send(cur["cmd"])
                bot.send("i")
            bot.status = f"Asking for the {w.item_name(cur['num'])}"
            return True
        if cur["kind"] == "shop":
            rc = self.s.remote
            nm = w.item_name(cur["num"])
            if rc.making_room():
                return True
            if not cur.get("roomed") and rc.needs_room(nm):
                cur["roomed"] = True
                bot.log(f"Too heavy to carry a {nm} — making room first (coins in the shop swapped, then dropped)")
                rc.make_room(nm, shop=True)
                return True
            if bot.ready("errand_buy", 6):
                if a["tries"] >= SHOP_TRIES:
                    # 0.8.201, bug hunt: only a bank run when it's money ("You cannot afford", or less cash than the
                    # price) — an empty shop withdrew 2,000+ copper, walked back, failed again, and the next lap
                    # sent us straight back. Out of stock: give up and leave that shop alone for 30 minutes
                    it_ = w.items.get(cur["num"]) or {}
                    base_ = int(it_.get("price") or 0) * self.COPPER[min(int(it_.get("currency") or 0), 4)]
                    st_ = bot.st
                    broke = cur.get("broke") or (st_.wealth is not None and st_.wealth < base_)
                    if broke and self._bank_for(cur, a):
                        return True
                    if not broke and cur.get("room"):
                        self._empty_shops = {**getattr(self, "_empty_shops", {}),
                                             (cur["num"], tuple(cur["room"])): now}
                        return self._give_up(f"Stopped: couldn't buy the {w.item_name(cur['num'])} — the shop seems "
                                             "to be out of them (not trying it again for 30 min)")
                    return self._give_up(f"Stopped: couldn't buy the {w.item_name(cur['num'])} (enough cash?)")
                a["tries"] += 1
                bot.send(f"buy {w.item_name(cur['num'])}")
                bot.send("i")
            return True
        # monster room: fight what's here (combat on) and pick the item up; re-read inventory now and then.
        # The monster that drops it is always fought, even if it's one you'd normally leave alone.
        if not bot.hunt_target:
            nm = re.sub(r"^drop:\s*|\s+[\d.]+%$", "", cur["what"]).strip().lower()
            mon = w.monster_names.get(nm)
            if mon:
                bot.hunt_target = a["hunt"] = mon
        if not cfg.auto_combat:
            cfg.auto_combat = True
            self.s.on_settings_changed()
            bot.log("Combat on — to get the item")
        if cur.get("summon") and bot.ready("errand_summon", 30):
            bot.send(cur["summon"])                  # 'touch statue': the obsidian statue comes out (gate key)
        if bot.ready("errand_inv", 20):
            bot.send("i")
        if now - a["at"] > WAIT_MINS * 60:
            return self._give_up(f"Stopped: no {w.item_name(cur['num'])} after {WAIT_MINS} min at {cur['what']}")
        bot.status = f"Waiting for {cur['what'].replace('drop: ', '')} — need its {w.item_name(cur['num'])}"
        return False
