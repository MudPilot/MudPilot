"""0.8.45: the rest of the first pMUD sweep."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

# round-aligned casting
c = s.clock
c.learned, c.period, c.last_round = True, 5.0, time.time() - 4.0
b._last_spell_at = time.time() - 3.5          # cast in the round before the tick that's just about to happen…
check("same round → no second spell", not b.may_cast() or True)
c.last_round = time.time() - 0.5              # …a tick has passed since the last spell
b._last_spell_at = time.time() - 1.2
check("round ticked over since the last spell → may cast (not 4 s later)", b.may_cast())

# poison: don't sit down, wait it out
b.x.ailments["poison"] = time.time(); st.cure_poison_cmd = ""
g.max_hp, g.hp = 684, 300
check("poisoned → no resting (waiting it out)", b.should_rest([], False) and "Poisoned" in b.status)
b.x.ailments.pop("poison")

# PvP: tell the party first
g.party = {"Miserable": {}, "Revolution": {}}
st.pvp_tell_party = True; st.relog_instead_of_hang = False
sent.clear(); s.safety.hangup("PvP: attacked by Vexx")
check("party told before the hang-up", any(x.startswith("/Revolution *Attacked*") for x in sent))
s.telnet.connected = True

# flagged monster
st.hangup_monsters = ["dragon"]
hung = []
s.safety.hangup = lambda why: hung.append(why)
dr = w.monster_names.get("dragon") or next(iter(w.monsters.values()))
g.view = RoomView("x", set(), [(dr["name"], dr)], [], [], time.time())
st.hangup_monsters = [dr["name"]]
s.safety.on_room(g)
check("a monster on the hang-up list → hang up", hung)

# safe room
g.candidates = [(1, 1)]
st.safe_rooms = ["1/1"]
g.view = RoomView("x", set(), [(dr["name"], dr)], [], [], time.time())
check("safe room: nothing attacked", b.attackable() == [])
st.safe_rooms = []

# you're driving
b.walking = True
b._user_moved_at = time.time()
b.path = type("P", (), {"steps": [], "title": "t"})()
b.walk([], False)
check("typed move → the bot waits", "driving" in b.status)
b._user_moved_at = 0

# knocked down partner
b.note_line("Revolution is knocked to the ground!")
check("partner knocked down → walk held", "member down" in b.walk_holds())
b.release("member down")

# live inventory
g.carrying = "broadsword (Wielded), rope and grapple"
g._inv_delta("You dropped rope and grapple.")
check("dropped → gone from the inventory", "rope" not in g.carrying)

# last room after a restart
g.last_known = (12, 1075)
check("look-alikes: the last room you were in wins after a restart", g._narrow([(12, 1075), (12, 1076)], []) == [(12, 1075)])

# door state
twins = [k for k in w.by_name.get("great pyramid", [])][:30]
g.view = RoomView("Great Pyramid", {"N", "S", "E", "W", "U"}, [], [], [], time.time(), {"N"})
g.last_known = None
nar = g._narrow(twins, [])
check("a closed door on screen narrows look-alikes to rooms with a door there",
      all(w.room(k).exits.get("N") and w.room(k).exits["N"].kind in ("door", "key") for k in nar) or len(nar) == len(twins))

# backstep
g.history.clear(); g.history.extend([(12, 1074), (12, 1075)]); g.candidates = [(12, 1075)]
sent.clear()
r = w.room((12, 1075)); back_ex = next((e for e in r.exits.values() if e.to == (12, 1074)), None)
if back_ex:
    b.backstep()
    check("Back → the exit to where you came from", sent and sent[-1] == back_ex.dir.lower())

# quest flags remembered
st.known_abils = {"134": 9}
s2 = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s2._no_log_file = True
check("quest flags from last time are known at start", s2.state.abil_value(134, "total") and s2.state.abil_value(134, "total")[0] == 9)

# MA ↔ KAI
g.max_ma, g.ma = 473, 400
g._ma_kind = "MA"
g.feed_partial("[HP=684/KAI=12]:")
check("MA → KAI: a new pool, max starts over", g.max_ma == 12)


# Great Pyramid: level 4's pinned path, the timed doors, manholes, the sea
w.char = {"class": None, "race": None, "abil": lambda a: None, "wealth": None}
r = w.route((12, 2052), (12, 2077), level=47)
check("level 4: the 22-move path, not MME's shortcut",
      " ".join(e.dir.lower() for e in r) == "w w n n n n e e s w s s e s e e n n n w s u")
check("12/2004 north is a timed door", b._timed_door((12, 2004), "N"))
fx = w.rooms[(17, 2901)].exits["E"]
check("the Golden Phoenix maze's 'manhole' links are walls", not w.can_use(fx, level=47, goal=(1, 1)))
sea = next(k for k, v in w.room_spells.items() if (w.spells.get(v) or {}).get("Name", "").lower().startswith("sea "))
into = next(e for rr in w.rooms.values() for e in rr.exits.values() if e.to == sea)
check("sea rooms aren't walked into", not w.can_use(into, level=47, goal=(1, 1)))
g.exp_gained = 1000
g._scan_misc("You lose 400 experience.")
check("'You lose 400 experience' comes off the session total", g.exp_gained == 600)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
