"""0.8.192 (Revolution: the Go to the Spectral Knight "didn't even try to use the required commands to open doors").
The way down: 'push sarcophagus' (6/859 W), then 6/861 down opens with four levers pulled in order in four alcoves
(6/919, 6/921, 6/920, 6/918) — and each alcove is behind a wall a lever in an Ancestral Tomb opens (6/889, 6/917,
6/903, 6/875), behind iron doors — then the searches to 6/993 and 'push button'. On 0.8.188 the walk round the levers
gave up and typed 'd' into 6/861's wall (every start, on the practice server). 0.8.189's nested tours fixed that; this
also covers the iron door at 6/885 failing its bashes: the Go to 'went round' it, the lever behind it out of reach,
and typed 'd' into the wall again. Now the walk round the levers goes back through a door that failed (it's the only
way to that lever), and when a lever really can't be reached it stops and says so instead of walking into the wall."""
import asyncio, os, sys, tempfile, threading, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_spectral"))
from mudpilot import config, simserver
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
DB = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=DB); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w = s.bot, s.world
p = b.pilot
def plan(frm=(6, 835)):
    p.target, p.done, p.prog, p.pending = (6, 994), {}, {}, None
    w.forget_routes()
    return p._build(frm)
def cmds(steps):
    return [(x.room, c) for x in steps or [] for c in (x.pre or [])] + \
           [(x.room, x.move) for x in steps or [] if not x.dir and x.move]
steps = plan()
c = cmds(steps)
check(f"a plan from the Tomb Steps to the Spectral Knight ({len(steps or [])} steps)", steps)
check("…pushes the sarcophagus in 6/859", ((6, 859), "push sarcophagus") in c)
alcoves = [r for r, x in c if x == "pull lever" and r in ((6, 918), (6, 919), (6, 920), (6, 921))]
check(f"…pulls the four alcove levers in order 919, 921, 920, 918 ({alcoves})",
      alcoves == [(6, 919), (6, 921), (6, 920), (6, 918)])
tombs = {r for r, x in c if x == "pull lever" and r in ((6, 889), (6, 917), (6, 903), (6, 875))}
check(f"…after the tomb levers that open each alcove ({sorted(tombs)})", len(tombs) == 4)
check("…pushes the button in 6/993", ((6, 993), "push button") in c)
d861 = [i for i, x in enumerate(steps or []) if x.room == (6, 861) and x.move == "D"]
check("…and goes down 6/861 only after the fourth alcove lever",
      d861 and all(i > max(j for j, x in enumerate(steps) if x.room == (6, 918)) for i in d861))
# the iron door to 6/889's lever failed its bashes a while ago: the walk round still goes through it
w.fail_edge((6, 885), "E")
steps2 = plan()
check(f"6/885 E failed earlier: still planned to the 6/889 lever ({len(steps2 or [])} steps)",
      steps2 and ((6, 889), "pull lever") in cmds(steps2))
w.failed_edges.clear()
# a lever nobody can get to: no plain 'd' into the wall
w.walls = {((6, 885), "E"): time.time() + 3600, ((6, 886), "W"): time.time() + 3600}
steps3 = plan()
check(f"the 6/889 lever out of reach: no plan that walks into 6/861's wall ({steps3 and len(steps3)}, "
      f"{getattr(p, '_untourable', None)})",
      not any(x.room == (6, 861) and x.move == "D" for x in steps3 or []) and getattr(p, "_untourable", None))
w.walls = {}
w.forget_routes()

# ---- walked on the practice server (gates on), after twenty missed bashes 'went round' the iron door
PORT = 2494
real = WorldDB(DB)
sim = simserver.Sim(real, seed=8, mob_rate=0, start=(6, 835), gates={"kit": [1281], "level": 55, "strength": 75})
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
st2.char_class, st2.char_race, st2.char_alignment = "Priest", "Human", "Good"
s2 = Session(st2, world_path=DB); s2.password = "x"; s2._no_log_file = True
s2.on_alert = lambda m: None; s2.on_no_route = lambda m: None
sent = []
_o = s2.send
s2.send = lambda c_, from_bot=False: (sent.append((c_, sim.players[-1].room if sim.players else None)),
                                       _o(c_, from_bot))[1]
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
s2.state.picklocks, s2.state.strength = 182, 60     # ('st' read: 0.8.222 reads it first before a picklocks door)
s2.world.fail_edge((6, 885), "E")
check(f"the walk starts ({s2.bot.goto((6, 994))})", s2.bot.walking)
run(300, lambda: not s2.bot.walking)
pl = sim.players[-1]
check(f"at the Spectral Knight (in {pl.room[0]}/{pl.room[1]}; {s2.bot.status})", pl.room == (6, 994))
done = [r for c_, r in sent if c_ == "pull lever"]
check(f"every lever pulled where it is ({len(done)} pulls)", {(6, 889), (6, 919), (6, 918)} <= set(done))
check("never 'd' typed at 6/861 before the levers", not any(c_ in ("d", "down") and r == (6, 861) and
                                                            sent.index((c_, r)) < sent.index(("pull lever", (6, 918)))
                                                            for c_, r in sent if ("pull lever", (6, 918)) in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.stdout.flush()
os._exit(0 if ok else 1)
