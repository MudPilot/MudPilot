"""Phoenix feather quest (Dan, 2026-10-30) on the practice server, with real random drops:
- the Warped Asylum: Go to the old man (9/1259) from the Asylum Ward — 'asylum' drops you anywhere in 9/1183-1206 and
  the cells' corridors drop you in a random north cell (9/1255-1263): walk on from wherever it lands — Dan's
  'n s n s… until we see the old man';
- quest stage 4: 'go portal' at 9/1291 drops you anywhere in the Caves of Chaos (9/1292-1327) — find where, walk to
  the shadow guard (9/1423)."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
PORT = 2446
sim = simserver.Sim(world, seed=7, mob_rate=0, start=(9, 1182))
sim.quest = {133: 4}


def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())


threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_reconnect = False; st.auto_combat = False; st.char_level = 15
s = Session(st); s.password = "x"; s._no_log_file = True
s._abil = s.state.abil_value
s.state.abil_value = lambda a, kind="total": (4,) if a == 133 else s._abil(a, kind)
s.connect()
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s.poll()
        if until and until():
            return True
        time.sleep(0.02)
    return False


run(5, lambda: s.state.room is not None and s._entered)
s.state.level = 15
p = sim.players[-1]
check(f"starts in the Asylum Ward ({s.state.room})", s.state.room == (9, 1182))
check("Go to the old man starts", s.bot.goto((9, 1259)))
run(300, lambda: p.room == (9, 1259) and not s.bot.walking)
drops = sum(1 for x in s.logs if "the drop landed in" in x)
check(f"reached the old man's cell 9/1259 (true room {p.room}, {drops} drops)", p.room == (9, 1259))
check("never gave up as 'knocked off the path'", not any("Drift:" in x or "Stopped" in x for x in s.logs))
# the portal at quest stage 4: into the Caves of Chaos, then on to the shadow guard
p.room = (9, 1291)
s.send("")
run(4, lambda: s.state.room == (9, 1291))
check("Go to the shadow guard starts", s.bot.goto((9, 1423)))
run(240, lambda: p.room == (9, 1423) and not s.bot.walking)
check(f"through the Caves of Chaos to the shadow guard 9/1423 (true room {p.room})", p.room == (9, 1423))
print("\n".join(x for x in s.logs[-25:] if "Go to" in x or "drop" in x or "Arrived" in x or "Stopped" in x))
print("ALL PASS" if ok else "SOME FAILED")
os._exit(0 if ok else 1)
