"""Revolution, 2026-10-30: 'go hole' typed again and again in 2/193 Dragon's Teeth Hills — "Your command had no effect."
Five rooms there look exactly like 2/487, where the hole is (same name, exits, MegaMUD hash); the walk had drifted
onto a look-alike. Walks through the hole on the practice server: plain ones from a few rooms around it, and the
drifted one (in 2/193, the tracker sure it's 2/487) — it must check with 'pro' and walk to the real hole."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
PORT = 2447
HOLE, BELOW = (2, 487), (2, 1306)
sim = simserver.Sim(world, seed=4, mob_rate=0, start=(2, 543))


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
st.auto_reconnect = False; st.auto_combat = False; st.char_level = 55
s = Session(st); s.password = "x"; s._no_log_file = True
s.connect()
sent = []
_o = s.send
s.send = lambda c, from_bot=False: (sent.append(c), _o(c, from_bot))[1]
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
s.state.level = 55
p = sim.players[-1]


def walk(start, label, fake=None):
    p.room = start
    s.bot.stop("test")
    s.send("pro")
    run(4, lambda: s.state.room == start)
    if fake:
        s.state.candidates = [fake]                      # the tracker has drifted onto a look-alike
        s.state.located = None
    sent.clear()
    started = s.bot.goto(BELOW)
    run(180, lambda: p.room == BELOW and not s.bot.walking)
    tries = sent.count("go hole")
    check(f"{label}: {start[0]}/{start[1]} → through the hole to {BELOW[0]}/{BELOW[1]} "
          f"(true room {p.room}, 'go hole' sent {tries}x)", started and p.room == BELOW and tries <= 2)


for k in [(2, 543), (2, 486), (2, 488), (2, 290)]:
    walk(k, "walk")
walk((2, 193), "drifted onto a look-alike", fake=HOLE)
print("\n".join(x for x in s.logs[-30:] if "pro" in x or "look" in x or "no effect" in x or "Arrived" in x))
print("ALL PASS" if ok else "SOME FAILED")
os._exit(0 if ok else 1)
