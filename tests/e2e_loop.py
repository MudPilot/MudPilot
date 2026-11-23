"""Loop laps on the practice server, against the bundled Paradigm map (the way e2e_realm_walk.py runs).

Scenarios (--case):
  laps    whole laps of a Town Gates <-> River Street loop (1/1 -> 1/16 -> 1/1), with combat/rest/loot on
  lost    mid-lap the practice server moves you somewhere off the loop (a teleport the bot didn't ask for): it
          should notice, resync and get back onto the loop
  fail    one exit on the loop starts answering 'Your path is blocked.' for 20 s: the bot should not hammer it
          forever, nor lose its place; when it opens again the laps carry on
  all     the three in turn (default)

  python tests\\e2e_loop.py --case all --secs 90
Exit 0 unless a scenario fails its checks."""
import argparse, asyncio, os, sys, tempfile, threading, time
ROOT = os.environ.get("MUDPILOT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("MUDPILOT_SRC") or ROOT)
DB = os.path.join(ROOT, "mudpilot", "bundled", "Paradigm.db")
os.environ.setdefault("MUDPILOT_NO_RECORD", "1")
if not os.environ.get("MUDPILOT_DATA_DIR"):
    os.environ["MUDPILOT_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "mudpilot_e2e_loop")
os.makedirs(os.environ["MUDPILOT_DATA_DIR"], exist_ok=True)
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route

A, B = (1, 1), (1, 16)


def scenario(case, port, secs, seed):
    real = WorldDB(DB)                       # the practice realm's own map: the bot gets its own copy
    sim = simserver.Sim(real, seed=seed, mob_rate=0.35 if case == "laps" else 0.1, start=A)

    up = {}

    def run_server():
        async def go():
            try:
                srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", port)
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
    if not up.get("ok"):                     # never walk someone else's server on a busy port
        print(f"practice server didn't start on port {port}: {up.get('err')}", flush=True)
        os._exit(2)
    st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
    st.host, st.port, st.username, st.my_name = "127.0.0.1", port, "Tester", "Tester"
    st.auto_reconnect = False
    st.auto_combat = True; st.attack_spells = ["bliz", "fbal"]; st.min_mobs, st.max_mobs = 1, 3
    st.auto_rest = True; st.rest_below_ma, st.rest_until_ma = 30, 90; st.auto_loot = True
    s = Session(st, world_path=DB); s.password = "x"; s._no_log_file = True
    s.on_alert = lambda m: None
    s.on_no_route = lambda m: None
    mism = []
    s.state.on_room.append(lambda gs: mism.append((time.time(), gs.room, sim.players[-1].room))
                           if gs.room and sim.players and gs.room != sim.players[-1].room else None)
    s.connect()
    t0 = time.time()
    while time.time() - t0 < 4 and not (s.state.room and s._entered):
        s.poll(); time.sleep(0.03)
    w = s.world
    loop = path_from_route(w, A, w.route(A, B) + w.route(B, A), name="test loop")
    loop_rooms = {A} | {ex.to for ex in w.route(A, B) + w.route(B, A)}
    s.bot.start_path(loop, loop=True)
    end = time.time() + secs
    laps, last, ev, notes = 0, 0, {}, []
    blocked = None
    while time.time() < end:
        s.poll(); time.sleep(0.03)
        el = time.time() - (end - secs)
        p = sim.players[-1] if sim.players else None
        if case == "lost" and "tp" not in ev and el > 15 and p and not p.combat:
            # off the loop, a few rooms away (Silvermere's streets), without a move the bot sent
            off = next(k for k in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11) if (1, k) in real.rooms and (1, k) not in loop_rooms)
            ev["tp"] = (time.time(), tuple(p.room), (1, off))
            p.room = (1, off)
            notes.append(f"teleported {ev['tp'][1]} -> {(1, off)} at {el:.0f}s")
        if case == "lost" and "tp" in ev and "back" not in ev and s.state.room in loop_rooms and \
                p and tuple(p.room) in loop_rooms and time.time() - ev["tp"][0] > 1:
            ev["back"] = time.time() - ev["tp"][0]
            notes.append(f"back on the loop after {ev['back']:.1f}s at {s.state.room}")
        if case == "fail" and "blk" not in ev and el > 10 and p:
            r = real.room(tuple(p.room))
            nxt = s.bot.path.steps[s.bot.idx] if s.bot.path and s.bot.idx < len(s.bot.path.steps) else None
            ex = r.exits.get((nxt.move or "").upper()) if nxt else None
            if ex is not None:
                blocked = (ex, ex.kind)
                ex.kind = "restricted"          # the plain server answers 'Your path is blocked.'
                ev["blk"] = time.time()
                notes.append(f"blocked {p.room} {ex.dir} at {el:.0f}s")
        if case == "fail" and "blk" in ev and "open" not in ev and time.time() - ev["blk"] > 20:
            blocked[0].kind = blocked[1]
            ev["open"] = time.time()
            ev["sent_blocked"] = sum(1 for l in s.logs if "path is blocked" in l.lower())
            notes.append(f"opened again; bot status then: {s.bot.status!r} walking={s.bot.walking}")
        if s.bot.idx < last:
            laps += 1
        last = s.bot.idx
    print(f"== {case}: loop {len(loop.steps)} steps, laps {laps}, idx {s.bot.idx}, walked {s.state.steps_walked}")
    print(f"   kills {s.state.kills} exp {s.state.exp_gained} cash {s.state.copper_looted} deaths {s.state.deaths}")
    print(f"   tracking mismatches: {len(mism)} {[(r, q) for _t, r, q in mism[:4]]}")
    print(f"   walking: {s.bot.walking} | status: {s.bot.status}")
    for n in notes:
        print("   " + n)
    ok = s.bot.walking and laps >= 1
    if case == "lost":
        ok = ok and "back" in ev
    if case == "fail":
        ok = ok and "open" in ev
    tail = [l for l in s.logs if "Trigger" not in l][-25:]
    print("   log tail:\n     " + "\n     ".join(tail))
    print(f"   {'PASS' if ok else 'FAIL'}")
    try:
        s.disconnect()
    except Exception:
        pass
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="all", choices=["laps", "lost", "fail", "all"])
    ap.add_argument("--secs", type=int, default=90)
    ap.add_argument("--port", type=int, default=2560)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    cases = ["laps", "lost", "fail"] if a.case == "all" else [a.case]
    res = [scenario(c, a.port + i, a.secs, a.seed) for i, c in enumerate(cases)]
    os._exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
