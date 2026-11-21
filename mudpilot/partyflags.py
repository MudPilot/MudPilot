"""Leading the party somewhere a quest flag decides the way (Dan, 2026-11-04): the Great Pyramid's 4th-level arches
let you through at DaoLordQuest 1–7 or 9+, and throw you to a random room at 8. The route is worked out with your
flags — so before setting off, ask everyone '@flags 134' and, when someone's value wouldn't get through, don't go:
"Can't go to 12/2085: Revolution is on DaoLordQuest 8 (you're on 9) — 8 doesn't get through."
Party members who don't answer (MegaMUD) are left to it, as before."""
from __future__ import annotations

import re
import time

ASK_SECS = 12
KNOWN_SECS = 1800        # a member's answer counts for routing this long (a quest step done since: asked again)
# '{DaoLordQuest (134) = 8 - …}', or '{ability 127 = not set - …}' from someone who has never had the flag, so
# doesn't know its name (Evolution, 2026-11-21: those answers were missed and the party went to Jorah anyway)
ANSWER_RE = re.compile(r"(?:\((\d+)\)|\bability\s+(\d+))\s*=\s*(-?\d+|not set)", re.I)


def exit_flags(w, ex) -> set:
    """Quest flags (ability ids) this exit's way through depends on: a gate ('Ability: 134 w/value …'), or the
    spell it casts on you branching on one (the arches' 'in archway check')."""
    out = {int(m.group(1)) for m in w.ABIL_GATE_RE.finditer(ex.etype or "")}
    nums = [int(n) for n in re.findall(r"(?:pre|post)-(\d+)", ex.etype or "") if int(n)]
    if nums:
        from . import mmetext
        for n in nums:
            for req, _ch, _to, _op in mmetext.run(getattr(w, "textblocks", {}), w.spells, [f"cast {n}"], ex.to[0]):
                for key in ("abil", "abil_eq", "no_abil"):
                    out |= {int(a) for a, _v in req.get(key) or []}
    return out


def path_flags(w, mp) -> set:
    out = set()
    from .megamud_files import step_exit
    for st in mp.steps or []:
        ex = step_exit(w, st)                       # (0.8.201, walk check: room-command exits too)
        if ex is not None:
            out |= exit_flags(w, ex)
    return {a for a in out if a > 0}


class PartyFlags:
    def __init__(self, bot):
        self.bot = bot
        self.asking = None       # {"mp", "loop", "target", "ids", "q": {member: {ids}}, "ans": {(member, id): v}, "t"}
        self._asked = {}         # path title -> when (once in 10 minutes)
        self.known = {}          # member (lower case) -> {ability id: (value, 0 = not set; when)}

    def party_values(self, aid) -> list:
        """What the party members (not you) told us their flag #aid is — for the router: a quest gate has to let
        everyone through, like class and race gates. Members who haven't said are left out."""
        me = (self.s.settings.my_name or "").lower()
        now = time.time()
        out = []
        for n in (self.s.state.party or {}):
            got = self.known.get(n.lower(), {}).get(int(aid))
            if n.lower() != me and got and now - got[1] < KNOWN_SECS:
                out.append(got[0])
        return out

    def known_sig(self) -> tuple:
        now = time.time()
        return tuple(sorted((n, a, v) for n, d in self.known.items() for a, (v, t) in d.items()
                            if now - t < KNOWN_SECS))

    @property
    def s(self):
        return self.bot.s

    def check(self, mp, loop) -> bool:
        """Before leading the party down mp: True = holding it while the party is asked."""
        b, s = self.bot, self.s
        target = getattr(b, "_goto_target", None)
        me = (s.settings.my_name or "").lower()
        members = [n for n in (s.state.party or {}) if n.lower() != me]
        if not members or not target or not s.comeback.leading():
            return False
        if time.time() - self._asked.get(mp.title, 0) < 600:
            return False
        ids = sorted(path_flags(s.world, mp))
        if not ids:
            return False
        self._asked[mp.title] = time.time()
        self.asking = {"mp": mp, "loop": loop, "target": tuple(target), "ids": ids, "t": time.time(), "ans": {},
                       "q": {m: set(ids) for m in members}}
        for m in members:
            for a in ids:
                b.send(f"/{m} @flags {a}")
        # (0.8.208: "depends on quest flags" read like a refusal — Revolution stopped a walk that was about to go)
        b.log(f"'{mp.title}': a step on the way goes by quest flag ({', '.join(b.flag_name(a) for a in ids)}) — "
              f"asking {', '.join(members)} theirs first (a few seconds), then walking")
        b.status = "Checking the party's quest flags, then going…"
        return True

    def answer(self, sender, msg) -> bool:
        """'{DaoLordQuest (134) = 8 - next step: …}' back from someone we asked."""
        a = self.asking
        if not a:
            return False
        who = next((m for m in a["q"] if m.lower() == sender.lower()), None)
        if not who:
            return False
        got = False
        for aid1, aid2, v in ANSWER_RE.findall(msg):
            aid = int(aid1 or aid2)
            if aid in a["q"][who]:
                a["q"][who].discard(aid)
                val = None if v.lower() == "not set" else int(v)
                a["ans"][(who, aid)] = val
                self.known.setdefault(who.lower(), {})[aid] = (0 if val is None else val, time.time())
                got = True
        return got

    def tick(self) -> bool:
        a = self.asking
        if not a:
            return False
        if any(a["q"].values()) and time.time() - a["t"] < ASK_SECS:
            self.bot.status = "Checking the party's quest flags…"
            return True
        self.asking = None
        b, st = self.bot, self.s.state
        try:
            self.s.world.forget_routes()             # the answers are part of the route now (route_char)
        except Exception:
            pass
        stuck = []
        for (who, aid), v in a["ans"].items():
            mine = (st.abil_value(aid, "total") or (None,))[0]
            if v == mine:
                continue
            if not self._gets_through(a["target"], aid, v):
                stuck.append((who, aid, v, mine))
        if stuck:
            k = a["target"]
            r = self.s.world.room(k)
            where = f"{k[0]}/{k[1]} {r.name if r else ''}".strip()
            def val(v):
                return "no" if v is None else str(v)
            bits = [(f"{who} has no {b.flag_name(aid)}" if v is None else f"{who} is on {b.flag_name(aid)} {v}")
                    + f" (you're on {val(mine)})" for who, aid, v, mine in stuck]
            msg = f"Can't go to {where}: " + "; ".join(bits) + " — that doesn't get through"
            b.stop(msg)
            b.log(msg)
            self.s.on_alert(msg)
            self.s.on_no_route(msg)
            return True
        differs = [(who, aid) for (who, aid), v in a["ans"].items()
                   if v != (st.abil_value(aid, "total") or (None,))[0]]
        if differs and a["mp"].title.startswith("Go to "):
            # someone's flag isn't yours, but there's a way for everyone: work the Go to out again with theirs —
            # the path we asked about may go by a gate only you get through ('ask Jorah transport' needs
            # NeutralQuest 2+; Evolution took the whole party there, 2026-11-21)
            who = sorted({w_ for w_, _a in differs})
            b.log(f"Quest flags: {', '.join(who)} {'has' if len(who) == 1 else 'have'} different ones — "
                  f"working the way out again so everyone gets through")
            if b.goto(a["target"], then=b.after_goto):
                return True
        b.start_path(a["mp"], a["loop"], checked=True)
        return True

    def _gets_through(self, target, aid, v) -> bool:
        """Would the way there exist with this value of the flag (theirs instead of yours)?"""
        b, st = self.bot, self.s.state
        key = ("granted", aid)
        saved = st.abil_rows.get(key)
        try:
            # (they said 'not set': known to be missing — 0, not 'unknown', which the map reads as 'maybe fine')
            st.abil_rows[key] = (0 if v is None else v, time.time())
            return b.plan_route(st.room, target) is not None
        finally:
            if saved is None:
                st.abil_rows.pop(key, None)
            else:
                st.abil_rows[key] = saved
