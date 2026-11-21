"""Token routing (0.8.201, Dan): let Go to 'use' a teleport token you carry when it saves a lot of walking.

On the PVE realm there are no recall items, just the town tokens (token of Silvermere, of Rhudaur, of Khazarad…):
5 uses a day, a spell that takes a round, and only with no monsters in the room and not in combat. MME has the
whole story in the item: Ability 43 casts the token's spell, whose textblock reads

    nomonsters 3509:minlevel 25 3507:failroomitem 3391:price 200000 4146:…:cast 310:teleport 1813 1:…

so the landing room (1/1813, the Pier), the level it needs and the cash it wants come from the data. A token MME
has no landing room for can be given one by hand (Settings → route_token_dest: {"token of x": "map/room"}).

The rules:
  * Settings → Other → Routing → 'Use teleport tokens I carry…' (off by default), solo only — a token takes only
    you, a party would be left behind;
  * only a token you carry (the 'i' list), your level and cash allow, and that hasn't failed lately;
  * only when it saves at least route_token_min_save rooms (a use costs about TOKEN_ROOMS rooms: a spell round
    and the look where you land);
  * planned from the room you're in, used only with the room clear and out of combat, never in the same round
    as a spell; monsters there → walk instead;
  * it didn't take you anywhere (out of uses, a no-token room, short of cash…) → that token is left alone for
    FAIL_MINS and the Go to walks.
Only the new Go to walker (pilot.py) plans with tokens; loops and imported paths never do.
"""
from __future__ import annotations

import re
import time

from .megamud_files import Step

TOKEN_ROOMS = 5          # what one use costs, in rooms of walking (a spell round + the look where you land)
FAIL_MINS = 30           # a token that didn't work is left alone this long
BLOCK_SECS = 90          # monsters in the room: walk instead, and don't plan that token from here for this long
ROUND_SECS = 5.0         # a token is a spell: not in the same round as one you cast
RETRY_MAX = 2            # 'already cast this round'-type answers: try again this many times
# what the game says when a use doesn't go (MME keeps the messages out of its data, so these are the usual words)
FAIL_RE = re.compile(r"\b(?:you (?:can(?:no|')t|cannot|may not|are unable|must|don'?t have)|nothing happens|"
                     r"not (?:enough|while|here|now)|no (?:more )?(?:charges|uses)|too (?:many|soon)|"
                     r"has no effect|had no effect|is (?:drained|exhausted|depleted)|monsters? (?:here|nearby|present))",
                     re.I)
RETRY_RE = re.compile(r"\b(?:already|this round|wait (?:a|until)|still recovering)\b", re.I)


def token_table(w) -> dict:
    """{item number: {"name", "to": (map, room), "level", "price" (copper), "nomonsters"}} — every limited-use item
    whose spell teleports you to one room (not a random drop). Cached on the world."""
    gear = getattr(w, "gear", None) or {}
    c = getattr(w, "_token_table", None)
    if c is not None and c[0] is gear and c[1] == len(gear):
        return c[2]
    from . import mmetext
    out = {}
    tbs = getattr(w, "textblocks", None) or {}
    for num, g in gear.items():
        try:
            uses = int(g.get("UseCount") or 0)
        except (TypeError, ValueError):
            continue
        if not (1 < uses < 9999) or not g.get("name"):
            continue                                 # (a one-shot — the levitation potion — isn't a token)
        ab = g.get("abils") or {}
        sp = int(ab.get(43) or ab.get("43") or 0)
        spell = (getattr(w, "spells", None) or {}).get(sp) if sp else None
        if not spell:
            continue
        sab = {int(a[0]): a[1] for a in spell.get("abils") or [] if len(a) >= 2 and a[0] is not None}
        found = None
        if int(sab.get(148) or 0):
            for segs in mmetext.block_lines(tbs, int(sab[148])):
                if segs and mmetext.is_trigger(segs[0]):
                    continue
                for req, chance, to, _op in mmetext.run(tbs, w.spells, segs, 0):
                    if to and not chance and tuple(to) in w.rooms:
                        found = (tuple(to), req)
                        break
                if found:
                    break
        elif int(sab.get(140) or 0) and int(sab.get(141) or 0):
            found = ((int(sab[141]), int(sab[140])), mmetext.new_req())
        if not found or found[0] not in w.rooms:
            continue
        to, req = found
        out[int(num)] = {"name": g["name"], "to": to, "level": int(req.get("level") or 0),
                         "price": int(req.get("price") or 0), "nomonsters": bool(req.get("nomonsters")), "uses": uses}
    w._token_table = (gear, len(gear), out)
    return out


def parse_room(text):
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", str(text or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def router(bot) -> "TokenRouter":
    r = bot.__dict__.get("_token_router")
    if r is None:
        r = bot.__dict__["_token_router"] = TokenRouter(bot)
    return r


class TokenRouter:
    def __init__(self, bot):
        self.a = bot
        self.failed: dict = {}        # token item -> until (didn't work: out of uses, a no-token room, no cash…)
        self.blocked: dict = {}       # (token item, room) -> until (monsters there when it was its turn)
        self.sent = None              # {num, room, t, retries}: a use that went out, waiting for where it lands
        self.uses: dict = {}          # token item -> [when it took us somewhere] (5 a day)
        self.spent_inv: dict = {}     # token item -> the 'i' list it was used under (gone until 'i' shows it again)

    # ------------------------------------------------------------ what you carry
    def _names(self) -> set:
        from .gamestate import parse_item_list
        st = self.a.st
        out = set()
        for _q, n in parse_item_list(st.carrying or ""):
            n = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip().lower()
            if n:
                out.add(n)
        return out

    def carried(self) -> list:
        """[(item number or name, info)] the tokens you carry that know where they land."""
        a = self.a
        w = a.s.world
        tab = token_table(w)
        held = a.held_items() or set()
        out = [(n, tab[n]) for n in sorted(held) if n in tab]
        manual = getattr(a.cfg, "route_token_dest", None) or {}
        if manual:
            names = self._names()
            for nm, where in manual.items():
                to = parse_room(where)
                if not to or to not in w.rooms or (nm or "").strip().lower() not in names:
                    continue
                low = nm.strip().lower()
                num = next((n for n, it in w.items.items() if (it.get("name") or "").lower() == low), low)
                info = dict(tab.get(num) or {"name": nm.strip(), "level": 0, "price": 0, "nomonsters": True, "uses": 0})
                info["to"] = to                       # (yours wins: you've seen where it really lands)
                out = [x for x in out if x[0] != num] + [(num, info)]
        return out

    # ------------------------------------------------------------ may it go now / from here
    def _solo(self) -> bool:
        st, me = self.a.st, (self.a.cfg.my_name or "").lower()
        return not any(n.lower() != me for n in (st.party or {}))

    def room_clear(self) -> bool:
        st = self.a.st
        return not st.in_combat and not (st.view and st.view.monsters)

    def _settle(self):
        """A use that went out and a new room came in somewhere else: it worked — count it."""
        s, st = self.sent, self.a.st
        if not s or st.view_seq == s.get("seq") or not st.room or tuple(st.room) == s["room"]:
            return
        self.sent = None
        now = time.time()
        self.uses[s["num"]] = [t for t in self.uses.get(s["num"], []) if now - t < 86400] + [now]
        self.spent_inv[s["num"]] = getattr(st, "inv_seq", None)

    def spent(self, num, info) -> bool:
        """Used up as far as we know: its uses today are gone, or it was used and 'i' hasn't shown it since."""
        now = time.time()
        n = len([t for t in self.uses.get(num, []) if now - t < 86400])
        if info.get("uses") and n >= int(info["uses"]):
            return True
        return num in self.spent_inv and self.spent_inv[num] == getattr(self.a.st, "inv_seq", None)

    def usable(self, here) -> list:
        a, now = self.a, time.time()
        self._settle()
        if not getattr(a.cfg, "route_tokens", False) or not here or not self._solo():
            return []
        st = a.st
        lvl = st.level or a.cfg.char_level or 0
        cash = st.wealth
        out = []
        for num, info in self.carried():
            if self.failed.get(num, 0) > now or self.blocked.get((num, here), 0) > now:
                continue
            if info["to"] == tuple(here) or self.spent(num, info):
                continue
            if info.get("level") and lvl and lvl < info["level"]:
                continue
            if info.get("price") and (cash is None or cash < info["price"]):
                continue                             # it wants cash you haven't got (or we don't know yet)
            out.append((num, info))
        return out

    # ------------------------------------------------------------ planning
    def shortcut(self, here, target, walk):
        """(token, info, route on from where it lands) when a token beats walking `walk` (list of exits, or None
        = no walking way) by at least route_token_min_save rooms; else None."""
        a = self.a
        if not here or not target or isinstance(target, (set, frozenset)) or tuple(here) == tuple(target):
            return None
        toks = self.usable(here)
        if not toks or not self.room_clear():
            return None
        w = a.s.world
        save = max(1, int(getattr(a.cfg, "route_token_min_save", 40) or 40))
        walking = len(walk) if walk is not None else 1 << 30
        try:
            lvl = a.route_level()
        except Exception:
            lvl = None
        have = a.held_items() or set()
        try:
            avoid = a.avoid_for(target) or None
        except Exception:
            avoid = None
        best = None
        for num, info in toks:
            to = info["to"]
            rest = [] if to == tuple(target) else w.route(to, tuple(target), level=lvl, have=have, avoid=avoid)
            if rest is None:
                continue
            cost = len(rest) + TOKEN_ROOMS
            if walking - cost < save:
                continue
            if best is None or cost < best[0]:
                best = (cost, num, info, rest)
        if best is None:
            return None
        cost, num, info, rest = best
        if a.ready("token_plan_note", 30):
            r = w.room(info["to"])
            a.log(f"Go to: using the {info['name']} — lands at {r.name if r else '?'} ({info['to'][0]}/{info['to'][1]}), "
                  f"{len(rest)} rooms from there instead of "
                  + (f"{walking} rooms of walking" if walk is not None else "no walking way at all")
                  + (f" (it costs {info['price']:,} copper)" if info.get("price") else ""))
        return num, info, rest

    def step(self, here, num, info) -> Step:
        w = self.a.s.world
        r = w.room(here)
        s = Step(r.mega_hash if r else "", 0, f"use {info['name'].lower()}", [], tuple(here), tuple(info["to"]))
        s._token = num
        return s

    # ------------------------------------------------------------ using it
    def hold(self, step, here) -> str:
        """Before a token step goes out: '' = go; 'wait' = not this tick (a spell this round); 'walk' = monsters /
        a fight here — walk instead (that token not from here for a while)."""
        a, now = self.a, time.time()
        num = getattr(step, "_token", None)
        if num is None:
            return ""
        if not self.room_clear():
            self.blocked[(num, tuple(here))] = now + BLOCK_SECS
            who = ", ".join(sorted({sh for sh, _r in ((a.st.view.monsters if a.st.view else None) or [])}))[:60]
            a.log("Go to: not using the token here — " + (f"{who} in the room" if who else "in combat")
                  + " (it only works with the room clear); walking instead")
            return "walk"
        if now - (getattr(a, "_cast_sent_at", 0) or 0) < ROUND_SECS:
            a.status = "Waiting a round before using the token"
            return "wait"
        sent = self.sent
        if not sent or sent["num"] != num or sent["room"] != tuple(here) or now - sent["t"] > 60:
            self.sent = {"num": num, "room": tuple(here), "t": now, "retries": 0, "retry": False,
                         "seq": a.st.view_seq}
        else:
            sent["t"], sent["seq"] = now, a.st.view_seq
        return ""

    def no_move(self, step, here) -> str:
        """The token step didn't take us anywhere: 'retry' (the round was busy) or 'walk' (that token's out)."""
        num = getattr(step, "_token", None)
        sent = self.sent
        if sent and sent["num"] == num and sent.get("retry") and sent["retries"] < RETRY_MAX:
            sent["retries"] += 1
            sent["retry"] = False
            return "retry"
        self.fail(num, "it didn't take us anywhere")
        return "walk"

    def fail(self, num, why):
        if num is None:
            return
        first = self.failed.get(num, 0) <= time.time()
        self.failed[num] = time.time() + FAIL_MINS * 60
        self.sent = None
        if first:
            info = dict(self.carried()).get(num) or token_table(self.a.s.world).get(num) or {"name": str(num)}
            self.a.log(f"Go to: the {info['name']} didn't work ({why}) — walking; leaving it alone for {FAIL_MINS} min")
        try:
            self.a.s.world.forget_routes()
        except Exception:
            pass

    def note_line(self, text):
        """The game's answer to a token use that didn't go: fall back to walking at once (not after the step times
        out)."""
        s = self.sent
        if not s or time.time() - s["t"] > 6:
            return
        if self.a.st.view_seq != s.get("seq"):
            return                                   # a room came in: it went (or something else moved us)
        line = (text or "").strip()
        if not line or line.startswith("[") or ":" in line or len(line) > 160:
            return                                   # (a prompt, chat — 'Bob gossips: you can't…' — or a long line)
        if RETRY_RE.search(line):
            s["retry"] = True
        elif not FAIL_RE.search(line):
            return
        a = self.a
        a.st.pending.clear()
        a._expect_seq = None                         # the walk needn't wait out the step timeout for a room
        if not s["retry"]:
            self.fail(s["num"], f"'{line[:80]}'")
