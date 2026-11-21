"""0.8.189 (realm walk sweep): the Grand Stair's south-east door (7/150, '[251 picklocks/strength]') opens with the
lever in 7/152. A Go to that pulled it a couple of minutes earlier counts it as done (3 minutes), so the next walk
went straight to the door — shut again by then. The door handler typed 'pull lever' in 7/150 (no lever there), tried
'open', and gave up: "Stopped: the door southeast is locked". Now a shut door that's opened from another room sends
the walk back round to do it again. Walked on the practice server with honest gates."""
import asyncio, os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_remote_door"))
from mudpilot import config, simserver
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
DB = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
PORT = 2492
real = WorldDB(DB)
sim = simserver.Sim(real, seed=4, mob_rate=0, start=(7, 149), gates={"kit": [1281], "level": 55, "strength": 75})
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
st.auto_reconnect = False; st.auto_combat = False; st.char_level = 55
st.char_class, st.char_race, st.char_alignment = "Mage", "Human", "Good"
s = Session(st, world_path=DB); s.password = "x"; s._no_log_file = True
s.on_alert = lambda m: None; s.on_no_route = lambda m: None
sent = []
_o = s.send
s.send = lambda c, from_bot=False: (sent.append((c, sim.players[-1].room if sim.players else None)), _o(c, from_bot))[1]
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
s.state.level = 55
b = s.bot
b.pilot.done[((7, 150), "SE")] = time.time() - 60      # pulled a minute ago, on an earlier walk: shut again now
check(f"the walk starts ({b.goto((7, 151))})", b.walking)
run(120, lambda: not b.walking)
pl = sim.players[-1]
check(f"arrived in 7/151 (in {pl.room[0]}/{pl.room[1]}; status: {b.status})", pl.room == (7, 151))
levers = [r for c, r in sent if c == "pull lever"]
check(f"pulled the lever in 7/152 ({levers})", (7, 152) in levers)
check("…and never 'pull lever' in 7/150, where there's none", (7, 150) not in levers)
print("ALL PASS" if ok else "SOME FAILED")
sys.stdout.flush()
os._exit(0 if ok else 1)
