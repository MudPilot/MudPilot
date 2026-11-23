"""0.8.201 bug hunt (party.md, realm_walk.md, walk_maps_*.md): nested errands, bank runs back to the real target,
room commands that aren't spells, room-command exits' items, @stop and two drops in comeback, padded room names,
casters at guards with Combat off, spell-trap pockets, FFFFFFFF path steps and cross-map bridges, targets inside an
avoided area, followers and boss farming, Stop ending a trip, the warehouse door's cost, one invite line, recipe
text, and a target that throws you back out."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_bughunt_walk"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import MPath, Step, path_from_route, resolve_path, step_exit

ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, g, cfg = s.bot, s.world, s.state, s.settings
b.log = lambda m, *a, **k: logs.append(m)
class P:
    def __init__(self, title, loop=False):
        self.title, self.steps, self.is_loop, self.resolved = title, [], loop, True

# --- (1) a fetch inside a fetch keeps the first errand and its Go to
er = b.errands
target, r1, r2 = (8, 951), (8, 689), (8, 300)
outer_mp = P("Go to 8/951 Ancient Stronghold")
er.active = {"todo": [{"num": 111, "kind": "shop", "room": r1, "what": "x", "dist": 1}], "then": (outer_mp, False),
             "started": time.time(), "at": None, "tries": 0, "after": None, "target": target}
b._goto_target = r1
er.source_for = lambda n, *a, **k: {"num": n, "kind": "shop", "room": r2, "what": "y", "dist": 1}
ok1, _why = er.plan(P("Go to 8/689 Guest Quarters"), False, [222])
a = er.active
check("nested fetch: planned", ok1)
check("…the first errand's Go to is kept", a["then"][0] is outer_mp and a["target"] == target)
check(f"…the new item goes first, the first one after ({[t['num'] for t in a['todo']]})",
      [t["num"] for t in a["todo"]] == [222, 111])
b._goto_target = (9, 9)                                  # not the errand's own leg: a fresh errand as before
er.plan(P("Go to 9/9 Somewhere"), False, [333])
check("a walk that isn't the errand's leg starts its own errand", [t["num"] for t in er.active["todo"]] == [333])
er.active = None
del er.source_for

# --- (2) a bank run for an item goes back to the Go to's target, not the bank
bank = (6, 1334)
class Trips:
    trip = None
    def withdraw_for(self, mp, loop, short, why=""):
        b._goto_target = bank                            # what the real withdraw_for's goto(bank) does
        self.trip = {"kind": "withdraw", "back": (mp, loop)}
        return True
real_trips, s.trips = s.trips, Trips()
a = {"todo": [], "then": (P("Go to 17/2601 Zombie Pen"), False), "target": (17, 2601), "after": None}
num = next(iter(w.items))
er._bank_for({"num": num, "room": (1, 1)}, a)
check(f"bank run: back to the Go to's target ({s.trips.trip.get('goto')})", s.trips.trip.get("goto") == (17, 2601))
s.trips = real_trips

# --- (3) room commands aren't spells
check("('jump' does resolve to some MME spell world-wide — the test means something)", s.spellbook.find("jump"))
g.char_class, g.level = "Mage", 55
for c_ in ("jump north", "dive moat", "light torch"):
    b.send(c_)
    check(f"'{c_}' isn't counted as a spell", b._last_cmd == (c_, False))
cfg.attack_spells = ["mmis"]
b.send("mmis rat")
check("an attack spell of yours still is", b._last_cmd[1] is True)
b.send("cast mmis rat")
check("…and 'cast <spell>'", b._last_cmd[1] is True)
cfg.attack_spells = []

# --- (4) a room-command exit's item is seen by the needed-items check
ex = w.room((1, 816)).exits["@dig grave"]
mp = path_from_route(w, (1, 816), [ex], name="Go to 1/9462")
check("step_exit finds the '@dig grave' exit from the step's command", step_exit(w, mp.steps[-1]) is ex)
check(f"path_needs: the shovel ({b.path_needs(mp)})", any(n == 1415 for n, _s in b.path_needs(mp)))

# --- (5) a member's @stop ends the comeback fetch
c = s.comeback
b.x._own_party = True
g.party = {"Miserable": {}, "Revolution": {}, "Buddy": {}}
loop = P("Stonecaps loop", True)
c.fetch = {"name": "Revolution", "phase": "going", "room": (14, 6559), "back": (loop, True), "t": time.time() - 40}
c.missing = {"Revolution": {"t": time.time() - 40, "why": "left behind"}}
b.walking = False
starts = []
real_sp = b.start_path
b.start_path = lambda mp, loop=None, checked=False: starts.append(mp.title)
s.remote.c_stop("Revolution", "")
check("@stop from the member: no fetch left", c.fetch is None and not c.missing)
c.tick()
check("…and the loop doesn't restart by itself", not starts)

# --- (6) two members drop at once: the second isn't lost
c.reset()
c.away.clear()
c._self_left = 0
b._user_stop_at = 0
b.portal_cmd_just_sent = lambda: False
c._ask_where("Revolution")
c.missing["Revolution"] = {"t": time.time(), "why": "left behind"}
c.feed_line("Buddy is no longer following you.")
check(f"Buddy stopped following mid-fetch: noted ({list(c.missing)}, {c.__dict__.get('queued')})",
      "Buddy" in c.missing and "Buddy" in (c.__dict__.get("queued") or []))
sent.clear()
c._finish()
check(f"after Revolution, Buddy is fetched ({c.fetch and c.fetch['name']})", c.fetch and c.fetch["name"] == "Buddy")
c.reset()
c._ask_where("Revolution")
c._ask_where("Buddy")                                    # his @comeback while Revolution is being fetched
c._finish()
check(f"queued by a second @comeback: fetched afterwards ({c.fetch and c.fetch['name']})",
      c.fetch and c.fetch["name"] == "Revolution")
c.reset()
b.start_path = real_sp

# --- (7) room names padded with spaces
check(f"17/2247's name is stripped ({w.room((17, 2247)).name!r})", w.room((17, 2247)).name == "mausoleum Labyrinth")
check("…and found by the name the game shows", (17, 2247) in w.by_name.get("mausoleum labyrinth", []))

# --- (8) a caster that can't cast (Combat off) swings at a guard
from mudpilot.spells import is_attack_spell
sp_ = next(x for x in w.spells.values() if is_attack_spell(x) and x.get("Short"))
s.full_caster = lambda: True
s.known_spell_dicts = lambda: [sp_]
cfg.attack_spells, cfg.auto_spells = [sp_["Short"]], True
g.level = 60
mon = {"num": next(iter(w.monsters)), "name": "deranged priest"}
cfg.auto_combat, cfg.auto_nuke = True, False
check("Combat on: the level-60 caster doesn't melee", b._no_melee(mon))
cfg.auto_combat = False
check("Combat off (no spell can go out): it may swing", not b._no_melee(mon))
cfg.attack_spells = []

# --- (10) a spell-trap pocket isn't a one-way trap
s.route_char()
w.char = dict(w.char or {}, spell_traps=False)
w.forget_routes()
check("15/357 SW is a spell trap (map data)", w.room((15, 357)).exits["SW"].kind == "restricted")
out = w.route((15, 357), (15, 356), level=55, have=set())
check(f"traps off: still a way out when there's no other ({out and len(out)})", out is not None)

# --- (11) MegaMUD 'FFFFFFFF' steps, (9) cross-map bridges aren't learned
pair = None
for k, r in w.rooms.items():
    e = r.exits.get("N")
    if not e or e.kind != "normal" or len(w.by_hash.get(r.mega_hash, [])) != 1:
        continue
    r2 = w.room(e.to)
    back = r2.exits.get("S") if r2 else None
    if back and back.kind == "normal" and back.to == k and len(w.by_hash.get(r2.mega_hash, [])) == 1:
        pair = (k, e.to)
        break
A, B = pair
hA, hB = w.room(A).mega_hash, w.room(B).mega_hash
mpf = MPath(name="t", author="", start_hash=hA, end_hash=hA,
            steps=[Step(hA, 0, "N"), Step("FFFFFFFF", 0x80, "hide 500 gold"), Step(hB, 0, "S")])
check(f"FFFFFFFF step: the path resolves ({mpf.resolve_note if resolve_path(w, mpf) else 'not resolved'})",
      mpf.resolved and mpf.steps[1].room == B and mpf.steps[1].dest == B)
learned = []
real_add = w.add_learned
w.add_learned = lambda *a_: learned.append(a_)
mpb = MPath(name="", author="", start_hash="DCE00004", end_hash="X",
            steps=[Step("DCE00004", 0, "raise idol"), Step("DCE00005", 0, "N")])
resolve_path(w, mpb, hint=(3, 817))
check(f"3/817 'raise idol' isn't learned as a move to another map ({learned})",
      not any(m == "raise idol" for _a, m, _b in learned))
w.add_learned = real_add

# --- (12) a target inside an avoided area
av = b.avoid_set()
npp = [k for k in av if w.room(k).name == "Negative Power Plane"]
bw = [k for k in av if w.room(k).name.startswith("Black Wasteland")]
af = b.avoid_for((8, 958))
check("avoid_for 8/958: the target's own area isn't avoided", (8, 958) not in af and not (set(npp) & set(af)) if npp else False)
check("…Black Wasteland still is", bw and set(bw) <= set(af))
check("a target outside: unchanged", b.avoid_for((1, 1)) == av)

# --- (14) a follower doesn't farm bosses by itself
due = []
bh = s.bosshunt
bh.due = lambda: due.append(1) or []
cfg.boss_farm_on, cfg.boss_hunt_on = True, True
b.x._own_party, b.x._following = False, "Revolution"
b.walking, b.status = False, "Idle"
g.party = {}
g.in_combat = False
bh.tick()
check("follower: no boss farming", not due)
b.x._following = None
bh.tick()
check("…the leader does look for one (control)", due)
cfg.boss_farm_on = cfg.boss_hunt_on = False

# --- (15) Stop ends a shop/bank trip
s.trips.trip = {"kind": "withdraw", "room": bank, "cmds": [], "back": (loop, True), "t": time.time(), "phase": "doing",
                "next_at": 0, "why": "x"}
b.stop("Stopped by you")
check("Stop: the trip is cancelled", s.trips.trip is None)

# --- (16) warehouse door, one invite line, recipe text, a target that throws you out
d = w.room((1, 1104)).exits["N"]
# (0.8.223: the board fix gives it 'use crowbar' (item 570) — an item exit now, not a stuck '1000' door)
check(f"1/1104 N opens with 'use crowbar' now ({d.action_cmds()})", any("crowbar" in c for c in d.action_cmds()))
cfg.my_name = "Revolution"
cfg.remote_players = {"Miserable": {"party": True}}
b.walking, b.loop, b.path = True, True, loop
s._rejoin = None
b.x._followed = None
sent.clear()
s.remote.note_invite("Miserable has invited you to follow him.")
s.remote.keep_my_loop("Miserable")                       # the same line through the other join rule
check(f"one invite line: invite only, no join ({sent})", "invite Miserable" in sent and not any(x.startswith("join") for x in sent))
cfg.my_name = "Miserable"
b.walking = False
rroom = (16, 1517)
real_rf = getattr(w, "recipe_for", None)
w.recipe_for = lambda n: {"needs": [], "room": rroom, "cmds": ["pray"], "nomonsters": False}
todo = er._recipe_todo(num, set())
check(f"a recipe with no parts: '{todo[-1]['what']}'", todo[-1]["what"].startswith("get it at ") and "the  in" not in todo[-1]["what"])
if real_rf is not None:
    w.recipe_for = real_rf
p = b.pilot
stops = []
b.stop = lambda why="": stops.append(why)
b._drifted = lambda *a_: False
p._build = lambda here_: None
b.goto = lambda *a_, **k_: True
p.target, p.last = (17, 2978), {"dest": (17, 2978)}
p._replan((17, 2980), True)
check("thrown out of the target once: tries again", not stops)
p.last = {"dest": (17, 2978)}
p._replan((17, 2980), True)
check(f"twice: stops and says why ({stops})", stops and "sends you back out" in stops[-1])

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
