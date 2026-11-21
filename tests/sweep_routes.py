"""Route sweep (planner only, no game): Go to a curated list of tricky places, a sample of every kind of odd exit
and a sample of Rooms.md, from a few starting towns, the way the bot plans it (Bot.goto → plan_route, errands).
Flags: no route, routes through avoided areas, detours much longer than the plain shortest way, needed items
errands can't fetch, exceptions. Writes tests/sweep_report.txt (and sweep_cases.json for e2e_sweep_walk.py).

  python tests\\sweep_routes.py                 curated + exit-kind sample + 3 per Rooms.md group
  python tests\\sweep_routes.py --rooms all     every Rooms.md entry (slow)
  python tests\\sweep_routes.py --solo          plan alone instead of leading a party of two
  python tests\\sweep_routes.py --level 30      plan at another level

Backburner tooling: exit code is 0 unless the sweep itself breaks (findings aren't test failures)."""
import argparse, collections, json, os, random, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.board_fixes import VIA

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOMS_MD = os.path.join(here, "tests", "fixtures", "Paradigm_Rooms.md")    # copy of the mini PC's (read-only there)
REPORT = os.path.join(here, "tests", "sweep_report.txt")
CASES_OUT = os.path.join(here, "tests", "sweep_cases.json")

TOWNS = {"Silvermere": (1, 1), "Silvermere Town Square": (1, 224), "Arlysia": (17, 2269),
         "Khazarad": (6, 1245)}         # (Shadowmere 5/224 needs a level-75 portal on MME's map)

# (label, target, start town or None = every town, what it should do)
CURATED = [
    ("Great Pyramid, Entrance", (12, 1800), None, {}),
    ("Great Pyramid, Sphinx Lvl 1", (12, 1920), "Silvermere", {}),
    ("Great Pyramid, Level 3 Entrance", (12, 2002), "Silvermere", {}),
    ("Great Pyramid, Level 4", (12, 2052), "Silvermere", {"via": [(12, 2005)]}),
    ("Great Pyramid, Level 5", (12, 2077), "Silvermere", {}),
    ("Great Pyramid (Below Pharoah)", (12, 2085), None, {}),
    ("Dark-Elf City, Town Gates Archway", (8, 462), None, {"via": [(7, 1405)], "fetch": ["bloodstone orb"]}),
    ("Dark-elf Prison", (8, 493), None, {"via": [(7, 1405)]}),
    ("Dark-elf Castle Level 1", (8, 604), "Silvermere", {}),
    ("Dark-elf Queen", (8, 705), "Silvermere", {}),
    ("Dark-elf Archmage", (8, 558), "Silvermere", {}),
    ("Commander's Office (orb)", (8, 459), "Silvermere", {}),
    ("Black Steel Gate (statue)", (8, 461), "Silvermere", {}),
    ("Fungus Tunnel", (7, 1405), "Silvermere", {}),
    ("King Crab", (16, 297), None, {"lands": (16, 287)}),
    ("Dragon's Teeth Hills (Vortex)", (3, 783), "Silvermere", {}),
    ("Pillaged Museum Vortex", (3, 613), "Silvermere", {}),
    ("Mind Flayer Magus (Black Wasteland)", (3, 787), "Silvermere", {"avoided_target": True}),
    ("Wastelands Obelisk", (1, 2426), "Silvermere", {}),
    ("Rock Island (Nexus Portal)", (17, 9643), "Arlysia", {}),
    ("Mountain Plateau, NPP Portal", (16, 9504), "Silvermere", {}),
    ("Ancient Tree Portal", (9, 1291), "Silvermere", {}),
    ("Musty Grottos, Portal", (1, 9462), "Silvermere", {}),
    ("Redstone Tunnel, NPP Portal", (1, 2681), "Silvermere", {}),
    ("Bank of Godfrey (lever)", (1, 297), None, {}),
    ("Pier (raft shop)", (1, 1813), "Arlysia", {}),
    ("Albion River, Fork", (14, 2462), "Silvermere", {}),
    ("Talgarn, Central Dock", (14, 10141), "Silvermere", {}),
    ("The River Lorian, Waterfall", (14, 7332), "Silvermere", {}),
    ("Coldspring Confluence", (14, 9163), "Silvermere", {}),
]

CURATED_LABELS = {c[0] for c in CURATED}

KIND_SAMPLE = {"hidden": 10, "text": 10, "key": 10, "item": 8, "toll": 5, "restricted": 6, "door": 6, "cast": 5,
               "trap": 4}


def build(level, party):
    st = config.Settings(); st.save = lambda: None; st.char_level = level; st.my_name = "Miserable"
    st.auto_get_items = True; st.bash_key_doors = False; st.check_needed_items = True
    st.char_class = "Mage"; st.char_race = "Human"; st.char_alignment = "Good"      # party Miserable (race a guess)
    Session.rooms_md_path = property(lambda self: ROOMS_MD)
    s = Session(st)
    s.world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s.state.world = s.world
    s._board_fixes()                        # a Paradigm session has these (pyramid segments, shut doors)
    # quest gates ('Ability: 134 w/value 2 to 999'): the live characters have done the quests the sweep's
    # places need — count an ability we don't know as passed, and note which ones a route leaned on
    w, orig = s.world, s.world.gate_ok
    s.assumed = set()
    def gate_ok(ex):
        m = w.ABIL_GATE_RE.search(ex.etype or "")
        if m and not w.GATE_RE.search(ex.etype or "") and not w.ALIGN_RE.search(ex.etype or ""):
            fn = (w.char or {}).get("abil")
            if (fn(int(m.group(1))) if fn else None) is None and int(m.group(3)) > 0:
                s.assumed.add(int(m.group(1)))
                return True
        return orig(ex)
    w.gate_ok = gate_ok
    s._no_log_file = True
    s.sent = []
    class T:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): s.sent.append(x)
        def close(self): pass
    s.telnet = T(); s._entered = True; s.state.level = level
    s.on_no_route = lambda m: None
    s.on_alert = lambda m: None
    s.state.carrying = "astral staff (Weapon Hand)"; s.state.keys = ""; s.state.inv_seq += 1
    try:
        s.state.wealth = 200000
    except Exception:
        pass
    if party:
        s.state.party = {"Miserable": {}, "Revolution": {"class": "Druid"}}
        s.comeback.leading = lambda: True
    return s


def rname(w, k):
    r = w.room(k)
    return f"{k[0]}/{k[1]} {r.name}" if r else f"{k[0]}/{k[1]} ?"


def reset(s):
    b = s.bot
    try:
        b.stop("Stopped by you")
    except Exception:
        pass
    try:
        b.errands.cancel()
    except Exception:
        pass
    b._avoid_blocked = None
    b._trip_allow, b._trip_deny = {}, {}
    b._pending_goto = b._pending_abil = None
    if getattr(s.world, "failed_edges", None):
        s.world.failed_edges.clear()
    b._cool = {} if not hasattr(b, "_cool") else b._cool
    for k in ("opener_note", "dry_route_note"):
        try:
            b._cool.pop(k, None)
        except Exception:
            pass


def rooms_of(mp):
    out = []
    for x in mp.steps:
        if x.room:
            out.append(tuple(x.room))
        if x.dest:
            out.append(tuple(x.dest))
    return out


def run_case(s, label, start, target, expect):
    w, b = s.world, s.bot
    reset(s)
    s.state.candidates = [start]
    log0, sent0 = len(s.logs), len(s.sent)
    s.assumed.clear()
    res = {"label": label, "start": list(start), "target": list(target), "issues": [], "notes": []}
    lvl = b.route_level()
    avoid = b.avoid_set()
    t0 = time.time()
    try:
        ok = b.goto(target)
    except Exception:
        res["issues"].append(("exception", "Bot.goto raised:\n" + traceback.format_exc(limit=6),
                              "the frame at the bottom of the traceback"))
        return res
    res["secs"] = round(time.time() - t0, 2)
    if s.assumed:
        res["notes"].append("assumed quest abil " + ", ".join(map(str, sorted(s.assumed))))
    logs = s.logs[log0:]
    res["log"] = [l for l in logs if "started by" not in l][-8:]
    sent = s.sent[sent0:]
    mp = b.path
    act = b.errands.active
    if act and not mp:
        mp = act["then"][0]
    todo = (act or {}).get("todo") or []
    res["errands"] = [{"item": w.item_name(t["num"]), "kind": t["kind"], "room": list(t["room"]),
                       "what": t.get("what"), "dist": t.get("dist")} for t in todo]
    if not ok or mp is None:
        msg = b.no_route_msg or (logs[-1] if logs else "goto returned False")
        everything = w._route(start, target, level=999, have=set(w.items))
        if everything is None:
            # gates (class / alignment / spell trap / cast) aside, is there a way at all?
            og, oc = w.gate_ok, w.char
            w.gate_ok = lambda ex: True
            w.char = dict(oc or {}, spell_traps=True, wealth=10 ** 9)
            try:
                gated = w._route(start, target, level=999, have=set(w.items))
            finally:
                w.gate_ok, w.char = og, oc
        else:
            gated = None
        if b._pending_goto or b._pending_abil:
            res["issues"].append(("asked game", f"goto waited on the game first (sent {sent})",
                                  "automation.Bot.goto (_pending_goto/_pending_abil)"))
        elif expect.get("avoided_target") or tuple(target) in avoid or "which you're avoiding" in msg:
            res["notes"].append(f"no route (target in / only past an avoided area — expected): {msg}")
            if tuple(target) in avoid:
                res["issues"].append(("avoided target", "asked to go INTO an avoided area and refused because "
                                      "the only way in runs through avoided rooms: " + msg,
                                      "automation.Bot._plan_route: when the target is in an avoided area, drop "
                                      "that area's rooms from avoid (the Go to itself is the consent) — design call"))
        elif "can't fetch" in msg:
            res["issues"].append(("unfetchable", msg, "errands.Errands.source_for (quest item: no shop/drop/ask in "
                                  "MME) — or board_fixes for a known source"))
        elif everything is not None and w._route(start, target, level=lvl, have=set(w.items)) is None:
            res["notes"].append(f"level-gated: no way at level {lvl} even with every item (level 999: "
                                f"{len(everything)} rooms)")
            if expect.get("level_ok", True) and label in CURATED_LABELS:
                res["issues"].append(("level-gated", msg, "check the gate (MME level) — curated target"))
        elif everything is None and gated is not None:
            res["notes"].append(f"gated for this character (class/alignment/quest/spell trap): {msg[:200]}")
        elif everything is None:
            res["issues"].append(("MME gap", f"no way in at all on MME's map (even level 999 + every item): {msg}",
                                  "board_fixes.ADD_EXITS, or a learned exit / imported path"))
        else:
            res["issues"].append(("no route", msg, "automation.Bot.goto / _plan_route (route exists with every "
                                  f"item at level 999: {len(everything)} rooms)"))
        return res
    steps = len(mp.steps)
    res["steps"] = steps
    rr = rooms_of(mp)
    res["route"] = [list(k) for k in rr[:: max(1, len(rr) // 12)]][:14]
    res["kinds"] = sorted({(w.room(x.room).exits.get(x.dir).kind if x.room and x.dir and w.room(x.room)
                            and w.room(x.room).exits.get(x.dir) else "cmd") for x in mp.steps})
    end = tuple(mp.steps[-1].dest) if mp.steps and mp.steps[-1].dest else None
    real_target = tuple(getattr(b, "_goto_target", None) or target)
    if real_target != tuple(target):
        res["notes"].append(f"goes to {rname(w, real_target)} instead (twin / spawn room)")
    if expect.get("lands") and real_target != tuple(expect["lands"]):
        res["issues"].append(("wrong landing", f"expected to land at {rname(w, expect['lands'])}, "
                              f"goes to {rname(w, real_target)}", "automation.Bot._reachable_twin"))
    if end and end != real_target:
        res["issues"].append(("ends elsewhere", f"path ends at {rname(w, end)}, target {rname(w, real_target)}",
                              "megamud_files.path_from_route"))
    # avoided areas: not counting the ends (already in it / going into it)
    bad = [k for k in rr if k in avoid and k not in (start, real_target)]
    if bad and start not in avoid and real_target not in avoid:
        fb = any("will try picking/bashing" in l for l in logs) and b.plan_route(start, real_target) is None
        res["issues"].append(("through avoided", f"walks through {len(bad)} avoided rooms, e.g. {rname(w, bad[0])}"
                              + (" — plan_route found nothing (missing key), so goto's 'as if you had every key' "
                                 "fallback planned it without avoid=" if fb else ""),
                              "automation.Bot.goto fallback `full = w.route(..., have=self.every_item())` and "
                              "pilot.Pilot._route's same fallback: pass avoid=self.avoid_set()" if fb else
                              "automation.Bot._plan_route / _opener_route"))
    for t in todo:
        leg = w.route(start, tuple(t["room"]), level=lvl, have=b.held_items() or set(), avoid=avoid)
        if leg is None:
            plain_leg = w.route(start, tuple(t["room"]), level=lvl, have=b.held_items() or set())
            if plain_leg and any(ex.to in avoid for ex in plain_leg[:-1]):
                res["issues"].append(("errand through avoided", f"fetching {w.item_name(t['num'])} at "
                                      f"{rname(w, t['room'])} only goes through an avoided area",
                                      "errands.Errands.source_for (doesn't pass avoid= to w.route)"))
    for want in expect.get("fetch", []):
        if not any(e["item"] == want for e in res["errands"]):
            res["issues"].append(("missing fetch", f"expected an errand for {want}, got "
                                  f"{[e['item'] for e in res['errands']] or 'none'}", "errands.Errands.plan"))
    for v in expect.get("via", []):
        if tuple(v) not in rr:
            res["issues"].append(("not via", f"expected to go via {rname(w, v)}", "board_fixes.VIA / SEGMENTS"))
    # detours: against the plain shortest way that also stays out of avoided areas (with every item, so a key
    # errand doesn't count against it), and the whole trip with errands
    every = b.every_item()
    base = w._route(start, real_target, level=lvl, have=every, avoid=avoid if start not in avoid else None)
    raw = w._route(start, real_target, level=lvl, have=every)
    held = w._route(start, real_target, level=lvl, have=b.held_items() or set(),
                    avoid=avoid if start not in avoid else None)
    res["shortest_held"] = len(held) if held is not None else None
    res["shortest"] = len(base) if base is not None else None
    res["shortest_any"] = len(raw) if raw is not None else None
    pinned = any(tuple(v["via"]) in rr for v in VIA) or any(
        set(map(tuple, seg.get("nodes", []))) & set(rr) for seg in getattr(w, "segments", []))
    if base is not None and steps > len(base) * 1.5 + 20 and held is not None and not todo             and steps <= len(held) * 1.5 + 20:
        # the short way needs an item we don't carry (a key / raft) and the bot walks round instead
        res["issues"].append(("skipped shortcut", f"{steps} steps; with the item(s) the short way needs it'd be "
                              f"{len(base)} (without: {len(held)}) — not fetched",
                              "automation.Bot._dry_route (round-the-water limit) / goto: compare fetch+short "
                              "vs the long way"))
    elif base is not None and steps > len(base) * 1.5 + 20:
        if pinned:
            res["notes"].append(f"{steps} steps vs {len(base)} shortest (pinned way: board_fixes VIA/SEGMENTS)")
        else:
            res["issues"].append(("long detour", f"{steps} steps vs {len(base)} shortest staying out of avoided "
                                  "areas", "worlddb.WorldDB.route / automation.Bot._dry_route / _opener_route"))
    trip, at, got = 0, start, set(b.held_items() or set())
    for t in todo + ([{"room": real_target, "num": None}] if todo else []):
        leg = w.route(at, tuple(t["room"]), level=lvl, have=got | every if t["num"] is None else got)
        trip += len(leg) if leg is not None else 500
        at = tuple(t["room"])
        if t["num"] is not None:
            got.add(t["num"])
    res["trip"] = trip if todo else steps
    if todo and base is not None and trip > (len(base) + 30) * 3:
        res["issues"].append(("long errand", f"whole trip {trip} rooms with errands "
                              f"({', '.join(e['item'] + ' @ ' + '/'.join(map(str, e['room'])) for e in res['errands'])})"
                              f" vs {len(base)} plain", "errands.Errands.source_for / plan"))
    # needed items on the walk itself that nothing will fetch
    try:
        miss = b.missing_items(mp)
    except Exception:
        miss = None
        res["issues"].append(("exception", "Bot.missing_items raised:\n" + traceback.format_exc(limit=4),
                              "automation.Bot.missing_items"))
    if miss:
        hard, soft = miss
        fetched = {t["num"] for t in todo}
        for n in hard:
            if n in fetched:
                continue
            src = b.errands.source_for(n, frm=start)
            if src is None:
                res["issues"].append(("unfetchable", f"walk needs {w.item_name(n)} (#{n}) and errands.source_for "
                                      "has no source", "errands.Errands.source_for / worlddb item sources"))
        for n in soft:
            if n not in fetched:
                res["notes"].append(f"soft key {w.item_name(n)} not fetched (door gets picked/bashed)")
    if sent:
        res["notes"].append(f"sent: {sent[:4]}")
    return res


def sample_exits(w, rng):
    """target = the room beyond a random exit of each odd kind (seeded, so runs compare)."""
    by = collections.defaultdict(list)
    for k, r in w.rooms.items():
        for d, e in r.exits.items():
            if e.kind in KIND_SAMPLE and e.to in w.rooms and e.to != k:
                by[e.kind].append((k, d, e))
    out = []
    for kind, n in KIND_SAMPLE.items():
        pool = sorted(by[kind], key=lambda x: (x[0], x[1]))
        for k, d, e in rng.sample(pool, min(n, len(pool))):
            out.append((f"[{kind}] {d} of {rname(w, k)}: {e.etype[:50]}", tuple(e.to), "Silvermere", {"exit": (k, d)}))
    return out


def sample_rooms(s, per_group, rng):
    rows = s.known_rooms()
    by = collections.defaultdict(list)
    for g, n, k in rows:
        by[g].append((n, tuple(k)))
    out = []
    for g in sorted(by):
        items = by[g] if per_group is None else rng.sample(by[g], min(per_group, len(by[g])))
        for n, k in items:
            out.append((f"Rooms.md {g}: {n}", k, "Silvermere", {}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", default="3", help="Rooms.md entries per group, or 'all'")
    ap.add_argument("--level", type=int, default=47)
    ap.add_argument("--solo", action="store_true")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--only", default="", help="only cases whose label contains this")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    s = build(a.level, not a.solo)
    w = s.world
    cases = []
    for label, tgt, town, exp in CURATED:
        for tn in ([town] if town else list(TOWNS)):
            cases.append((label, TOWNS[tn], tgt, exp, tn))
    for label, tgt, tn, exp in sample_exits(w, rng):
        cases.append((label, TOWNS[tn], tgt, exp, tn))
    for label, tgt, tn, exp in sample_rooms(s, None if a.rooms == "all" else int(a.rooms), rng):
        cases.append((label, TOWNS[tn], tgt, exp, tn))
    if a.only:
        cases = [c for c in cases if a.only.lower() in c[0].lower()]
    results, t0 = [], time.time()
    for i, (label, start, tgt, exp, tn) in enumerate(cases):
        r = run_case(s, label, start, tgt, exp)
        r["town"] = tn
        r["exit"] = [list(exp["exit"][0]), exp["exit"][1]] if exp.get("exit") else None
        results.append(r)
        flag = "ISSUE" if r["issues"] else "ok   "
        print(f"[{i + 1:3d}/{len(cases)}] {flag} {tn} → {rname(w, tgt)} ({label}) "
              f"{r.get('steps', '-')} steps" + (f"  — {r['issues'][0][0]}" if r["issues"] else ""), flush=True)
    write_report(s, results, a, time.time() - t0)
    with open(CASES_OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"\nReport: {REPORT}")
    return 0


def write_report(s, results, a, secs):
    w = s.world
    bad = [r for r in results if r["issues"]]
    kinds = collections.Counter(i[0] for r in bad for i in r["issues"])
    L = [f"MudPilot route sweep (planner) — {time.strftime('%Y-%m-%d %H:%M')}",
         f"level {a.level}, {'solo' if a.solo else 'leading a party of two'}, {len(results)} Go tos in {secs:.0f} s",
         f"{len(bad)} with issues: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()), ""]
    order = ["exception", "through avoided", "avoided target", "skipped shortcut", "errand through avoided", "no route", "wrong landing", "not via",
             "missing fetch", "unfetchable", "ends elsewhere", "long errand", "long detour", "asked game", "MME gap"]
    for kind in order + sorted(set(kinds) - set(order)):
        rows = [(r, i) for r in bad for i in r["issues"] if i[0] == kind]
        if not rows:
            continue
        L.append(f"=== {kind} ({len(rows)}) ===")
        for r, (k, what, fix) in rows:
            L.append(f"- {r['town']} → {rname(w, tuple(r['target']))}  [{r['label']}]")
            L.append(f"    what: {what}")
            L.append(f"    route: {r.get('steps', '-')} steps (shortest {r.get('shortest')}, with what's held "
                     f"{r.get('shortest_held')}, ignoring avoided "
                     f"{r.get('shortest_any')}); errands: "
                     + ("; ".join(f"{e['item']} ({e['kind']} @ {e['room'][0]}/{e['room'][1]})" for e in r.get('errands', []))
                        or "none"))
            if r.get("log"):
                L.append("    log: " + " | ".join(r["log"][-3:])[:600])
            L.append(f"    fix: {fix}")
        L.append("")
    L.append("=== all Go tos ===")
    for r in results:
        L.append(f"{'!!' if r['issues'] else 'ok'} {r['town']:<22} → {rname(w, tuple(r['target'])):<45} "
                 f"{str(r.get('steps', '-')):>4} steps  trip {str(r.get('trip', '-')):>4}  "
                 + ("errands: " + ", ".join(e['item'] for e in r['errands']) if r.get('errands') else "")
                 + ("  notes: " + "; ".join(map(str, r['notes'])) if r['notes'] else ""))
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
