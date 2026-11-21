"""Dan, 2026-11-01: the Iceforge needs a dragon key. It isn't a quest item: put a white, black, green, blue and red fang
in the slot at the dragon key door (the Unholy Temple, 3/606) with the room cleared. The dragons round the prismatic
dragon drop the fangs — loop those rooms. MudPilot gathers them and does it."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, er, w = s.bot, s.state, s.bot.errands, s.world
walked = []
b.start_path = lambda *a, **k: walked.append("path")
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


rc = w.recipe_for(757)
check(f"MME's recipe read: 5 fangs in order at 3/606, room clear ({rc and rc['cmds'][0]} … {rc and rc['cmds'][-1]})",
      rc and rc["room"] == (3, 606) and len(rc["cmds"]) == 5 and rc["cmds"][0] == "put white fang in slot"
      and rc["cmds"][-1] == "put red fang in slot" and rc["nomonsters"])
mp = type("P", (), {"steps": [], "title": "Go to 3/632 The Iceforge", "is_loop": False, "filename": "",
                    "needed_item": ""})()
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
g.candidates = [(3, 595)]
g.carrying, g.keys = "mithril greatsword (Weapon Hand)", ""
okk, why = er.plan(mp, False, [757])
kinds = [t["kind"] for t in (er.active or {}).get("todo", [])]
check(f"planned: ask the party, farm 5 fangs, the slot ({kinds})", okk and kinds == ["party"] + ["farm"] * 5 + ["recipe"])
check(f"…the farm loops the dragon lairs and the prismatic dragon ({er.active['todo'][1]['rooms']})",
      (3, 595) in er.active["todo"][1]["rooms"] and (3, 560) in er.active["todo"][1]["rooms"])
check("…and looting wants the fangs", {"white fang", "red fang"} <= er.wanted())
sent.clear(); er.tick()
check(f"asks the party for the key first ({sent})", "/Revolution @have dragon key" in sent)
er.have_answer("Revolution", "{no dragon key}"); er.have_answer("Evolution", "{no dragon key}")
for _ in range(3):
    er.tick()
check(f"nobody has it: on to the fangs ({[t['kind'] for t in er.active['todo']]})", er.active["todo"][0]["kind"] == "farm")
# a key turns up after all: no farming
saved = list(er.active["todo"])
g.keys = "dragon key"
g.carrying = "mithril greatsword (Weapon Hand)"
b.held_items = lambda: {757}
er.tick()
check("the key turns up: farming and slot dropped", not er.active or not any(t.get("key") == 757 or t["kind"] == "recipe"
                                                                              for t in er.active.get("todo", [])))
# back: no key; all five fangs in the pack → the slot
er.active = {"todo": [t for t in saved if t["kind"] == "recipe"], "then": (mp, False), "started": time.time(),
             "at": None, "tries": 0, "after": None, "target": None}
b.held_items = lambda: {736, 737, 738, 739, 740}
g.candidates = [(3, 606)]
g.view = RoomView("Unholy Temple", {"E", "W"}, [("dark cultist", {"name": "dark cultist"})], [], [], time.time())
sent.clear(); er.tick()
check(f"monsters in the temple: fight first, no slot yet ({sent})", not any("slot" in c for c in sent))
g.view = RoomView("Unholy Temple", {"E", "W"}, [], [], [], time.time())
for _ in range(6):
    b._cool.pop("recipe_step", None)
    er.tick()
puts = [c for c in sent if "slot" in c]
check(f"room clear: the five fangs in order ({puts})", puts == rc["cmds"])
b.held_items = lambda: {757}
er.active["then"] = (mp, False)
er.tick()
check("the key's in the pack: errand done", not er.active)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
