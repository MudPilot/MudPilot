"""0.8.48/49: MME shop + item data, key doors, banks as safe rooms, drops, combat summary, item history."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
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
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

check("map data v9", w.version >= 9)
check("key door's bare side gets the other side's 'or picklocks'",
      "picklocks" in w.rooms[(15, 863)].exits["S"].etype and w.exit_need(w.rooms[(15, 863)].exits["S"])[1])
check("shop types read (6+ banks are type 7)", sum(1 for x in w.shops.values() if x.get("type") == 7) >= 6)
banks = set(s.trips.banks())
check("banks by type and name (Godfrey 1/297 among them)", (1, 297) in banks and len(banks) >= 8)
check("some items are Not Droppable", any(int(x.get("Not Droppable") or 0) for x in w.gear.values()))

# banks are safe rooms
g.candidates = [(1, 297)]
g.view = RoomView(w.rooms[(1, 297)].name, set(), [("thief", w.identify_monster("thief"))], [], [], time.time())
g.in_combat = False
check("no fight started in a bank", b.attackable() == [])
st.banks_safe = False
b._banks_for = None
check("…unless switched off", b.attackable() != [] or w.identify_monster("thief") is None)
st.banks_safe = True

# combat summary
cl = s.combatlog
cl.reset()
g.candidates = [(12, 1811)]
g.view = RoomView("Great Pyramid", {"E", "W"}, [("large giant scorpion", w.identify_monster("large giant scorpion"))],
                  [], [], time.time())
feed("Your flaming magma blast strikes large giant scorpion for 64 damage!",
     "The large giant scorpion lunges at you!",
     "The large giant scorpion stings you for 30 damage!",
     "You slap the large giant scorpion for 12 damage!",
     "You critically slap the large giant scorpion for 40 damage!",
     "You swing at the large giant scorpion!")
m = cl.mobs.get("giant scorpion") or {}
check("spell damage counted", m.get("spell_dmg") == 64 and cl.spells["flaming magma blast"]["hits"] == 1)
check("melee hits / crits / misses", m.get("hits") == 2 and m.get("crits") == 1 and m.get("misses") == 1)
check("its hits and misses on you", m.get("taken_hits") == 1 and m.get("taken_miss") == 1 and m.get("taken") == 30)

# drops: what turns up right after a kill
feed("The scorpion shudders and falls dead, leaking black fluid.", "You gain 4000 experience.")
g.view = RoomView("Great Pyramid", {"E", "W"}, [], [(1, "scorpion stinger"), (5, "silver nobles")], [], time.time())
cl.on_room(g)
kills, seen = cl.seen_drops("giant scorpion")
check("a kill is counted for drops", kills >= 1)
check("what appeared after it is its drop", "scorpion stinger" in seen)
rec = w.monster_names.get("orc") or next(iter(w.monsters.values()))
check("MME drop list from items' Obtained From", isinstance(cl.mme_drops(rec), list))

# item history + stash
feed("You picked up 5 silver nobles.", "You dropped 3 gold crowns.", "You hid 2 platinum pieces.")
whats = [x[1] for x in cl.items]
check("item history: got / dropped / stashed", "got" in whats and "dropped" in whats and "stashed" in whats)
stash = cl.stashed()
check("stashed coins added up", stash.get("gold crown") == 3 and stash.get("platinum piece") == 2)


# timers for any monster, set by hand, and shared with @spawn
bt = s.bosses
bt.data = {}; bt.save = lambda: None
orc = w.identify_monster("orc") or next(m for m in w.monsters.values() if m.get("in_game"))
bt.track(orc, respawn_min=30)
check("any monster can have a timer", orc in bt.tracked() and bt.respawn_secs(orc["num"]) == 1800)
bt.set_kill_time(orc, time.time() - 600)
txt, left = bt.status(orc["num"])
check("kill time set by hand → due in ~20 min", left and 1150 < left < 1250)
rep = bt.spawn_reply(orc)
check("@spawn answer in pMUD's format", rep.startswith(orc["name"] + ": dead - Next spawn: ") and "m" in rep)
bt.data = {}
bt.track(orc, respawn_min=30)
check("another bot's reply sets the time", bt.ingest_spawn_reply("Revolution", "{" + orc["name"] + ": dead - Next spawn: 10m}")
      and 550 < bt.status(orc["num"])[1] < 650)
st.remote_enabled = True; st.remote_channels = {"telepath": True}; st.remote_players = {"Revolution": ["query"]}
sent.clear()
s.remote.feed_line(f"Revolution telepaths: @spawn {orc['name']}")
check("@spawn answered", any("Next spawn" in x for x in sent))

# quest guide
from mudpilot.panes2 import quest_guide
s.route_char()
ab = next(iter(sorted(w.quest_steps)))
g_ = quest_guide(w, g, st, ab)
check("quest guide lists steps with a state each", isinstance(g_, list) and all("state" in x for x in g_))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
