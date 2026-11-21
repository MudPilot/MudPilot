"""0.8.190 (Dan, "guarded portals"): a portal / hole MME only lets you use with the room clear ('nomonsters' — the
Deranged Priest's 'go hole' at 16/356, the master assassin's 'push panel' at 7/1283) is planned with Combat on or off,
and the walk fights what's there first, then goes (the sweep: 'go hole' 8 times into a priest, then "isn't getting
anywhere"). Planned, then walked on the practice server with honest gates."""
import asyncio, os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_guarded"))
from mudpilot import config, simserver
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
DB = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=DB); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
ex = w.room((16, 356)).exits["@go hole"]
check(f"16/356 'go hole' needs the room clear ({ex.req.get('nomonsters')})", ex.req.get("nomonsters"))
st.auto_combat = False
s.route_char()
r = w.route((16, 356), (16, 543), level=55)
check(f"Combat off: still planned through it (Dan: it fights the guard anyway) ({len(r) if r else None})", r and r[0] is ex)
st.auto_combat = True
s.route_char()
r = w.route((16, 356), (16, 543), level=55)
check("Combat on: planned through it", r and r[0] is ex)
priest = w.monster_names.get("deranged priest")
step = Step(w.room((16, 356)).mega_hash, 0, "go hole", [], (16, 356), (16, 543))
g.candidates = [(16, 356)]
g.view = RoomView("Guarded Hut", {"N"}, [("deranged priest", priest)])
check("the priest's there: the walk holds the step and goes for it", b._guard_first(step, (16, 356), time.time())
      and b.hunt_target is priest)
g.view = RoomView("Guarded Hut", {"N"}, [])
check("gone: on through the hole", not b._guard_first(step, (16, 356), time.time()) and b.hunt_target is None)
st.auto_combat = False
g.view = RoomView("Guarded Hut", {"N"}, [("deranged priest", priest)])
b.walking = True
held = b._guard_first(step, (16, 356), time.time())
check(f"Combat off with the priest there: fights it anyway ({b.status})", held and b.hunt_target is priest)
st.auto_combat = True

# ---- walked: the practice server's priest stands in 16/356 and 'go hole' fails while he's there
PORT = 2493
real = WorldDB(DB)
sim = simserver.Sim(real, seed=6, mob_rate=0, start=(16, 356), gates={"kit": [1281], "level": 55})
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r_, w_: simserver.handle(sim, r_, w_), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)
st2 = config.Settings(); st2.save = lambda: None; st2.board = "Paradigm"; st2.my_name = "Tester"
st2.host, st2.port, st2.username = "127.0.0.1", PORT, "Tester"
st2.auto_reconnect = False; st2.auto_combat = True; st2.char_level = 55; st2.stop_before_boss = False
st2.char_class, st2.char_race, st2.char_alignment = "Mage", "Human", "Good"
s2 = Session(st2, world_path=DB); s2.password = "x"; s2._no_log_file = True
s2.on_alert = lambda m: None; s2.on_no_route = lambda m: None
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
check(f"the walk starts ({s2.bot.goto((16, 543))})", s2.bot.walking)
run(180, lambda: not s2.bot.walking)
pl = sim.players[-1]
check(f"the priest died and the hole was taken (in {pl.room[0]}/{pl.room[1]}; {s2.bot.status})", pl.room == (16, 543))
print("ALL PASS" if ok else "SOME FAILED")
sys.stdout.flush()
os._exit(0 if ok else 1)
