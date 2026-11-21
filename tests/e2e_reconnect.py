"""Dropped line: auto-reconnect (in the background), log back in, carry on with the loop.
Also: a line that goes silent is noticed and dropped; a hang-up / Disconnect never reconnects."""
import asyncio, os, socket, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route

PORT = int(os.environ.get("PORT", 2417))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=7, mob_rate=0)

def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)

st = config.Settings()
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_reconnect, st.reconnect_delay = True, 2
s = Session(st)
s.password = "secret"
sent_alerts = []
s.notify.send = lambda kind, msg, force=False: sent_alerts.append((kind, msg))
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
        time.sleep(0.03)
    return False

run(5, lambda: s.state.room is not None and s._entered)
here = s.state.room
nb = next(ex.to for ex in world.room(here).exits.values() if ex.to and ex.to[0] == here[0] and world.route(ex.to, here))
lp = path_from_route(world, here, world.route(here, nb) + world.route(nb, here), name="Tiny loop")
s.bot.start_path(lp, loop=True, checked=True)
run(4, lambda: s.state.steps_walked >= 2)
check("walking the loop", s.bot.walking)

# 1) the line drops (router blip)
s.telnet.sock.shutdown(socket.SHUT_RDWR)
run(3, lambda: not s.telnet.connected and getattr(s, "_drop_resume", None) is not None)
check("noticed the drop", not s.telnet.connected and not s.bot.walking)
check("remembered the loop", getattr(s, "_drop_resume", None) and s._drop_resume["path"] is lp)
t0 = time.time()
back = run(20, lambda: s.telnet.connected and s._entered)
check("reconnected and back in the realm", back)
resumed = run(10, lambda: s.bot.walking and s.bot.path is lp)
check("carrying on with the loop", resumed)
check("phone told: dropped and back", [k for k, _ in sent_alerts].count("drop") >= 2)

# 2) the line goes silent
s.settings.dead_line_secs = 3
s._await_reply_since = time.time() - 10
run(1, lambda: not s.telnet.connected)
check("silent line dropped", not s.telnet.connected)
check("…and reconnects", run(20, lambda: s.telnet.connected and s._entered))

# 3) Disconnect by you: stays down
run(6, lambda: s.bot.walking)
s.disconnect()
run(8)
check("Disconnect stays down", not s.telnet.connected)
print("ALL PASS" if ok else "SOME FAILED")
print("\n".join(s.logs[-15:]))
os._exit(0 if ok else 1)
