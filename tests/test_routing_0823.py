"""0.8.223 (Dan's answers to HUNT_1121 'For Dan' 8, 9, 10, 12, 15): routing.
- rooms that hurt are costed in route(), weighed by your HP: the L30 thief takes the dry way round the Quagmire (m14c);
- a stretch of rooms that hurt for your whole max HP is walked round, or the Go to stops and names it (Lava Tube, m1315 R6);
- a big character still takes the short way through a bog that only scratches it."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.char_level = 55; st.my_name = "Tester"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = T(); s._entered = True
s.on_no_route = lambda m: None
w, b, g = s.world, s.bot, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def plan(a, z, hp, lvl=30, carried=()):
    w.char = dict(w.char or {}, max_hp=hp, hangup_pct=30, carried=frozenset(carried), gate_any=False)
    w.forget_routes()
    w.stretch_blocks = {}
    return w.route(a, z, level=lvl, have=set(carried))

def dmg(r):
    return sum(w.room_damage(e.to, ()) for e in r or ())

saved = dict(w.char or {})
try:
    r = plan((14, 9486), (14, 1388), 390)
    check(f"L30 thief (390 HP) round the Quagmire: {len(r or [])} steps, {dmg(r)} damage", r and dmg(r) < 400)
    r = plan((14, 2097), (14, 9956), 390)
    check(f"L30 thief 14/2097 -> 14/9956: {len(r or [])} steps, {dmg(r)} damage (was 204 / 2,500)", r and dmg(r) < 500)
    r = plan((15, 1137), (15, 1137), 533)
    # the Lava Tube trip: from outside the hot rooms
    src = (7, 995) if (7, 995) in w.rooms else None
    if src:
        r = plan(src, (15, 1137), 533, lvl=41)
        sb = list((w.stretch_blocks or {}).values())
        why = w.why_no_route(src, (15, 1137), level=41, have=set()) if r is None else []
        check(f"0.8.224.2 (Dan): Lava Tube with 533 HP: walked, no wall ({len(r or [])} steps)", r is not None)
        r = plan(src, (15, 1137), 2700, lvl=41)          # (0.8.224: the limit is the hang-up line — 1800 needs 2700 at 30%)
        check(f"Lava Tube with 2700 HP: walks ({len(r or [])} steps)", r is not None)
    t = time.time()
    for a, z in [((1, 1), (14, 1388)), ((1, 1), (15, 416)), ((1, 1), (8, 560))]:
        plan(a, z, 390, lvl=30)
    check(f"three long plans in {time.time() - t:.1f}s", time.time() - t < 20)

    # --- whole Go tos (session) ---
    logs = []
    b.log = lambda m, *a, **k: logs.append(str(m))
    def go(here_, tgt, lvl=30, pick=40, strg=80, carrying="torch", hp=500):
        b.stop("Stopped by you"); b.errands.cancel(); s.trips.reset("t"); b._pending_abil = None
        g.candidates = [here_]; g.level = lvl; st.char_level = lvl; g.picklocks, g.strength = pick, strg
        g.max_hp = g.hp = hp; g.max_hp_read = True
        g.carrying = carrying; g.keys = ""; g.inv_seq += 1; w.forget_routes(); b.no_route_msg = ""
        b._flags_reread = {tuple(tgt): time.time()}
        logs.clear()
        r = b.goto(tgt)
        return r, b.walking, b.no_route_msg or "", (len(b.path.steps) if b.path and b.walking else 0)
    
    b.send = lambda *a, **k: None
    # 15: a way blocked only by rooms that hurt: no look-alike-room / alignment searches, and the reason given
    if (7, 995) in w.rooms:
        calls = []
        rt0, al0 = b._reachable_twin, b._align_is_the_block
        b._reachable_twin = lambda *a, **k: calls.append("twin") or rt0(*a, **k)
        b._align_is_the_block = lambda *a, **k: calls.append("align") or al0(*a, **k)
        try:
            t = time.time()
            r = go((7, 995), (15, 1137), lvl=41, hp=533)
        finally:
            b._reachable_twin, b._align_is_the_block = rt0, al0
        check(f"0.8.224.2: Go to the Lava Tube at 533 HP: walked, no twin search ({calls}, {time.time() - t:.1f}s)",
              r[1] and not calls)
    # 9: the jail cell — a thief picks the 101 door in, can't pick the 151 door out, the jail key drops outside
    r = go((1, 1), (1, 541), lvl=30, pick=150, strg=45)
    check(f"jail cell 1/541 with picklocks 150: refused up front ({r[2][:110]})", not r[1] and "back out" in r[2])
    r = go((1, 1), (1, 541), lvl=30, pick=160, strg=45)
    check(f"jail cell 1/541 with picklocks 160: walks ({r[:2]}, {r[2][:80]})", r[1])
    # 10: in by a key door, out through its other side (typed '(Door [71 picklocks/strength])'): the same door
    jk = w.exit_need(w.rooms[(16, 2117)].exits["W"])[0] if (16, 2117) in w.rooms and "W" in w.rooms[(16, 2117)].exits else None
    if jk:
        out = w.rooms[(16, 2118)].exits.get("E")
        check(f"Fiery Lair 16/2118 E is the key door's other side (key twin {w.key_twin(out) is not None})",
              out is not None and w.key_twin(out) is not None)
        w.char = dict(w.char, door_power=(0, 40))
        check("…and opens with that key in hand", w.door_beaten(out, {jk}) is True and w.door_beaten(out, set()) is not True)
        r = go((16, 2117), (16, 2118), lvl=60, pick=0, strg=40, carrying=w.item_name(jk))
        check(f"Go to the Fiery Lair with its key, strength 40: walks ({r[:2]} {r[2][:90]})", r[1])
        r = go((16, 2118), (16, 2117), lvl=60, pick=0, strg=40, carrying=w.item_name(jk))
        check(f"…and back out with the key ({r[:2]} {r[2][:90]})", r[1])
    # 12: a key door your strength beats, 106 rooms round vs ~10 through it (1/1098 W, '[or 41 picklocks/strength]')
    r = go((1, 896), (1, 2339), lvl=30, pick=0, strg=75)
    check(f"1/896 -> 1/2339 with strength 75: the short way through the key door ({r[3]} steps)",
          (r[1] and 0 < r[3] < 40) or any("beats walking round" in l for l in logs))
    r = go((1, 896), (1, 2339), lvl=30, pick=0, strg=20)
    check(f"…with strength 20: walks round ({r[3]} steps)", (not r[1]) or r[3] > 40)
    
finally:
    w.char = saved; w.forget_routes()
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
