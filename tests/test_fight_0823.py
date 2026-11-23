"""0.8.223, fights from the 2026-11-21 bug hunt (HUNT_1121.md "For Dan" 4-7, Dan approved):
4. ran from the same monster in the same room twice: too strong for 30 minutes — routes go round the room, the monster
   isn't attacked unless it starts it, a Go to that room isn't started by anything but you (fight3 #2).
5. our move lands in another room: 'in combat' is cleared (nothing there) or cleared a few seconds on when nothing
   there hits us (m1018 #2b).
6. a guard / an item dropper gets the 'can I win this?' check (m349 #5 the ancient willow, m149 N1 Sheriff Lionheart).
7. a walk started after Stop rests again (m1315 R4); a level-50+ caster out of mana backs off a room and rests
   (m1617c N1)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55; st.say_panic = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent, logs = [], []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
s.on_no_route = lambda m: None
_log = s.log
s.log = lambda m, *a, **k: logs.append(m)
w, b, g = s.world, s.bot, s.state
g.inv_at = float("inf")
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# ---------------------------------------------------------------- 4. twice from the same monster
room = (1, 364)
r = w.room(room)
check("1/364 is on the map", r is not None and r.exits)
mob = next((m for m in w.monsters.values() if m.get("exp", 0) > 0 and m.get("name")), None)
shown = {d for d, ex in r.exits.items() if ex.visible} or set(r.exits)
g.candidates = [room]; g.max_hp, g.hp = 130, 40
g.view = RoomView(r.name, set(shown), [(mob["name"], mob)])
b.flee()
check("one run: not marked", room not in b.too_strong_rooms())
g.candidates = [room]; b._cool.clear()
g.view = RoomView(r.name, set(shown), [(mob["name"], mob)])
logs.clear(); b.flee()
check(f"second run from the {mob['name']} there: too strong ({logs[-1][:100] if logs else ''})",
      room in b.too_strong_rooms() and any("too strong" in m for m in logs))
check("…the room is kept out of routes", room in (w.user_avoid or ()))
g.in_combat = False; b._attacked_at = 0; b._aggro = {}
g.view = RoomView(r.name, set(shown), [(mob["name"], mob)])
check("…and the monster isn't attacked unless it starts it", not any(rr is mob for _s, rr in b.attackable()))
g.in_combat = True
check("…but fought back when it's on us", any(rr is mob for _s, rr in b.attackable()) or not b.hostile(mob))
g.in_combat = False
other = next(tuple(ex.to) for ex in r.exits.values() if ex.to)
g.candidates = [other]; logs.clear()
res = b.goto(room)          # (started from here, a test: not you — like an errand leg)
check(f"a Go to that room started by anything but you: refused, says why ({b.no_route_msg[:90]})",
      res is False and "too strong" in b.no_route_msg)
b._too_strong[room] = (time.time() - 1, mob["name"])
check("30 minutes on: forgotten", room not in b.too_strong_rooms())
# the pilot: re-planning to a target we ran from twice stops with the reason
b._too_strong = {room: (time.time() + 1800, mob["name"])}
stops = []
real_stop = b.stop
b.stop = lambda why="Stopped": stops.append(why)
b.pilot.target = room; b.pilot.last = None
b.pilot._replan(other, False)
b.stop = real_stop
check(f"pilot re-plan into it: stops, naming the monster ({stops[-1][:100] if stops else None})",
      stops and mob["name"] in stops[-1] and "not going back" in stops[-1])
b._too_strong = {}
b.pilot.target = None

# ---------------------------------------------------------------- 5. stale 'in combat' after our own move
g.in_combat = True
g.view = RoomView("Somewhere", {"N"}, [])
g._moved_in((1, 1))
check("move into an empty room: not in combat any more", g.in_combat is False)
g.in_combat = True; g.combat_on_at = time.time() - 30
g.view = RoomView("Somewhere", {"N"}, [(mob["name"], mob)])
g.candidates = [(1, 1)]
g._moved_in((1, 1))
check("monsters there: still in combat for now", g.in_combat is True)
b._attacked_at = 0; b._aggro = {}
b._stale_combat(time.time() + 2)
check("…2 s on, nothing hit: still in combat", g.in_combat is True)
b._stale_combat(time.time() + 7)
check("…7 s on, nothing hit us: cleared", g.in_combat is False)
g.in_combat = True; g._moved_in((1, 1)); b._attacked_at = time.time() + 1
b._stale_combat(time.time() + 7)
check("…hit since we came in: stays in combat", g.in_combat is True)
b._attacked_at = 0; g.in_combat = False
# through the real room tracking: a move north that lands in the next room
src = next(k for k, x in w.rooms.items() if "N" in x.exits and x.exits["N"].kind == "normal" and x.exits["N"].to in w.rooms
           and not w.look_alike(x.exits["N"].to) and not w.look_alike(k))
dst = w.rooms[src].exits["N"].to
g.candidates = [src]; g.history = [src]; g.in_combat = True
dshown = {d for d, ex in w.rooms[dst].exits.items() if ex.visible}
g.view = RoomView(w.rooms[dst].name, dshown, [])
g._locate(("move", "N", [src]), w.rooms[dst].name, dshown)
check(f"a real move {src} → {g.room}: 'in combat' cleared", g.room == tuple(dst) and g.in_combat is False)

# ---------------------------------------------------------------- 6. guards and item droppers
willow = w.monster_names.get("ancient willow")
sheriff = w.monster_names.get("sheriff lionheart")
priest = w.monster_names.get("deranged priest")
step = Step(w.room((16, 356)).mega_hash, 0, "go hole", [], (16, 356), (16, 543))
g.candidates = [(16, 356)]; g.level = 10; st.char_level = 10; g.max_hp = g.hp = 130
g.view = RoomView("Guarded Hut", {"N"}, [("Sheriff Lionheart", sheriff)])
stops = []
b.stop = lambda why="Stopped": stops.append(why)
b._guard_at = None; b.hunt_target = None
held = b._guard_first(step, (16, 356), time.time())
b.stop = real_stop
print(f"(the ancient willow: ~{s.danger.mob_dpr(willow):.0f} damage a round to you by MME's numbers - not too strong by damage)")
check(f"L10 vs a guard that would maul it (Sheriff Lionheart): not fought ({stops[-1][:110] if stops else None})",
      held and stops and "too strong" in stops[-1] and b.hunt_target is None)
g.level = 55; st.char_level = 55; g.max_hp = g.hp = 100000
g.view = RoomView("Guarded Hut", {"N"}, [("deranged priest", priest)])
b._guard_at = None; b.hunt_target = None
check("a guard you can beat: fought as before", b._guard_first(step, (16, 356), time.time()) and b.hunt_target is priest)
b._guard_hunt, b.hunt_target, b._guard_at = False, None, None
jail = next((n for n, it in w.items.items() if (it.get("name") if isinstance(it, dict) else str(it)).lower() == "jail key"), None) \
    if isinstance(w.items, dict) else None
if jail is None:
    jail = next((n for n in range(1, 3000) if w.item_name(n).lower() == "jail key"), None)
check(f"the jail key is in the bundled data ({jail})", jail is not None)
g.candidates = [(1, 1)]; g.level = 10; st.char_level = 10; g.max_hp = g.hp = 130
b.errands.too_strong = {}
src_ = b.errands.source_for(jail)
check(f"L10: the jail key isn't planned off Sheriff Lionheart ({src_ and src_.get('what')}; "
      f"{b.errands.too_strong})", (not src_ or src_["kind"] != "monster") and jail in b.errands.too_strong)
g.level = 60; st.char_level = 60; g.max_hp = g.hp = 10 ** 7
b.errands.too_strong = {}
src_ = b.errands.source_for(jail)
check(f"…a character who'd win: planned as before ({src_ and src_.get('what')})", src_ and src_["kind"] == "monster")
g.max_hp = g.hp = 900

# ---------------------------------------------------------------- 7a. Stop, then a walk: rests work again
b.walking = False; st.auto_rest = True
b.stop("Stopped by you")
check("Stop with nothing walking: no rest for 2 minutes", b._no_rest_until > time.time())
g.candidates = [(1, 1)]; w.forget_routes()
tgt = next(tuple(ex.to) for ex in w.rooms[(1, 1)].exits.values() if ex.to and ex.kind == "normal")
b.goto(tgt)
check(f"a walk started after it: resting allowed again ({b._no_rest_until})", b._no_rest_until == 0)
b.stop("Stopped")

# ---------------------------------------------------------------- 7b. caster out of mana backs off and rests
tree = w.monster_names.get("hanging tree")
sb = s.spellbook
mage = [x for x in ("mmis", "lbol", "chao", "come", "magm", "chai") if sb.find(x)]
st.auto_combat = True; st.auto_spells = True; st.auto_cast = True; st.auto_nuke = True; st.aoe_safety = False
st.attack_spells = mage; st.multi_spell = ""; st.char_level = 55; g.level = 55; g.spellcasting = 291
g.known_spells = st.known_spells = list(mage)
st.spell_mana_reserve = 0; g.max_ma = 514
g.char_class = st.char_class = "Mage"
b.x.may_cast_attack = lambda: True
g.candidates = [room]; g.party = {}

def fight(ma, party=None):
    g.ma = ma; g.party = party or {}
    sent.clear(); logs.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0; b._area_armed = 0
    b._attack_sent_at = 0; b._melee_on = False; g.in_combat = True; b._fled = False
    g.view = RoomView(r.name, set(shown), [("hanging tree", tree)])
    b.fight([("hanging tree", tree)])
    return [c for c in sent if c.strip()]

c = fight(0)
check(f"L55 mage, 0 mana, the tree here: backs off a room to rest ({c}; {[m for m in logs if 'mana' in m][:1]})",
      any(x in {d.lower() for d in shown} for x in c) and b._fled and any("backing off" in m for m in logs))
check("…not counted as a run from something too strong", room not in b.too_strong_rooms())
c = fight(514)
check(f"…with mana: casts, no backing off ({c})", any(x.split()[0] in mage for x in c) and not any("backing off" in m for m in logs))
c = fight(0, party={"Leader": {}, "Tester": {}})
check(f"…a follower doesn't wander off on its own ({c})", not any("backing off" in m for m in logs))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
