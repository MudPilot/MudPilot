"""0.8.35: everything MME's textblocks say (teleports through 'cast', 'text' chains, NPC talk), the walker
not typing into walls, set talk slow, Eco travel, the recover password masked on screen."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, mmetext
from mudpilot.worlddb import WorldDB
from mudpilot.session import Session
from mudpilot.gamestate import RoomView

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
w.char = {"class": None, "race": None, "abil": lambda a: None, "wealth": None}

# --- the sinkhole: 'dive sinkhole' → minlevel 20 → cast 5100 (abilities 140/141 = room 2224 on map 12)
acts = w.room_actions.get((12, 1075)) or []
check("Scorching Desert, Sinkhole: dive sinkhole goes to 12/2224",
      any(a["to"] == (12, 2224) and "dive sinkhole" in a["triggers"] for a in acts))
r = w.route((12, 1075), (12, 2224), level=47)
check("…and the router uses it", r and r[-1].text_command == "dive sinkhole")
check("…not below level 20", not w.route((12, 1075), (12, 2224), level=15))
r = w.route((12, 335), (12, 2224), level=47)
check("from 12/335 into the Crumbling Temple", bool(r) and any(e.text_command == "dive sinkhole" for e in r))

# --- the pyramid word still opens its exit
pyr = [ex for ex in w.rooms[(12, 1188)].exits.values() if ex.kind == "hidden"] if (12, 1188) in w.rooms else []
check("pyramid: the word is the hidden exit's action", any("say gazmuldduhaz" in [c.lower() for c in ex.action_cmds()]
                                                              for ex in pyr) or not pyr)

# --- interpreter: a teleport two blocks down the chain, conditions carried along
tbs = {1: ("pull rope:minlevel 30:text 2\nlook:message 5\n", 0, ""),
       2: ("class 3:checkitem 77:text 3\n", 0, ""),
       3: ("message 9:teleport 40 13\n", 0, "")}
acts = mmetext.room_actions(tbs, {}, 1, (1, 1))
check("teleport two textblocks down is found", len(acts) == 1 and acts[0]["to"] == (13, 40))
check("…with what it needs", acts and acts[0]["req"]["level"] == 30 and acts[0]["req"]["classes"] == [3]
      and acts[0]["req"]["items"] == [77])
check("talk block: 'visit:3' → a way somewhere",
      mmetext.npc_actions({9: ("ways:3348\nvisit:3\n", 0, ""), **tbs}, {}, 9, 1)[0]["to"] == (13, 40))
check("NPC ways are listed (map 13's guide)", any(v for v in w.npc_ways.values()))
check("lots more of the map reachable", w.teleports > 200)

# --- level gates written 'Level: 64 to 0' mean 64 and up
ex = next(e for e in w.rooms[(16, 12231)].exits.values() if "Level: 64 to 0" in e.etype)
check("'Level: 64 to 0' open at 70", w.can_use(ex, level=70))
check("…closed at 60", not w.can_use(ex, level=60))


# --- NPC talk opens exits: 'ask sphinx sun' at the Great Pyramid (MME: remoteaction … exit 8 = up)
for k, cmd in (((12, 1920), "ask sphinx fire"), ((12, 2001), "ask sphinx sun")):
    ex = w.rooms[k].exits["U"]
    check(f"{k[0]}/{k[1]} up opens with '{cmd}'", cmd in ex.action_cmds())
w.char = {"class": None, "race": None, "abil": lambda a: 20, "wealth": None}
r = w.route((17, 1628), (12, 2002), level=47)
check("17/1628 → 12/2002 routes through the pyramid now", bool(r))
w.char = {"class": None, "race": None, "abil": lambda a: None, "wealth": None}
gl = next(e for rr in w.rooms.values() for e in rr.exits.values() if e.kind == "cast" and "1257" in e.etype)
check("an exit that casts 'gloomy teleport' on you isn't walked", not w.can_use(gl, level=47))

# --- session bits
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.locate_cmd = "pro"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True

s.send("@party go portal")
s._talk_slow_line("Your command had no effect.")
check("talk slow: 'no effect' → said again with a '.'", sent[-1] == ".@party go portal" and st.talk_slow == 1)
sent.clear(); s.send("@do go portal")
check("…and from then on with the '.' first time", sent == [".@do go portal"])
s._talk_slow_line('You say ".@do go portal"')
check("the '.' was said out loud → talk isn't slow, say it again without", sent[-1] == "@do go portal" and st.talk_slow == 0)
s._talk_slow_line("Talking speed:       Slow")
check("'pro' Talking speed: Slow → slow", st.talk_slow == 1)

got = []
s.on_line = lambda segs: got.append("".join(t for t, _ in segs))
s._line([("Recover Password:    123456", None)])
check("recover password masked on screen", got and "123456" not in got[-1] and "(hidden)" in got[-1])

# --- walker: the step says east, the room shows no east → locate, don't type into the wall
b = s.bot
from mudpilot.megamud_files import path_from_route
route = w.route((10, 22), (10, 23), level=47)
mp = path_from_route(w, (10, 22), route, "test")
b.path, b.walking, b.loop, b.idx = mp, True, False, 0
from mudpilot.megamud_files import Step
fake = Step(w.room((10, 23)).mega_hash, 0, "E", [], (10, 23), (10, 24))
mp.steps.append(fake)
b.idx = len(mp.steps) - 1
s.state.candidates = [(10, 23)]
s.state.view = RoomView("Rocky Trail", {"SW", "U"}, [], [], [], time.time())
sent.clear()
b._no_such_exit(fake, (10, 23))
check("no east exit here → asks 'pro' instead of typing 'e'", sent == ["pro"])

# --- Eco travel
st.eco_travel = True
b.walking, b.loop = True, False
s.state.level, s.state.max_hp, s.state.hp = 47, 684, 684
bandit = w.monster_names["bandit"]
worm = w.monster_names["sandworm"]
scorp = w.monster_names["giant scorpion"]
keep = b._eco_filter([("bandit", bandit), ("sandworm", worm)])
check("Eco at 47: walk past the bandit and a 1,100-exp sandworm", keep == [])
keep = b._eco_filter([("bandit", bandit), ("sandworm", worm), ("giant scorpion", scorp)])
check("…stop for a 4,000-exp scorpion — and then take the whole room", len(keep) == 3)
b.eco_note_hit("The bandit slashes you for 60 damage!")
check("…but a bandit that hits for 60 (over the limit) gets fought",
      "bandit" in [k[0] for k in b._eco_filter([("bandit", bandit)])])
b._eco_hits = {}
s.state.hp = 300
check("…and everything on you is fought below the Eco HP %", len(b._eco_filter([("bandit", bandit)])) == 1)
s.state.hp = 684
b.loop = True
check("…loops aren't Eco (that's where you hunt)", len(b._eco_filter([("bandit", bandit)])) == 1)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
