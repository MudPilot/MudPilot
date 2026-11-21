"""A Go to arriving or a loop starting turns Combat and Heal back on, even if they were off on the way — never Nuke
(Dan, 2026-11-02: "Combat should be, nuke shouldnt"; every Go to had turned Evolution's Nuke back on)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
s.telnet.send_line = lambda c: None
b, g, w = s.bot, s.state, s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
a = w.by_name["rotting glade, trail"][0]
nxt = next(ex.to for ex in w.rooms[a].exits.values() if ex.to in w.rooms)

def trip(during=None):
    g.candidates = [a]
    assert b.goto(nxt), b.no_route_msg
    if during:
        during()
    g.candidates = [nxt]
    b.idx = len(b.path.steps)
    g.pending.clear()
    b._step_sent_at = time.time() - 60
    b.walk([], False)

st.auto_nuke, st.auto_combat, st.auto_heal = False, False, False
trip()
check(f"arrived: Combat and Heal on ({st.auto_combat}, {st.auto_heal})", st.auto_combat and st.auto_heal
      and str(b.status).startswith("Arrived"))
check(f"…Nuke still off ({st.auto_nuke})", st.auto_nuke is False)
st.auto_combat = st.auto_heal = False
from mudpilot.megamud_files import path_from_route
g.candidates = [a]
loop = path_from_route(w, a, w.route(a, nxt), name="Test loop")
b.stop("test")
b.start_path(loop, loop=True, checked=True)
check(f"loop started: Combat and Heal on, Nuke off ({st.auto_combat}, {st.auto_heal}, {st.auto_nuke})",
      st.auto_combat and st.auto_heal and st.auto_nuke is False)
st.arrive_auto_on = False; st.auto_combat = st.auto_heal = False
b.stop("test"); b.start_path(loop, loop=True, checked=True)
check("option off: a loop still fights (Dan, 2026-11-20), Heal stays off", st.auto_combat is True and st.auto_heal is False)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
