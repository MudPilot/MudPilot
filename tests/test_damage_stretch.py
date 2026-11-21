"""0.8.190 (Dan, "weigh by HP + rest first"): before a long stretch of rooms that hurt you (Volcano magma at up to
60 a room, a bog, a river without a raft), the walk rests to full first when what it has wouldn't see it through
above the hang-up line (the realm walk sweep hung up in the Volcano tunnels at 25% HP). A raft keeps the river off."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_damage_stretch"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55; st.auto_rest = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, w, g = s.bot, s.world, s.state
raft = next(n for n, it in w.items.items() if it.get("name") == "log raft")
river = next(k for k, sp in w.room_spells.items() if (w.spells.get(sp) or {}).get("Name") == "river damage")
check(f"a river room hurts without a raft ({w.room_damage(river)})", w.room_damage(river) > 0)
check(f"…and not with one ({w.room_damage(river, {raft})})", w.room_damage(river, {raft}) == 0)
r = w.route((16, 9505), (16, 2692))
magma = sum(1 for x in r or [] if w.room_damage(x.to))
check(f"16/9505 → 16/2692: {len(r or [])} rooms of magma ({magma})", r and magma == len(r))
mp = path_from_route(w, (16, 9505), r or [], name="Go to 16/2692")
b.path, b.idx = mp, 0
g.max_hp, g.hp, g.level = 715, 715, 55
dmg, what = b._stretch_damage()
check(f"the stretch ahead adds up ({dmg} — {what})", dmg >= 60 * magma - 1 and "rooms that hurt" in what)
g.hp = 500
held = b._hurt_ahead(mp.steps[0])
check(f"at 500/715 HP: rest to full first ({held}, {logs[-1:]})", held and b._danger_hp == 100)
b._danger_hp = 0
g.hp = 715
check("at full HP: go (resting won't make it smaller — said once)",
      not b._hurt_ahead(mp.steps[0]) and any("going on" in l for l in logs))
b.path, b.idx = mp, 1
g.hp = 300
check("already in the magma (step 2): no sitting down in it — on out", not b._hurt_ahead(mp.steps[1]))
short = path_from_route(w, (16, 9505), (r or [])[:1], name="Go to one room")
b.path, b.idx = short, 0
g.hp = 600
check("one magma room at 600/715 HP: no stop for that", not b._hurt_ahead(short.steps[0]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
