"""0.8.200 spell-scroll errand (scrolls.py, from the MudPlay review): after a level-up (or the Spells tab's button), the
spells the class can learn now and doesn't know, the shops that stock their scrolls (ability 42), lowest level first
within the cash carried, buy + read at the counter, stop on the spellbook line or 'already know'. Off by default."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot import scrolls as S
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
check("off by default", st.auto_scrolls is False)
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, E = s.bot, s.world, s.scrolls
b.send = sent.append
g = s.state
g.char_class, g.level, g.in_combat, g.resting = "Mage", 5, False, False
st.known_spell_rows = [["mmis", "magic missile", 1, 2]]
st.known_spells = ["mmis"]

# --- which spells
mage = S.class_num(w, "Mage")
check(f"Mage is a class ({mage})", mage == 12)
names = [sp["Name"] for sp in E.wanted()]
check(f"wanted: learnable now, not known, lowest level first ({names})",
      names[:3] == ["blur", "illuminate", "smite"] and "magic missile" not in names)
check("nothing above level 5", all(int(sp["ReqLevel"]) <= 5 for sp in E.wanted()))
warrior = S.class_num(w, "Warrior")
check("a warrior can't learn mage spells", not any(S.learnable(w, sp, warrior, 50) for sp in E.wanted()))
check("trainer-taught spells from MME textblocks (class 11 learnspell 5573)", 5573 in S.tb_learnspells(w).get(11, set()))
blur = next(sp for sp in E.wanted() if sp["Name"] == "blur")
E.never.add(int(blur["Number"]))
check("a spell the game said we can't learn is dropped", "blur" not in [sp["Name"] for sp in E.wanted()])
E.never.clear()

# --- shops: stock slots, price with markup + charm
sc = S.scroll_items(w)
ill = sc[next(sp for sp in E.wanted() if sp["Name"] == "illuminate")["Number"]][0]
shops = s.trips.stocked_at(ill)
check(f"illuminate scroll stocked at two shops ({shops})", {r for r, _s, _p in shops} == {(1, 398), (1, 2144)})
g.charm = 75                                    # Fix(75/5) − 10 = 5% off
check(f"charm discount ({s.trips.price(ill, 100)})", s.trips.price(ill, 100) == int(400 * 0.95))
g.charm = 0

# --- the plan
d_here = {(1, 398): 10, (1, 2144): 40}
d_on = {(1, 398): 10, (1, 2144): 5}
E._dist_from = lambda here: d_here
E._dist_to = lambda room: d_on
stop, notes = E.plan((1, 300), (1, 300), budget=10 ** 6)
check(f"nearest shop by the walk there and back ({stop and stop['room']})", stop and stop["room"] == (1, 398))
check(f"…buys everything it stocks for us ({[w.item_name(i) for i, _s, _p in stop['buys']]})",
      [w.item_name(i) for i, _s, _p in stop["buys"]][:3] == ["scroll of blur", "scroll of illuminate", "scroll of smite"])
stop, _n = E.plan((1, 300), (1, 300), route_rooms=[(1, 2144)], budget=10 ** 6)
check(f"a shop on the loop wins: blur and illuminate there, not at the nearer shop "
      f"({[w.item_name(i) for i, _s, _p in stop['buys']]})",
      stop and stop["room"] == (1, 398) and not {"scroll of blur", "scroll of illuminate"} &
      {w.item_name(i) for i, _s, _p in stop["buys"]})
stop, _n = E.plan((1, 300), (1, 300), route_rooms=[(1, 2144)], budget=10 ** 6, skip_rooms={(1, 398)})
check("…which are bought at the loop's shop", stop and stop["room"] == (1, 2144) and "scroll of blur" in
      {w.item_name(i) for i, _s, _p in stop["buys"]})
stop, notes = E.plan((1, 300), (1, 300), budget=0)
check(f"no cash: only the free scrolls ({[w.item_name(i) for i, _s, _p in stop['buys']]}, broke {notes['broke'][:3]})",
      all(p == 0 for _i, _s, p in stop["buys"]) and "illuminate" in notes["broke"])
stop, _n = E.plan((1, 300), (1, 300), budget=10 ** 6, skip_rooms={(1, 398)})
check(f"a shop already visited is skipped ({stop and stop['room']})", stop and stop["room"] == (1, 2144))

# --- the shop's list
lines = ["The following items are for sale here:", "",
         "Item                          Quantity    Price",
         "------------------------------------------------------",
         "scroll of solid fog           10         600 gold crowns (You can't use)",
         "scroll of resist lightning    10         200 gold crowns",
         "scroll of eldritch bolt       9          600 gold crowns (Too powerful)",
         "scroll of blur                30           Free"]
rows = S.parse_list(lines)
check(f"list rows parsed ({rows})", len(rows) == 4 and rows[0][3] and rows[2][4] and rows[3][:2] == ("scroll of blur", 30))
check("a 29-character cut name still matches", S.list_row_for([("scroll of protection from evi", 3, "x", False, False)],
                                                              "scroll of protection from evil"))
check("prompt in front of a line is stripped", S.strip_prompt("[HP=50/MA=10]:You just bought x for nothing.")
      == "You just bought x for nothing.")

# --- level-up only with the setting on
E.note_line("You are now level 6!")
check("setting off: a level-up doesn't start it", E.pending is None)
st.auto_scrolls = True
E.note_line("You are now level 6!")
check("setting on: a level-up asks for it", E.pending == "level-up")

# --- the errand, standing in the shop (1/398)
g.candidates = [(1, 398)]
g.wealth = 100000
g.carrying = "leather armour (Worn)"
calls = []
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True
b.walking, b.path = False, None
E.tick()
check("idle after a level-up: waits for a lap end (no walking off between loops)", E.trip is None and E.pending)
E.pending = None
st.auto_scrolls = False
E.want_now()
E.tick()
check("the button: starts at once, even with the setting off", E.trip is not None and E.pending is None)
st.auto_scrolls = True
E.tick()
check(f"reads the spell list and the pack first ({sent[-2:]})", sent[-2:] == ["spells", "i"])
E.trip["next_at"] = 0
E.tick()
check(f"in the shop already: list ({E.trip['phase']})", E.trip["phase"] == "list")
E.tick()
check(f"'list' sent ({sent[-1]})", sent[-1] == "list")
for ln in ["The following items are for sale here:", "", "Item                          Quantity    Price",
           "scroll of blur                30           Free",
           "scroll of illuminate          5          400 copper farthings (You can't use)",
           "scroll of smite               3            8 gold crowns (Too powerful)"]:
    E.note_line(ln)
g.last_prompt = time.time() + 1
E.tick()
q = [x["name"] for x in E.trip["queue"]]
check(f"can't-use / too-powerful / not-listed skipped ({q})", q == ["scroll of blur"])
illum = next(sp for sp in s.world.spells.values() if sp.get("Name") == "illuminate" and int(sp["Number"]) in sc)
check("can't-use → never again", int(illum["Number"]) in E.never)
E.tick()
check(f"buy sent ({sent[-1]})", sent[-1] == "buy scroll of blur")
E.note_line("[HP=50/MA=10]:You just bought scroll of blur for nothing.")
E.tick()
E.tick()
check(f"then read it ({sent[-1]})", sent[-1] == "read scroll of blur")
E.note_line("You read scroll of blur and learn the spell blur.")
E.tick()
check(f"learned ({E.learned})", E.learned == ["blur"])
check("…and the bot re-reads its spell list", b._spells_asked is False)
E.tick()
E.tick()
check(f"pack checked before the next shop ({sent[-1]})", sent[-1] == "i")
E.trip["next_at"] = 0
E.soft.clear()                                 # (as if they'd restocked: the not-listed ones are wanted again)
E._dist_from = lambda here: {(1, 398): 0, (1, 2144): 40}
E.tick()
check(f"re-plan: the other shop for the rest ({calls[-1:]})", calls and calls[-1] == ("goto", (1, 2144)))
E.trip["phase"] = "list"; E.trip["sent"] = False; E.trip["next_at"] = 0
g.candidates = [(1, 2144)]
E.trip["stop"]["buys"] = [(it, sp, p) for it, sp, p in E.trip["stop"]["buys"] if w.item_name(it) == "scroll of frost jet"] \
    or E.trip["stop"]["buys"][:1]
E.tick()
E.trip["list_at"] = 0                          # no list came back: try the buys anyway
E.tick()
nm = E.trip["queue"][0]["name"]
E.tick()
E.note_line(f"You just bought {nm} for 8 gold crowns.")
E.tick(); E.tick()
E.note_line("You realize that you already know this scroll!")
E.tick()
check("'already know' ends that one", E.trip["cur"] is None and nm not in [x["name"] for x in E.trip["queue"]])

# --- buy / read answers
E.trip["queue"] = [{"name": "scroll of x", "spell": {"Number": 999001, "Name": "x"}, "item": 1, "price": 5}]
E.trip["phase"] = "buy"
E.tick()
E.note_line("You cannot afford scroll of x.")
E.tick()
check("can't afford → next", E.trip["cur"] is None)
E.trip["queue"] = [{"name": "scroll of y", "spell": {"Number": 999002, "Name": "y"}, "item": None, "price": 0}]
E.trip["phase"] = "read_carried"
E.tick()
check(f"a carried scroll is read without buying ({sent[-1]})", sent[-1] == "read scroll of y")
E.note_line("You don't know what to do with this!")
E.tick()
check("can't learn → never again", 999002 in E.never)

# --- Stop ends it, no walking back
b._user_stop_at = time.time() + 5
E.tick()
check("your Stop ends it", E.trip is None)
b._user_stop_at = 0

# --- lap end: off from the loop, back to it after
class P:
    title = "My loop"; is_loop = True; resolved = True
    class St:
        room = (1, 398); dest = (1, 399)
    steps = [St()]
loop = P()
g.candidates = [(1, 398)]
E.pending = "level-up"
check("lap end: off on the errand", E.lap_end(loop) and E.trip is not None)
E._finish("test")
check(f"…and back to the loop after ({calls[-1]})", calls[-1] == ("loop", "My loop"))

# --- a follower doesn't wander off
b.x._following = "Miserable"
E.pending = "level-up"
check("a follower doesn't go", not E.lap_end(loop))
b.x._following = None

# --- carried scrolls counted by name
g.carrying = "scroll of smite, leather armour (Worn)"
E.never.clear(); E.soft.clear()
cs = [n for n, _sp in E.carried_scrolls()]
check(f"a carried scroll for a wanted spell ({cs})", cs == ["scroll of smite"])

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
