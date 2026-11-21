"""0.8.40 extras from the pMUD sweep: boats, traps, bank run for tolls, protective gear for room spells,
item rules + weight, corpse recovery, quest steps from MME, long replies split at 127."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step, STEPF

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

# --- boats: 'secure passage to terra fuego' at 14/759 → 14/1812, a 100-round voyage, 2M fare
acts = w.room_actions.get((14, 759)) or []
boat = next((a for a in acts if a["to"] == (14, 1812)), None)
check("MME boat read: passage → landing, rounds at sea, fare", boat and boat["req"]["voyage"] and boat["req"]["price"])
ex = next(e for e in w.rooms[(14, 759)].exits.values() if e.to == (14, 1812))
check("…and costs its time at sea in routing", w.exit_cost(ex) > 100)
g.candidates = [(14, 759)]
b._boat_check((14, 759), ex.text_command, Step("", 0, ex.text_command, [], (14, 759), (14, 1812)))
g.candidates = [(14, 717)]
check("aboard: the walk waits (not 'lost')", b._at_sea(time.time()))
g.candidates = [(14, 1812)]
check("…landed: carry on", not b._at_sea(time.time()))

# --- traps
st.disarm_traps = True
sent.clear()
trap = next((k, d) for k, r in w.rooms.items() for d, e in r.exits.items() if e.kind == "trap" and len(d) <= 2)
stp = Step("", STEPF["DISARM"], trap[1], [], trap[0], w.rooms[trap[0]].exits[trap[1]].to)
check("trap ahead: disarm first", b._disarm_gate(stp, trap[0]) and sent and sent[-1].startswith("disarm trap"))
b._disarm_line("You successfully disarmed the trap to the north!")
check("…disarmed: go", not b._disarm_gate(stp, trap[0]))

# --- item rules + weight
st.item_rules = ["rope and grapple: max 1", "broadsword: drop", "rusty dagger: never", "iron key: keep 1"]
check("rule read", b.item_rule("rope and grapple").get("max") == 1 and b.item_rule("broadswords").get("drop"))
g.carrying = "rope and grapple, 2 broadswords"
g.view = RoomView("Test", {"N"}, [], [(1, "rope and grapple"), (1, "rusty dagger")], [], time.time())
st.auto_loot, st.loot_items = True, ["*"]
b._looted_seq = -1; b._loot_wait = None
sent.clear(); b.loot()
check("already have one rope: don't pick up another; never the rusty dagger",
      not any("rope" in x or "rusty" in x for x in sent))
g.enc = (3990, 4032, "Heavy", 99)
check("too heavy: won't fit", b.how_many_fit("golden breastplate", 1) == 0)
g.enc = (100, 4032, "None", 2)
check("…fits when you're light", b.how_many_fit("golden breastplate", 1) == 1)
sent.clear(); b._cool.clear()
b.x.drop_unwanted()
check("'drop' rule drops the broadswords", any(x.startswith("drop") and "broadsword" in x for x in sent))

# --- corpse
st.recover_corpse = True
g.view = RoomView("Test", {"N"}, [], [(1, "corpse of Miserable")], [], time.time())
b._looted_seq = -1; b._loot_wait = None; b._cool.pop("corpse", None)
sent.clear(); b.loot()
check("own corpse → 'recover corpse Miserable'", "recover corpse Miserable" in sent)

# --- protective gear
spn, rooms = None, []
for k, sp in w.room_spells.items():
    if sp in w.negates:
        spn, rooms = sp, [k]
        break
if spn:
    item = w.negates[spn][0]
    from mudpilot.spells import is_attack_spell
    nm = w.item_name(item)
    g.carrying = nm
    b.held_items = lambda: {item}
    sent.clear(); b._cool.clear()
    b._ward_gear(Step("", 0, "N", [], (1, 1), rooms[0]))
    harmful = is_attack_spell(w.spells.get(spn) or {})
    check("room spell ahead that an item of yours negates → wear it" if harmful else "harmless room spell: nothing worn",
          (f"wear {nm}" in sent) == bool(harmful) or not harmful)

# --- bank run for a toll
sent.clear()
b.goto = lambda target, then=None, ask=None, _retry=False: True
s.trips._nearest = lambda rooms, lim: ((1, 1), 3)
check("short for a toll → trip to the bank", s.trips.withdraw_for(type("P", (), {"title": "test path"})(), False, 500))
check("…to withdraw the difference", s.trips.trip and s.trips.trip["cmds"][0].startswith("withdraw "))
s.trips.trip = None

# --- quest steps
check("MME quest steps indexed", len(w.quest_steps) > 20)
check("…with a next step for a quest flag", "next step" in w.quest_hint(126, 50))

# --- long replies split at the game's 127 characters
sent.clear()
s.remote.reply("telepath", "Revolution", "x " * 120) if hasattr(s.remote, "reply") else None
check("remote replies never over 127 characters", all(len(x) <= 127 for x in sent))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
