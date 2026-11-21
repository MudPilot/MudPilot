"""MME textblocks, read the way the game runs them.

A room's CMD column points at a textblock: lines of 'trigger:effect:effect…'. An effect can hand off to
another textblock ('text 9800', 'random 871'), so the thing that actually moves you is often a block or
two down the chain. This walks the whole chain for every trigger and reports what typing it does:

    dive sinkhole  → minlevel 20 → cast 5100 (sinkhole: teleport 12/2224)        → a way in
    say gazmuldduhaz → remoteaction 1188                                          → opens an exit
    lift portcullis (3/707) → testskill strength → remoteaction 909 … map 3       → opens an exit elsewhere

Each result carries the conditions met on the way (level, class, race, items, quest abilities, cash) and
whether luck is involved (testskill / random), so routing can decide if it's a way for *you*.
"""
from __future__ import annotations

import re

VERBS = {
    "message", "giveitem", "takeitem", "text", "teleport", "cast", "checkitem", "class", "random",
    "failability", "minlevel", "summon", "checkability", "giveability", "nomonsters", "testability",
    "price", "adddelay", "addability", "roomitem", "testskill", "goodaligned", "addexp", "evilaligned",
    "levelcheck", "remoteaction", "failitem", "monsters", "clearitem", "check", "learnspell", "addevil",
    "givecoins", "race", "failroomitem", "needmonster", "maxlevel", "delay", "droproomitem",
    "removeability", "add",
}


def block_lines(tbs: dict, num: int) -> list[list[str]]:
    """The lines of a textblock, following its LinkTo chain, each split into segments."""
    out, seen = [], set()
    while num and num in tbs and num not in seen and len(seen) < 20:
        seen.add(num)
        text, link = tbs[num][0], tbs[num][1]
        for ln in str(text or "").replace("\r", "").split("\n"):
            segs = [s.strip() for s in ln.split(":")]
            if any(segs):
                out.append(segs)
        num = link
    return out


def is_trigger(seg: str) -> bool:
    w = seg.split(" ")[0].lower() if seg else ""
    return bool(w) and w not in VERBS and not w.lstrip("-").isdigit()


def _ints(seg):
    return [int(x) for x in re.findall(r"-?\d+", seg)]


def new_req():
    return {"level": 0, "maxlevel": 0, "classes": [], "races": [], "abil": [], "no_abil": [], "items": [],
            "no_items": [], "price": 0, "good": None, "evil": None, "monster": [], "board": None, "voyage": 0,
            "gives": [], "nomonsters": False}


def _copy(req):
    return {k: (list(v) if isinstance(v, list) else v) for k, v in req.items()}


def run(tbs, spells, segs, here_map, req=None, chance=False, depth=0, seen=None):
    """Follow one line's effects. Yields (req, chance, teleport_to or None, opens[list of (map, room)])."""
    req = _copy(req or new_req())
    seen = set(seen or ())
    opens = []
    for seg in segs:
        if not seg:
            continue
        verb = seg.split(" ")[0].lower()
        a = _ints(seg)
        if verb == "cast" and a and req.get("board") and not req.get("voyage"):
            land, rounds = _voyage(spells, a[0], here_map)
            if land:
                r2 = _copy(req)
                r2["voyage"] = rounds
                yield r2, chance, land, opens
                return
        if verb == "minlevel" and a:
            req["level"] = max(req["level"], a[0])
        elif verb == "maxlevel" and a:
            req["maxlevel"] = a[0] if not req["maxlevel"] else min(req["maxlevel"], a[0])
        elif verb == "class" and a:
            req["classes"] = [a[0]]
        elif verb == "race" and a:
            req["races"] = [a[0]]
        elif verb in ("checkitem", "takeitem") and a:
            if a[0] not in req["items"]:
                req["items"].append(a[0])
        elif verb == "failitem" and a:
            req["no_items"].append(a[0])
        elif verb == "checkability" and len(a) >= 2:
            if (a[0], a[1]) not in req["abil"]:
                req["abil"].append((a[0], a[1]))
        elif verb == "testability" and len(a) >= 2:
            # exactly this value (a quest stage) — 'checkability' is "at least"
            req["abil_eq"] = list(req.get("abil_eq") or []) + [(a[0], a[1])]
        elif verb in ("giveability", "addability") and len(a) >= 2:
            req = _copy(req)
            req["gives"] = list(req.get("gives") or []) + [(a[0], a[1], verb == "addability")]
        elif verb == "giveitem" and a:
            req = _copy(req)                         # 'ask commander orb' → giveitem 807 (bloodstone orb)
            req["give_items"] = list(req.get("give_items") or []) + [a[0]]
        elif verb == "failability" and len(a) >= 1:
            req["no_abil"].append((a[0], a[1] if len(a) > 1 else 1))
        elif verb == "price" and a:
            req["price"] += a[0]
        elif verb == "goodaligned" and a:
            req["good"] = a[0]
        elif verb == "evilaligned" and a:
            req["evil"] = a[0]
        elif verb == "needmonster" and a:
            req["monster"].append(a[0])
        elif verb == "nomonsters":
            req["nomonsters"] = True                 # only with the room clear (a guard to kill first: 0.8.190)
        elif verb == "testskill":
            chance = True
        elif verb == "remoteaction" and a:
            # remoteaction <room> <message> <?> <exit>: opens that room's exit (0=N 1=S 2=E 3=W 4=NE 5=NW
            # 6=SE 7=SW 8=U 9=D) — on the same map
            opens.append((here_map, a[0], a[3] if len(a) >= 4 else None))
        elif verb == "teleport" and len(a) >= 2:
            yield req, chance, (a[1] or here_map, a[0]), opens
            return
        elif verb == "cast" and a:
            sp = (spells or {}).get(a[0]) or {}
            ab = {}
            for pair in sp.get("abils") or []:
                if len(pair) >= 2 and pair[0] is not None:
                    ab[int(pair[0])] = pair[1]
            if 140 in ab and ab[140]:
                yield req, chance, (int(ab.get(141) or here_map), int(ab[140])), opens
                return
            if int(ab.get(148) or 0) and depth < 8 and int(ab[148]) not in seen:
                # a spell that runs a textblock (Great Pyramid level 4 arches: pass / fail → random teleport)
                got = False
                for out in run(tbs, spells, [f"text {int(ab[148])}"], here_map, req, chance, depth + 1, seen):
                    got = True
                    yield out[0], out[1], out[2], opens + out[3]
                if got:
                    return
            if int(ab.get(141) or 0) > 0 and not int(ab.get(140) or 0) and int(sp.get("MinBase") or 0) > 0:
                # a boat: this cast puts you aboard (a random cabin, rooms MinBase–MaxBase on that map);
                # the next cast is the voyage — a timed spell whose end casts the next, until one lands you
                req = _copy(req)
                req["board"] = (int(ab[141]), int(sp["MinBase"]), int(sp.get("MaxBase") or sp["MinBase"]))
        elif verb == "cast" and a and req.get("board"):
            pass
        elif verb in ("text", "random") and a and depth < 8 and a[0] not in seen:
            seen.add(a[0])
            subs = block_lines(tbs, a[0])
            got = False
            for sub in subs:
                if sub and is_trigger(sub[0]):
                    continue                      # a trigger line in a sub-block isn't run by this
                for out in run(tbs, spells, sub, here_map, req, chance or verb == "random", depth + 1, seen):
                    got = True
                    o_req, o_ch, o_to, o_open = out
                    yield o_req, o_ch, o_to, opens + o_open
            if got and verb == "text":
                return
    if opens or req.get("gives") or req.get("give_items"):
        yield req, chance, None, opens


def _voyage(spells, num, here_map):
    """Follow a voyage spell's end-casts (ability 151) to the one that lands you (140/141).
    (landing room, rounds at sea) or (None, 0)."""
    rounds, seen = 0, set()
    for _ in range(12):
        sp = (spells or {}).get(num)
        if not sp or num in seen:
            return None, 0
        seen.add(num)
        ab = {int(x[0]): x[1] for x in sp.get("abils") or [] if len(x) >= 2 and x[0] is not None}
        rounds += int(sp.get("Dur") or 0)
        if int(ab.get(140) or 0):
            return (int(ab.get(141) or here_map), int(ab[140])), rounds
        num = int(ab.get(151) or 0)
        if not num:
            return None, 0
    return None, 0


def room_actions(tbs, spells, cmd_block, here):
    """What each command in a room does: [{trigger, triggers, to, opens, req, chance}].
    Synonyms with the same outcome ('dive sinkhole', 'jump sinkhole', 'go sinkhole') are merged."""
    acts = []
    for segs in block_lines(tbs, cmd_block):
        if not segs or not is_trigger(segs[0]):
            continue
        trig = segs[0].strip()
        for req, chance, to, opens in run(tbs, spells, segs[1:], here[0]):
            if to == here:
                to = None
            if to is None and not opens and not req.get("gives"):
                continue
            same = next((x for x in acts if x["to"] == to and x["opens"] == opens and x["req"] == req), None)
            if same:
                if trig.lower() not in [t.lower() for t in same["triggers"]]:
                    same["triggers"].append(trig)
                continue
            acts.append({"trigger": trig, "triggers": [trig], "to": to, "opens": opens, "req": req,
                         "chance": chance})
    return acts


def npc_actions(tbs, spells, block, here_map):
    """A monster's talk block: 'ways:3348 / temple:3349 / visit:3358' — a topic, then the textblock it
    runs. Returns the topics that move you: [{topic, to, req, chance}]."""
    out = []
    for segs in block_lines(tbs, block):
        if len(segs) < 2 or not segs[1].strip().isdigit():
            continue
        topic = segs[0].strip()
        for req, chance, to, opens in run(tbs, spells, [f"text {segs[1].strip()}"], here_map):
            if to or req.get("gives") or req.get("give_items") or opens:
                out.append({"topic": topic, "to": to, "req": req, "chance": chance, "opens": opens})
    return out
