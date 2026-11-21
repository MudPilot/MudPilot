"""Walk sweep: actually walk a sample of the route sweep's Go tos on the practice server (simserver) and catch walker
problems — stuck steps, doors not opened, blocked moves, loops, timeouts, tracking drift.

Reads tests/sweep_cases.json (run tests\\sweep_routes.py first). Each walk starts a short way (--len rooms) before
the target on the planned way in, so the odd exit at the end gets walked without a 300-room trek. The practice
server only knows what MME says, and it can't do keys/items/tolls/casts/level gates ('Your path is blocked'), so
routes using those are listed as skipped, not walked. Appends a walk section to tests/sweep_report.txt.

  python tests\\e2e_sweep_walk.py               up to 24 walks
  python tests\\e2e_sweep_walk.py --max 60 --len 40

Backburner tooling: exit code is 0 unless the sweep itself breaks."""
import argparse, asyncio, collections, json, os, re, sys, threading, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.ansi import plain

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(here, "tests", "sweep_cases.json")
REPORT = os.path.join(here, "tests", "sweep_report.txt")
SIM_OK = {"normal", "door", "hidden", "text", "trap", "cmd"}       # what the practice server can walk
INTERESTING = {"door", "hidden", "text", "trap"}
PORT = 2431


def rname(w, k):
    r = w.room(tuple(k))
    return f"{k[0]}/{k[1]} {r.name}" if r else f"{k[0]}/{k[1]} ?"


def route_kinds(route):
    return [ex.kind for ex in route]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=24)
    ap.add_argument("--len", type=int, default=30, help="start this many rooms before the target")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    try:
        cases = json.load(open(CASES, encoding="utf-8"))
    except OSError:
        print("Run tests\\sweep_routes.py first (no tests\\sweep_cases.json)")
        return 1
    world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
    from mudpilot import board_fixes
    board_fixes.apply(world)
    level = 47

    # ---- pick walks: planner said ok-ish, no errands; start --len rooms back along the way in
    picks, skipped, seen = [], [], set()
    every = set(world.items)
    for c in cases:
        if a.only and a.only.lower() not in c["label"].lower():
            continue
        tgt = tuple(c["target"])
        if c.get("errands") or not c.get("steps") or tgt in seen:
            continue
        full = world.route(tuple(c["start"]), tgt, level=level, have=every)
        if not full:
            continue
        rooms = [tuple(c["start"])] + [ex.to for ex in full]
        i0 = max(0, len(full) - a.len)
        start, leg = rooms[i0], full[i0:]
        kinds = set(route_kinds(leg))
        if kinds - SIM_OK:
            skipped.append((c, sorted(kinds - SIM_OK)))
            continue
        seen.add(tgt)
        picks.append({"label": c["label"], "start": start, "target": tgt, "kinds": sorted(kinds),
                      "n": len(leg), "score": len(kinds & INTERESTING) * 10 + ("[" in c["label"]) * 5})
    picks.sort(key=lambda p: -p["score"])
    picks = picks[:a.max]
    print(f"{len(picks)} walks, {len(skipped)} skipped (sim can't model their exits)")

    # ---- practice server + one session; each walk teleports the sim player to its start
    sim = simserver.Sim(world, seed=5, mob_rate=0, start=picks[0]["start"] if picks else (1, 1))

    def run_server():
        async def go():
            srv = await asyncio.start_server(lambda r, w_: simserver.handle(sim, r, w_), "127.0.0.1", PORT)
            async with srv:
                await srv.serve_forever()
        asyncio.run(go())
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(0.5)
    st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
    st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
    st.auto_reconnect = False; st.auto_combat = False; st.char_level = level
    st.bash_doors_first = False             # the practice server has no 'bash' ("Huh?"): open doors instead
    s = Session(st); s.password = "x"; s._no_log_file = True
    s.world = world; s.state.world = world
    s.on_alert = lambda m: None
    s.on_no_route = lambda m: None
    rx = []
    _ol = s.on_line
    seq = []                                 # ('>', sent) / ('<', received), in order, for context
    s.seq = seq
    s.on_line = lambda segs: (rx.append(plain(segs)), seq.append(("<", plain(segs))), _ol(segs))
    sent = []
    _o = s.send
    s.send = lambda c, from_bot=False: (sent.append(c), seq.append((">", c, sim.players[-1].room if sim.players else None)),
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
    run(6, lambda: s.state.room is not None and s._entered)
    s.state.level = level
    results = []
    for i, p in enumerate(picks):
        res = walk_one(s, sim, world, p, rx, sent, run)
        results.append(res)
        print(f"[{i + 1:2d}/{len(picks)}] {'ISSUE' if res['issues'] else 'ok   '} {rname(world, p['start'])} → "
              f"{rname(world, p['target'])} ({p['label'][:50]}) {res['secs']} s"
              + (f"  — {res['issues'][0][0]}" if res["issues"] else ""), flush=True)
    write_report(world, results, skipped, a)
    print(f"\nReport section appended: {REPORT}")
    os._exit(0)


def walk_one(s, sim, w, p, rx, sent, run):
    b = s.bot
    res = {"label": p["label"], "start": p["start"], "target": p["target"], "kinds": p["kinds"], "issues": [],
           "notes": []}
    try:
        b.stop("Stopped by you"); b.errands.cancel()
    except Exception:
        pass
    pl = sim.players[-1]
    pl.room = tuple(p["start"]); pl.open_doors.clear(); pl.combat = None
    if getattr(w, "failed_edges", None):
        w.failed_edges.clear()
    s.state.candidates = [tuple(p["start"])]
    s.send("")
    run(3, lambda: s.state.room == tuple(p["start"]))
    rx0, tx0, sq0 = len(rx), len(sent), len(s.seq)
    trail, t0 = [pl.room], time.time()
    last_move = [time.time()]
    stuck = [0.0]

    def each():
        if pl.room != trail[-1]:
            trail.append(pl.room)
            last_move[0] = time.time()
        elif b.walking:
            stuck[0] = max(stuck[0], time.time() - last_move[0])
    try:
        ok = b.goto(tuple(p["target"]))
    except Exception:
        res["issues"].append(("exception", traceback.format_exc(limit=6), "automation.Bot.goto"))
        res["secs"] = 0
        return res
    if not ok:
        res["issues"].append(("no route", b.no_route_msg, "automation.Bot.goto"))
        res["secs"] = 0
        return res
    n = len(b.path.steps) if b.path else p["n"]
    res["steps_planned"] = n
    limit = 25 + 3 * n
    busy = lambda: (b.walking or b.errands.active or getattr(b, "_await_inv", None)
                    or getattr(b, "_pending_goto", None) or getattr(b, "_pending_abil", None))
    done = run(limit, lambda: time.time() - t0 > 1.5 and not busy(), each)
    res["secs"] = round(time.time() - t0, 1)
    rxs, txs = rx[rx0:], sent[tx0:]
    goal = tuple(getattr(b, "_goto_target", None) or p["target"])
    res["trail"] = [list(k) for k in trail]
    res["tx"] = txs[-12:]
    if not done:
        res["issues"].append(("timeout", f"still walking after {limit} s at {rname(w, pl.room)} "
                              f"(status: {b.status})", "pilot.py / automation.Bot.walk"))
        b.stop("Stopped by you")
    elif pl.room == tuple(p["start"]) and any("Not walking" in l for l in s.logs[-6:]):
        # refused before the first step (a key it can't fetch for the sim's character — Druid / Dark-Elf / level 38
        # from the practice server's 'stat'): a planner answer, not a walker problem
        res["notes"].append("refused to start: " + next(l for l in reversed(s.logs) if "Not walking" in l)[10:200])
    elif pl.room != goal:
        res["issues"].append(("stopped short", f"stopped at {rname(w, pl.room)} (status: {b.status}; "
                              f"log: {' | '.join(s.logs[-3:])[:300]})", "automation.Bot.walk / pilot.Pilot"))
    if stuck[0] > 20:
        res["issues"].append(("stuck step", f"no move for {stuck[0]:.0f} s while walking",
                              "automation.Bot.walk (stall watchdog) / pilot.py"))
    cnt = collections.Counter(trail)
    loops = [(k, c) for k, c in cnt.items() if c >= 5]   # (out-and-back to a remote action passes rooms 3-4 times)
    if loops:
        k, c = max(loops, key=lambda x: x[1])
        res["issues"].append(("loop", f"in {rname(w, k)} {c} times", "pilot.Pilot re-plan / gamestate._locate"))
    sq = s.seq[sq0:]
    def cause(pat):
        # the move sent just before each such line
        out = []
        for i, (k, t, *_r) in enumerate(sq):
            if k == "<" and pat in t.lower():
                prev = next((f"{x[1]} in {x[2][0]}/{x[2][1]}" if x[2] else x[1] for x in reversed(sq[:i])
                             if x[0] == ">"), "?")
                out.append(prev)
        return collections.Counter(out).most_common(4)
    closed = sum("door is closed" in l.lower() for l in rxs)
    blocked = sum("path is blocked" in l.lower() for l in rxs)
    noexit = sum("no exit in that direction" in l.lower() for l in rxs)
    if closed >= 2:
        res["issues"].append(("door not opened", f"'The door is closed' {closed} times after "
                              f"{cause('door is closed')} (door commands: "
                              f"{[t for t in txs if t.split()[:1] in (['open'], ['bash'], ['pick'])][:4]})",
                              "automation.Bot door handling (bash-first / open)"))
    # the practice server only lets you through a hidden exit after search / its action; the game lets you walk
    # a '(Hidden/Passable)' one straight away — those 'no exit's are the sim's, not the walker's
    def sim_gap(x):
        if x[0] != ">" or not x[2]:
            return False
        r = w.room(x[2]); d = (x[1] or "").strip().upper()
        from mudpilot.worlddb import norm_dir
        e = r.exits.get(norm_dir(d) or "") if r else None
        return bool(e and e.kind == "hidden" and "pass" in e.etype.lower())
    def blocked_kind(x):
        if x[0] != ">" or not x[2]:
            return None
        from mudpilot.worlddb import norm_dir
        r = w.room(x[2]); e = r.exits.get(norm_dir((x[1] or "").strip()) or "") if r else None
        return e.kind if e else None
    simblk = 0
    for i, x in enumerate(sq):
        if x[0] == "<" and "path is blocked" in x[1].lower():
            prev = next((y for y in reversed(sq[:i]) if y[0] == ">"), None)
            if prev and blocked_kind(prev) in ("key", "item", "toll", "cast", "restricted", "action"):
                simblk += 1
    if simblk:
        res["notes"].append(f"{simblk} 'path is blocked' on key/toll/item exits (sim gap; walker went round)")
    blocked -= simblk
    gaps = 0
    for i, x in enumerate(sq):
        if x[0] == "<" and "no exit in that direction" in x[1].lower():
            prev = next((y for y in reversed(sq[:i]) if y[0] == ">"), None)
            if prev and sim_gap(prev):
                gaps += 1
    if gaps:
        res["notes"].append(f"{gaps} 'no exit' from Hidden/Passable exits (sim gap; walker routed round)")
    noexit -= gaps
    if blocked:
        res["issues"].append(("blocked", f"'Your path is blocked.' {blocked} times after {cause('path is blocked')}", "worlddb.can_use / sim gap"))
    if noexit >= 2:
        res["issues"].append(("no exit", f"'There is no exit in that direction!' {noexit} times, after "
                              f"{cause('no exit in that direction')}",
                              "automation.Bot hidden-exit handling / gamestate tracking"))
    if s.state.room and tuple(s.state.room) != pl.room:
        res["issues"].append(("tracking", f"thinks it's in {rname(w, s.state.room)}, really {rname(w, pl.room)}",
                              "gamestate._locate"))
    if os.environ.get("SWEEP_DEBUG"):
        for x in sq:
            print("   ", x[0], x[1][:110], x[2] if len(x) > 2 and x[2] else "")
    if len(trail) - 1 > n * 1.5 + 6:
        res["notes"].append(f"walked {len(trail) - 1} rooms for {n} planned")
    return res


def write_report(w, results, skipped, a):
    bad = [r for r in results if r["issues"]]
    kinds = collections.Counter(i[0] for r in bad for i in r["issues"])
    L = ["", "=" * 100, f"MudPilot route sweep (walk, practice server) — {time.strftime('%Y-%m-%d %H:%M')}",
         f"{len(results)} walks (each from {a.len} rooms out), {len(bad)} with issues: "
         + (", ".join(f"{k} {n}" for k, n in kinds.most_common()) or "none"), ""]
    for r in bad:
        L.append(f"- {rname(w, r['start'])} → {rname(w, r['target'])}  [{r['label']}]  exits: {', '.join(r['kinds'])}")
        for k, what, fix in r["issues"]:
            L.append(f"    {k}: {what}")
            L.append(f"    fix: {fix}")
        L.append(f"    walked: {' '.join('/'.join(map(str, k)) for k in r.get('trail', [])[-10:])}")
        L.append(f"    last sent: {r.get('tx')}")
    L.append("")
    L.append("walks:")
    for r in results:
        L.append(f"  {'!!' if r['issues'] else 'ok'} {rname(w, r['start']):<40} → {rname(w, r['target']):<40} "
                 f"{r['secs']:>6} s  {len(r.get('trail', [])) - 1:>3}/{r.get('steps_planned', '-')} rooms  {', '.join(r['kinds'])}" + ("  " + "; ".join(r["notes"]) if r["notes"] else ""))
    sk = collections.Counter(k for _c, ks in skipped for k in ks)
    L.append("")
    L.append(f"skipped (the practice server blocks these exit kinds): {len(skipped)} — "
             + ", ".join(f"{k} {n}" for k, n in sk.most_common()))
    with open(REPORT, "a", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)
