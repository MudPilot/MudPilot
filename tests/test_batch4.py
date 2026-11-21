"""0.8.26: danger check, loop builder, advisor, gear watch, party sync, curse opener, timeline/death replay, sync."""
import os, sys, time, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import path_from_route
from mudpilot.danger import lair_spawn
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_rest = True; st.auto_combat = False; st.auto_bless = False; st.auto_spells = False
s = Session(st); b = s.bot; w = s.world
s._no_log_file = True
_tmp = tempfile.mkdtemp()
config.board_dir = lambda bd: os.path.join(_tmp, bd)
s.lairclock._for = s.history._for = None
sent, alerts = [], []
s.notify.send = lambda kind, msg, force=False: alerts.append((kind, msg))
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 684, 684, 473, 473
s.state.level = 30; st.char_level = 30

# a lair with hostile, exp-worth monsters, reachable from a neighbour
lair = None
for k, r in w.rooms.items():
    n, mons = lair_spawn(w, k)
    if n and mons and any(m["exp"] > 0 and b.hostile(m) for m in mons) and k[0] == 1:
        nb = next((ex.to for ex in r.exits.values() if ex.to in w.rooms and w.route(ex.to, k) and w.route(k, ex.to)), None)
        if nb:
            lair, before = k, nb
            break
check(f"found a test lair {lair}", lair is not None)

# ---- danger: learns from fights, rests to the needed HP only once it has real numbers
dg = s.danger
for lost in (300, 320, 310):
    dg.observe(lair, lost)
need, a = dg.needed_pct(lair)
check(f"observed: needs ~{need:.0f}% HP ({a})", a and a.get("observed") and 60 < need < 100)
lp = path_from_route(w, before, w.route(before, lair) + w.route(lair, before), name="L")
s.state.candidates = [before]; s.state.view = RoomView("x", {"N"}); s.state.view.t = time.time()
b.start_path(lp, loop=True, checked=True)
step = next(x for x in lp.steps if x.dest == lair)
s.state.hp = int(684 * 0.5)
check("hurt + dangerous lair next → holds to rest", b._danger_ahead(step, []) and b._danger_hp > 60)
b._cool = {}
check("should_rest now rests", b.should_rest([], True))
s.state.hp = 684; b._danger_hp = 0; s.state.resting = False
check("full HP → walks in", not b._danger_ahead(step, []))
# unobserved lair → heads-up only
lc = s.lairclock
lc.data.get(lc.key(lair), {}).pop("dmg", None)
s.state.hp = 300
check("MME numbers only → never a forced rest", not b._danger_ahead(step, []))
s.state.hp = 684
b.stop("Stopped by you")

# ---- loop builder
s.state.candidates = [before]
cands = s.loopbuilder.build(before, 40)
check(f"built {len(cands)} loop(s)", cands and all(c["route"] and c["lairs"] for c in cands))
c0 = cands[0]
rooms = [before]
for ex in c0["route"]:
    rooms.append(ex.to)
check("built loop ends where it starts", rooms[-1] == before)
mp = s.loopbuilder.save(c0, "Test built loop")
check("saved as a loop path", mp.is_loop and os.path.exists(mp.filename) and mp in s.paths)

# ---- advisor
ls = s.loopstats
ls._loaded_for = st.board
ls.data = {"l.mp": {"title": "L", "by": {"miserable": [{"t": i, "secs": 300, "exp": 50000 if i < 10 else 30000, "kills": 10,
                                                        "rests": 2, "deaths": 0, "level": 30, "lairs_full": 2,
                                                        "lairs_empty": 6} for i in range(20)]}},
           "o.mp": {"title": "Other loop", "by": {"miserable": [{"t": i, "secs": 300, "exp": 90000, "kills": 10, "rests": 1,
                                                                 "deaths": 0, "level": 31, "lairs_full": 5,
                                                                 "lairs_empty": 1} for i in range(5)]}}}
lp.filename = "/x/l.mp"
adv = s.advisor.advise(lp, build=False)
check(f"advice: better loop named", any("Other loop" in x for x in adv))
check("advice: trend down", any("less than 10 laps ago" in x for x in adv))
check("advice: empty lairs", any("empty" in x for x in adv))

# ---- gear watch
gw = s.gearwatch
g = next((g for g in w.gear.values() if int(g.get("ItemType") or 0) == 0 and int(g.get("Worn") or 0) == 11
          and (int(g.get("ArmourClass") or 0) >= 40) and not g["abils"].get(135) and not g.get("classes")), None)
s.state.carrying = ""
check("quiet until it has seen the inventory", gw.upgrade(g["name"]) is None if g else True)
s.state.carrying = "torch"
st.gear_min_gain = 0.5
up = gw.upgrade(g["name"]) if g else None
check(f"upgrade spotted ({g and g['name']})", up and up[1] == "Torso")
s.state.carrying = f"{g['name']} (Torso)"
check("not when already wearing it", gw.upgrade(g["name"]) is None)
s.state.carrying = "torch"
alerts.clear()
s.state.view = RoomView("x", {"N"}, items=[(1, g["name"])]); s.state.candidates = [before]
on_alerts = []
s.on_alert = lambda m: on_alerts.append(m)
gw.on_room(s.state)
check(f"alert said ({on_alerts[-1] if on_alerts else ''})", on_alerts and "Upgrade" in on_alerts[-1])

# ---- party sync
ps = s.partysync
s.state.party = {"Miserable": {"hp": 100, "ma": 100, "t": time.time()}, "Revolution": {"hp": 90, "ma": 50, "t": time.time()}}
st.party_sync = True
sent.clear(); ps.asked = set(); ps.tick()
check(f"hello sent once, with our level ({sent})",
      len(sent) == 1 and sent[0].startswith("/Revolution @mpsync hi tune"))
check("hi → answer", ps.command("Revolution", "hi").startswith("mpsync ok"))
ps.peers = {}
ps.answer("Revolution", "{mpsync ok 0.8.26}")
check("peer known", "Revolution" in ps.peers)
ps.command("Revolution", "st r=1 h=60 m=30")
check("peer resting seen", ps.peer_resting() == "Revolution")
s.state.hp = 600; b.walking = False; s.state.resting = False
s.state.view = RoomView("x", {"N"}); s.state.view.t = time.time()
sent.clear(); b._cool = {"par": time.time(), "par_solo": time.time()}; b.tick()
check(f"rests with them ({sent})", any(c in ("rest", "medi", "meditate") for c in sent))
s.state.resting = True; b._idle_rest = True
check("stays down while they rest", b.should_rest([], True))
ps.command("Revolution", "st r=0 h=100 m=100")
check("gets up when they do", not b.should_rest([], True))
s.state.resting = False; s.state.party = {}

# ---- dangerous fight opener
st.auto_combat = True; st.danger_opener_spell = "mist"; st.danger_opener_mobs = 3; st.attack_spells = []
rec = next(m for m in w.monsters.values() if m["exp"] > 0 and int(m.get("align") or 0) in (1, 2, 5, 6))
mobs = [(rec["name"], rec)] * 3
s.state.view = RoomView("y", {"N"}, monsters=mobs); s.state.view.t = time.time(); s.state.in_combat = False
b._risky = None; b._danger_open_done = False; b._cool = {}; sent.clear()
b.fight(mobs)
check(f"3 monsters → mist first ({sent})", sent and sent[0].startswith("mist"))
sent.clear(); b._cool = {}
b.fight(mobs)
check(f"…then the attack ({sent})", sent and not sent[0].startswith("mist"))
b._risky = None; b._danger_open_done = False; sent.clear(); b._cool = {}
b.fight(mobs[:1])
check(f"1 easy monster → no curse ({sent})", not any(c.startswith("mist") for c in sent))
st.auto_combat = False; st.danger_opener_spell = ""

# ---- timeline + death replay
tl = s.timeline
config.DATA_DIR = tempfile.mkdtemp()
tl._last_t = 0; tl.tick()
check("timeline segment recorded", tl.segs and tl.segs[-1][2] in ("idle", "walking", "fighting", "resting", "waiting"))
now = time.time()
tl.screen.extend([(now - 20, "*Combat Engaged*"), (now - 15, "The orc smashes you for 120 damage!"),
                  (now - 10, "The orc smashes you for 200 damage!"), (now - 2, "You are dead.")])
tl.hp.clear()
tl.hp.extend([(now - 20, 400, 684, 300, 473), (now - 15, 280, 684, 300, 473), (now - 10, 80, 684, 300, 473)])
rec = tl.death_replay(now)
check(f"death replay: hits {rec['by']}", rec["by"].get("orc") == 320)
check(f"tips ({rec['tips'][0][:50]})", rec["tips"] and any("started at" in t or "round did" in t for t in rec["tips"]))
from mudpilot.timeline import load_deaths
check("saved for the Deaths window", load_deaths() and load_deaths()[0]["by"].get("orc") == 320)

# ---- sync between two "PCs"
from mudpilot import sync as SY
A, B, SHARE = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
def setup(d, laps, prof):
    os.makedirs(os.path.join(d, "boards", "Main"), exist_ok=True)
    os.makedirs(os.path.join(d, "profiles"), exist_ok=True)
    json.dump({"k.mp": {"title": "K", "by": {"m": laps}}}, open(os.path.join(d, "boards", "Main", "loop_stats.json"), "w"))
    json.dump(prof, open(os.path.join(d, "profiles", "Miserable.json"), "w"))
    json.dump({"x": 1}, open(os.path.join(d, "boards", "Main", "world.db"), "w"))
setup(A, [{"t": 1, "exp": 5}], {"rest_below_hp": 70})
time.sleep(1.1)
setup(B, [{"t": 2, "exp": 7}], {"rest_below_hp": 55})
pf = os.path.join(A, "profiles", "Miserable.json"); os.utime(pf, (time.time() - 600, time.time() - 600))
def run_sync(d, startup):
    config.DATA_DIR = d
    config.PROFILES_DIR = os.path.join(d, "profiles")
    SY.LOCAL_STATE = os.path.join(d, "sync.json")
    sy = SY.Sync(s); sy.set_folder(SHARE)
    s.settings.profile = "Miserable"
    sy._flush = lambda: None; sy._reload = lambda c: None
    return sy.sync_now(startup=startup)
print("  A:", run_sync(A, True)); print("  B:", run_sync(B, True)); print("  A:", run_sync(A, True))
la = json.load(open(os.path.join(A, "boards", "Main", "loop_stats.json")))["k.mp"]["by"]["m"]
lb = json.load(open(os.path.join(B, "boards", "Main", "loop_stats.json")))["k.mp"]["by"]["m"]
check(f"loop stats merged on both PCs ({len(la)}, {len(lb)})", len(la) == 2 and len(lb) == 2)
pa = json.load(open(os.path.join(A, "profiles", "Miserable.json")))
check(f"newest settings won ({pa})", pa["rest_below_hp"] == 55)
check("map data never synced", not os.path.exists(os.path.join(SHARE, SY.SUB, "boards", "Main", "world.db")))
check("replaced file backed up", os.path.isdir(os.path.join(A, "sync_backup")))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
