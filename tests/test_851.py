"""0.8.51: doors wait for their answer, combat off mid-fight walks on, Eco's auto threshold."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_spells = False; st.auto_bless = False; st.auto_rest = False; st.auto_heal = False
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
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# --- Eco: a lone sandworm isn't worth two level-47s stopping
g.level = 47
st.eco_travel = True; st.eco_min_exp = 0
worth, hit = b.eco_limits()
check(f"auto threshold grows with level (47 → {worth})", worth >= 2350)
sw = w.monster_names["sandworm"]
b.walking, b.loop = True, None
from mudpilot.megamud_files import MPath, Step
b.path = MPath("Go to 1/1 x", "t", "", "", steps=[Step("", 0, "N", [], (1, 1), (1, 2))])
g.max_hp = g.hp = 684
check("…so a sandworm (1,100 exp) is walked past", b._eco_filter([("sandworm", sw)]) == [])

# --- doors: open, then wait for the answer before walking into it
dr = next((k, d) for k, r in w.rooms.items() for d, e in r.exits.items() if e.kind == "door" and k[0] == 1)
room, d = dr
mp = MPath("Go to x", "t", "", "", steps=[Step(w.rooms[room].mega_hash, 0, d, [], room, w.rooms[room].exits[d].to)])
b.start_path(mp, loop=False)
g.candidates = [room]
ex = set(e for e in w.rooms[room].exits if w.rooms[room].exits[e].visible)
g.view = RoomView(w.rooms[room].name, ex, [], [], [], time.time(), {d})
g.in_combat = False; st.auto_combat = False; st.eco_travel = False
sent.clear()
for _ in range(3):
    b._cool = {"par": time.time(), "par_solo": time.time()}; b._abil_read = ("done", 0); b.tick()
from mudpilot.worlddb import DIR_WORDS
exd = w.rooms[room].exits[d]
want = "open" if exd.action_cmds() else ("bash" if "1000" not in exd.etype else None)
check(f"a closed door: bashed first, not opened (Dan: they're nearly always locked) ({sent})",
      sent and (want is None or sent[0].startswith(want)))
check("…and doesn't walk into it before the game answers", d.lower() not in sent)
feed("The door is locked.")
sent.clear()
for _ in range(3):
    b._cool = {"par": time.time(), "par_solo": time.time()}; b._abil_read = ("done", 0); b.tick()
check(f"locked → pick / bash, still no blind move ({sent})", sent and sent[0].split()[0] in ("bash", "pick", "use")
      and d.lower() not in sent)
feed("You bashed the door open.")
sent.clear()
for _ in range(3):
    b._cool = {"par": time.time(), "par_solo": time.time()}; b._abil_read = ("done", 0); b.tick()
check(f"opened → walks through, no 'open' again ({sent})", d.lower() in sent and not any(x.startswith("open") for x in sent))

# --- combat switched off mid-fight while walking: walk on
b.stop("t"); sent.clear(); g.pending.clear(); b._expect_seq = None
mp = MPath("Go to y", "t", "", "", steps=[Step(w.rooms[(1, 1)].mega_hash, 0, "N", [], (1, 1), w.neighbor((1, 1), "N"))])
b.start_path(mp, loop=False)
g.candidates = [(1, 1)]
g.view = RoomView(w.rooms[(1, 1)].name, set(e for e, x in w.rooms[(1, 1)].exits.items() if x.visible),
                  [("orc", w.identify_monster("orc"))], [], [], time.time())
g.in_combat = True; st.auto_combat = False
for _ in range(3):
    b._cool = {"par": time.time(), "par_solo": time.time()}; b._abil_read = ("done", 0); b.tick()
check(f"combat off mid-fight: walks on ({sent} {b.status!r} {b.walk_holds()} w={b.walking} p={b.paused})", "n" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
