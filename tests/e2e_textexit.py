"""Paradigm: a text exit (go hole) into a passage that leads off-map — walked once, not looped."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
PORT = 2423
sim = simserver.Sim(world, seed=3, mob_rate=0, start=(1, 1694))
sim.text_delay = 1.5 if os.environ.get("LAGGY") else 0
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
st.auto_reconnect = False; st.auto_combat = False; st.char_level = 30
s = Session(st); s.password = "x"; s._no_log_file = True
s.connect()
def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s.poll()
        if until and until():
            return True
        time.sleep(0.02)
    return False
run(5, lambda: s.state.room is not None and s._entered)
print("start:", s.state.room)
s.state.level = 30
sent = []
_o = s.send
s.send = lambda c, from_bot=False: (sent.append(c), _o(c, from_bot))[1]
if os.environ.get("LAGGY"):
    # the real-game case: the tracker didn't recognise 'go hole' as a move (ambiguous room), so
    # nothing tells the walker a move is in flight — it must still wait for the room to answer
    _nc = s.state.note_command
    s.state.note_command = lambda c: None if c.strip().lower() == "go hole" else _nc(c)
ok = s.bot.goto((10, 3))
print("goto started:", ok, s.bot.status, s.bot.path and len(s.bot.path.steps))
arrived = run(60, lambda: not s.bot.walking)
print("arrived:", arrived, "at", s.state.room, "true:", sim.players[-1].room, "status:", s.bot.status)
print("go hole sent:", sent.count("go hole"), [c for c in sent if c.strip()][:12])
print("\n".join(s.logs[-12:]))
good = ok and sim.players[-1].room == (10, 3) and sent.count("go hole") == 1
print("ALL PASS" if good else "SOME FAILED")
os._exit(0 if good else 1)
