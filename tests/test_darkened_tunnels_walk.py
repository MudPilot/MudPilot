"""0.8.214 (Dan, 2026-11-20): Buddy's Go to the Darkened Tunnels Throne Room, walked on the practice server: levers at
15/604 and 15/730, then 15/477 N."""
import asyncio, os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_remote_door"))
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_dt_walk"))
from mudpilot import config, simserver
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
DB = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
PORT = 2493
real = WorldDB(DB)
sim = simserver.Sim(real, seed=4, mob_rate=0, start=(15, 335), gates={"level": 41, "strength": 150})
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w_: simserver.handle(sim, r, w_), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"; st.my_name = "Tester"
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_reconnect = False; st.auto_combat = False; st.char_level = 41
st.char_class, st.char_race, st.char_alignment = "Paladin", "Half-Ogre", "Good"
s = Session(st, world_path=DB); s.password = "x"; s._no_log_file = True
s.on_alert = lambda m: None; s.on_no_route = lambda m: None
sent = []
_o = s.send
s.send = lambda c, from_bot=False: (sent.append((c, sim.players[-1].room if sim.players else None)), _o(c, from_bot))[1]
logs = []
_l = s.log
s.log = lambda m, *a, **k: (logs.append(m), _l(m, *a, **k))[1]
s.connect()
def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s.poll()
        if until and until():
            return True
        time.sleep(0.02)
    return False
run(8, lambda: s.state.room is not None and s._entered)
s.state.level = 41
b = s.bot
g0 = b.goto((15, 416))
run(6, lambda: b.walking)                   # (0.8.222: a door on the way — st first, a few seconds)
check(f"Go to the Throne Room from 15/335 starts ({g0})", b.walking)
run(5)
check(f"not stopped for 'no way there' ({[l for l in logs if 'Stopped' in l][:2]})",
      not any("no way there" in l for l in logs))
levers = [r for c, r in sent if c == "pull lever"]
run(400, lambda: sim.players and sim.players[-1].room == (15, 416) or not b.walking)
levers = [r for c, r in sent if c == "pull lever"]
check(f"pulled the levers in 15/604 and 15/730 ({levers})", {(15, 604), (15, 730)} <= set(levers))
check(f"arrived in the Throne Room ({sim.players[-1].room if sim.players else None}; {[l for l in logs if 'Stopped' in l][:2]})",
      sim.players and sim.players[-1].room == (15, 416))
print("ALL PASS" if ok else "SOME FAILED"); os._exit(0 if ok else 1)
