"""0.8.47: monsters told apart by room, party cures, target priority, NoHang, confusion, stat truth, hidden players."""
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

# --- same-name monsters: the room decides
check("Paradigm has same-name monsters that differ", len(w.dup_names) > 50 and "zombie" in w.dup_names)
check("zombie in 9/1015's lair is the 500-exp one", w.identify_monster("zombie", room=(9, 1015))["num"] == 492)
check("…elsewhere, the usual one", w.identify_monster("zombie")["num"] != 492)
g.candidates = [(9, 1015)]
r = w.rooms[(9, 1015)]
v = RoomView(r.name, {"E", "W"}, [("zombie", w.identify_monster("zombie"))], [], [], time.time())
g._resolve_monsters(v)
check("the room view takes the one that lives here", v.monsters[0][1]["num"] == 492)

# --- party: poison from the P flag, @blind said, cures cast on them
st.cure_poison_cmd = "cupo"; st.cure_blind_cmd = "cubl"; st.party_cures = True
sp_ok = s.spellbook.find("cupo") is not None
s.spellbook.find = (lambda orig: (lambda x: {"Number": 1, "Short": x} if x in ("cupo", "cubl") else orig(x)))(s.spellbook.find)
feed("The following people are in your travel party:",
     "  Miserable Par                 (Mage)       [M:100%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H: 80%]P - Backrank", "[HP=684/MA=473]:")
check("par row flags read", g.party["Revolution"].get("flags") == "P")
check("…Revolution shows as poisoned", "Poisoned" in b.x.care.conditions("Revolution"))
sent.clear(); b._last_spell_at = 0
g.view = RoomView("Great Pyramid", {"E", "W"}, [], [], [], time.time())
check("not in the room: no cure", not b.x.cure_tick() and "cupo Revolution" not in sent)
g.view = RoomView("Great Pyramid", {"E", "W"}, [], [], ["Revolution"], time.time())
check("cure goes out on him", b.x.cure_tick() and "cupo Revolution" in sent)
sent.clear()
check("…not again straight away", not b.x.cure_tick() or "cupo Revolution" not in sent)
feed('Revolution says "@blind"')
check("'@blind' said by a party member noted", "Blind" in b.x.care.conditions("Revolution"))
feed("Deacon casts cure blindness on Revolution!")
check("someone else's cure clears it", "Blind" not in b.x.care.conditions("Revolution"))
feed('Vexx says "@blind"')
check("a stranger's '@blind' is ignored", "Vexx" not in b.x.care.cond)
feed("The following people are in your travel party:",
     "  Miserable Par                 (Mage)       [M:100%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H: 80%]  - Backrank", "[HP=684/MA=473]:")
check("clean par clears poison", "Poisoned" not in b.x.care.conditions("Revolution"))

# --- I go blind and can't cure it: tell the party
st.cure_blind_cmd = ""; st.report_conditions = True
sent.clear()
feed("You are blinded!")
check("'@blind' said for my healer", "@blind" in sent)
sent.clear(); feed("You are blinded!")
check("…once", "@blind" not in sent)
feed("You can see again.")

# --- target priority
mobs = [("orc", None), ("goblin", None), ("troll", None)]
st.target_priority = "second"
check("second → goblin first", b.x.leader_target(mobs)[0][0] == "goblin")
st.target_priority = "last"
check("last → troll first", b.x.leader_target(mobs)[0][0] == "troll")
st.target_priority = "third"
check("third of two → the second", b.x.leader_target(mobs[:2])[0][0] == "goblin")
st.target_priority = "first"

# --- NoHang
st.no_hang = True
s.safety.hangup("HP 10/600 below 30%")
check("NoHang: an automatic hang-up doesn't", s.telnet.connected)
s.safety.hangup("from your phone", manual=True)
check("…but one you ask for does", not s.telnet.connected)
s.telnet.connected = True; st.no_hang = False
s._want_connected = True

# --- confusion isn't a wall
g.candidates = [(12, 1811)]
b._resends = (((12, 1811), "n"), 6)
g.confused_fail_at = 0
feed("You fumble your weapon!")
check("an ordinary fumble isn't confusion", g.confused_fail_at == 0)
feed("You fumble in confusion.")
check("confusion noticed", time.time() - g.confused_fail_at < 2)
check("a move eaten by confusion isn't counted", not b._resend_guard((12, 1811), "n") and b._resends[1] == 6)

# --- a cast announcement doesn't poison you; the effect line does
st.message_rules_on = True
s.msgrules.conditions.clear(); b.x.ailments.pop("poison", None)
feed("Vexx casts poison bolt upon you!")
check("'casts poison bolt upon you' alone: not poisoned", "poisoned" not in s.msgrules.conditions)

# --- the stat effects list is the truth — on a board whose st lists effects at all
b.x._stat_lists_effects = False
b.x.ailments["held"] = time.time() - 30
feed("Name: Miserable                  Lives/CP:      9/0", "Intellect: 80      Willpower: 70", "")
b.x._stat_block["t"] -= 2
b.x.stat_block_tick()
check("a board whose st lists nothing: held stays", "held" in b.x.ailments)
b.x.ailments["held"] = time.time() - 30
feed("Name: Miserable                  Lives/CP:      9/0",
     "Intellect: 80      Willpower: 70",
     "You feel armoured! (111s)", "")
b.x._stat_block["t"] -= 2
b.x.stat_block_tick()
check("held but stat doesn't list it → not held", "held" not in b.x.ailments)

# --- someone hiding
g.view = RoomView("Great Pyramid", {"E", "W"}, [], [], [], time.time())
feed("You see Sneaky hiding in the shadows!")
check("a player found hiding joins the room's players", "Sneaky" in g.view.players)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
