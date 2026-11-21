"""0.8.189 (realm walk sweep): the Treetops' 16/551 north wall opens with 'tear bark' in 16/569 — and 16/569 is
behind a wall 'push knot' in 16/567 opens. The Go to's tour round the bark gave up on that (a leg through another
remote-action wall), so the walk typed 'n' into the wall at 16/551 and stopped: "no exit n from 16/551 and no other
way" (Lost City bank → the Volcano and Undermountain both died there). Now a leg gets its own tour: knot, bark, back,
north. Planned, then walked for real on the practice server with honest gates."""
import asyncio, os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_nested"))
from mudpilot import config, simserver
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
DB = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# ---- the plan
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=DB); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w = s.bot, s.world
p = b.pilot
p.target, p.done, p.prog, p.pending = (16, 552), {}, {}, None
steps = p._build((16, 550)) or []
seq = [(st_.room, c) for st_ in steps for c in (st_.pre or [])]
check(f"a plan from 16/550 to 16/552 ({len(steps)} steps)", steps)
knot = next((i for i, (r, c) in enumerate(seq) if c == "push knot"), None)
bark = next((i for i, (r, c) in enumerate(seq) if c == "tear bark"), None)
check(f"'push knot' goes out in 16/567 ({seq[knot] if knot is not None else None})",
      knot is not None and seq[knot][0] == (16, 567))
check(f"…then 'tear bark' in 16/569 ({seq[bark] if bark is not None else None})",
      bark is not None and knot is not None and bark > knot and seq[bark][0] == (16, 569))
north = next((i for i, x in enumerate(steps) if x.room == (16, 551) and x.move == "N"), None)
via_569 = next((i for i, x in enumerate(steps) if x.room == (16, 568) and x.move == "NW"), None)
check(f"…through 16/568 NW once it's open, and north from 16/551 last (steps {via_569}, {north})",
      north is not None and via_569 is not None and via_569 < north and north == len(steps) - 1)

# ---- walked, on the practice server with honest gates (its own copy of the map)
PORT = 2491
real = WorldDB(DB)
sim = simserver.Sim(real, seed=3, mob_rate=0, start=(16, 550), gates={"kit": [1281], "level": 55})
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w_: simserver.handle(sim, r, w_), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)
st2 = config.Settings(); st2.save = lambda: None; st2.board = "Paradigm"; st2.my_name = "Tester"
st2.host, st2.port, st2.username = "127.0.0.1", PORT, "Tester"
st2.auto_reconnect = False; st2.auto_combat = False; st2.char_level = 55
st2.char_class, st2.char_race, st2.char_alignment = "Mage", "Human", "Good"
s2 = Session(st2, world_path=DB); s2.password = "x"; s2._no_log_file = True
s2.on_alert = lambda m: None; s2.on_no_route = lambda m: None
sent = []
_o = s2.send
s2.send = lambda c, from_bot=False: (sent.append(c), _o(c, from_bot))[1]
s2.connect()
def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s2.poll()
        if until and until():
            return True
        time.sleep(0.02)
    return False
run(8, lambda: s2.state.room is not None and s2._entered)
s2.state.level = 55
check(f"the walk starts ({s2.bot.goto((16, 552))})", s2.bot.walking)
run(90, lambda: not s2.bot.walking)
pl = sim.players[-1]
check(f"arrived in 16/552 (in {pl.room[0]}/{pl.room[1]}; status: {s2.bot.status})", pl.room == (16, 552))
check(f"pushed the knot and tore the bark ({[c for c in sent if c in ('push knot', 'tear bark')]})",
      "push knot" in sent and "tear bark" in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.stdout.flush()
os._exit(0 if ok else 1)
