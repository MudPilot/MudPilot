"""Dan, 2026-10-28: the flaming mammoths are reached through Khazarad's dwarven mines with a mine pass bought at the
Miner's Guild next door — not the Black House door (a 10% cultist key) and not over the Old Mine's jump past rooms of
wraith spiders. Routes weigh what a way needs fetching, keep out of lairs that would maul you, and say so when the
only way goes through one; Best spots doesn't offer areas behind them, and builds the mammoth loop without the
horned demon lair that made it look 'deadly'."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47; st.char_class = "Mage"
st.auto_get_items = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, w = s.state, s.bot, s.world
g.level, g.max_hp, g.hp, g.ac, g.dr, g.picklocks, g.strength = 47, 674, 674, 60, 8, 0, 86
g.known_spells = ["mmis", "magm", "simp", "dfir", "esto"]
g.carrying, g.keys, g.wealth = "vortex staff (Weapon Hand)", "", 10 ** 7
g.inv_seq += 1
g.party = {"Miserable": {}, "Revolution": {"class": "Druid"}}
s.comeback.leading = lambda: True
s.route_char()
check("the Webbed Mine Chamber's wraith spiders count as dangerous", b.danger_room((15, 1539)))
check("…a slum street of dark cultists doesn't", not b.danger_room((1, 1224)))
# from the Bank of Khazarad to the Diamond Mine: buy a mine pass, down the mines, nothing dangerous
g.candidates = [(6, 1334)]
b.goto((15, 1832))
todo = [(w.item_name(t["num"]), t["room"]) for t in (b.errands.active or {}).get("todo", [])]
check(f"Go to the Diamond Mine: a mine pass from the Miner's Guild first ({todo})", ("mine pass", (6, 1567)) in todo)
g.carrying = "vortex staff (Weapon Hand), mine pass"; g.inv_seq += 1
b.errands.cancel(); b._way_memo = {}
r = b.plan_route((6, 1334), (15, 1832))
check(f"…then through the mines ({r and len(r)} steps), no dangerous lair on the way",
      r and any(ex.to == (6, 1568) for ex in r) and not any(b.danger_room(ex.to) for ex in r))
# the Old Mine loop past the spiders: it warns
s.logs.clear() if hasattr(s.logs, "clear") else None
b._cool.pop("danger_note", None)
b.plan_route((6, 1334), (15, 10159))
check("a place only reachable past the wraith spiders: it says so", any("careful" in l for l in s.logs))
# Best spots: no Old Mine loop; the mammoths are offered, with the mine pass, without the demon lair
g.candidates = [(6, 1334)]
g.carrying = "vortex staff (Weapon Hand)"; g.inv_seq += 1
res = s.spots.find(progress=lambda a, b_, m: None)
areas = {o["area"]: o for o in res.get("spots", [])}
check(f"Best spots doesn't offer the Old Mine loop behind the spiders ({list(areas)[:6]})", "Old Mine Tunnel" not in areas)
mam = next((o for o in res.get("spots", []) if any("flaming mammoth" in m for m in o["mobs"])), None)
check(f"…offers the flaming mammoths ({mam and mam['area']}, {mam and mam['risk']}, needs {mam and mam.get('needs')})",
      mam and "mine pass" in (mam.get("needs") or []) and "horned demon" not in mam["mobs"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
