"""Party Miserable, 2026-10-28, on the way to the flaming mammoths: the Black House door (Key 172 — black star key —
or 100 picklocks) with picklocks 0. It bashed it 3x (no strength option: it can't be bashed), gave up, and went round
over the Building Rooftops — 'jump north', a chance jump, split Revolution off. The key was lying in the room.
Dan: ask the party for a black star key; nobody has one → get one (pick it up / kill cultists for it)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_get_items = True; st.bash_doors_first = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, w = s.state, s.bot, s.world
g.level, g.picklocks, g.strength, g.max_hp, g.hp = 47, 0, 86, 674, 674
g.carrying, g.keys = "vortex staff (Weapon Hand)", ""
g.inv_seq += 1
g.party = {"Miserable": {}, "Revolution": {}}
s.comeback.leading = lambda: True
s.route_char()
# chance jumps: a party doesn't take the rooftops
# (15/1831 is a flaming mammoth lair in the Diamond Mine Tunnels — 15/10159 was an Old Mine Tunnel room, only
# reachable past Webbed Mine or the jumps)
g.candidates = [(17, 1624)]
r = b.plan_route((17, 1624), (15, 1831))
jumps = [ex.to for ex in r or [] if "(Chance)" in (ex.etype or "")]
areas = {w.room(ex.to).name.split(",")[0] for ex in r or []}
check(f"party route to the mammoths: no chance jumps ({len(r or [])} steps, jumps {jumps[:3]})", r and not jumps)
check("…down through Khazarad's mines with a mine pass",
      {"Iron Mine Entrance", "Mithril Mine", "Diamond Mine Tunnel"} <= areas and
      "mine pass" in [w.item_name(n) for n in b._route_items((17, 1624), r, b.held_items() or set())])
check("…not through Webbed Mine or the Negative Power Plane",
      not areas & {"Webbed Mine Tunnel", "Webbed Mine Chamber", "Negative Power Plane", "Black Wasteland"})
# at the door: no bashing a picklocks-only door
door = (1, 1224)
ex = w.room(door).exits.get("E")
check(f"the Black House door is picklocks-only ({ex.etype})", ex is not None and "strength" not in ex.etype)
g.candidates = [door]
b.goto(ex.to)                                  # the Black House, right behind the door
up_front = [w.item_name(t["num"]) for t in (b.errands.active or {}).get("todo", [])]
check(f"Go to behind it: plans the key up front, picklocks 0 ({up_front})", "black star key" in up_front)
# an old path walking into the locked door: no bash (the locked-door order for a picklocks-only door, picklocks 0)
saved = b.errands.active
b._locked_dir = "E"; b._lock_tries = {"E": 0}; b._unlocked = None
from mudpilot.megamud_files import Step
b.walking, b.path = True, type("P", (), {"steps": [Step("E", 0, "E", [], door, ex.to)], "title": "old path",
                                         "is_loop": False, "filename": "", "needed_item": ""})()
b.idx = 0
sent.clear(); b._cool.clear()
for _ in range(4):
    b._door_wait_until = 0
    if b._locked_dir is None:
        b._locked_dir = "E"
    try:
        b.walk([], True)
    except Exception:
        pass
check(f"never bashes it ({[c for c in sent if 'bash' in c]})", not any("bash" in c for c in sent))
b.walking, b.path = False, None
b.errands.active = saved
# the errand: party first
sent.clear(); b._cool.clear()
b.errands.tick()
check(f"asks the party first ({sent})", "/Revolution @have black star key" in sent)
b.errands.have_answer("Revolution", "{no black star key}")
sent.clear(); b._cool.clear()
b.errands.tick()
# lying on the floor here: pick it up
g.view = RoomView("Slum Street", {"N", "S", "E"}, [], [(1, "black star key")], ["Revolution"], time.time(), closed={"E"})
sent.clear(); b._cool.clear()
b.errands.tick()
check(f"on the floor: picks it up ({sent})", "get black star key" in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
