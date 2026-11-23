"""0.8.222, fixes from the 2026-11-21 simulated walks (bug_hunt/*_1121.md, HUNT_1121.md):
- the 'way back out' check only refuses when doors are what shut you in: spell-trap ways out (Darkened Tunnels pockets),
  rooms MME shows no way out of (Ozrinom's 17/2243), random-drop rooms (Warped Asylum) walk as before; a pocket you're
  already in doesn't stop a Go to inside it (17/2202 → 17/2205); Stone Barracks is still refused.
- a '1000' door on the plain way, and another way in a key / picklocks opens: that way (Dark-Elf Castle 8/560).
- route planning with every item isn't slowed by the HP wall (the spell-damage cache key).
- the 'any way in?' check (look-alike rooms) ignores this character's HP wall.
- 'sea n' (MegaMUD's search) counts as a search; a party's classes are checked on room commands."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.automation import SEARCH_CMD_RE
st = config.Settings(); st.save = lambda: None; st.char_level = 55; st.my_name = "Tester"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = T(); s._entered = True
s.on_no_route = lambda m: None
w, b, g = s.world, s.bot, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def go(here_, tgt, lvl=55, pick=182, strg=60, carrying="astral staff"):
    b.stop("Stopped by you"); b.errands.cancel(); s.trips.reset("t"); b._pending_abil = None
    g.candidates = [here_]; g.level = lvl; st.char_level = lvl; g.picklocks, g.strength = pick, strg
    g.max_hp = g.hp = 900; g.max_hp_read = True
    g.carrying = carrying; g.keys = ""; g.inv_seq += 1; w.forget_routes(); b.no_route_msg = ""
    r = b.goto(tgt)
    return r, b.walking, b.no_route_msg or ""

r = go((15, 356), (15, 360))
check(f"Darkened Tunnels side pocket (way out is a spell trap): walks {r[:2]} {r[2][:80]}", r[0] and r[1])
r = go((17, 2202), (17, 2205), lvl=12, pick=0, strg=30)
check(f"already in the Mausoleum's pocket: a Go to inside it walks {r[:2]} {r[2][:80]}", r[0] and r[1])
r = go((17, 2205), (17, 2243))
check(f"Ozrinom's 17/2243 (MME: no exits out): walks as in 0.8.221 {r[:2]} {r[2][:80]}", r[0] and r[1])
asy = sorted(k for k, x in w.rooms.items() if "warped asylum" in x.name.lower())
nb = next(tuple(ex.to) for k in asy for ex in w.rooms[k].exits.values() if ex.to not in asy)
r = go(nb, asy[len(asy) // 2])
check(f"Warped Asylum (random-drop ways out): walks {r[:2]} {r[2][:80]}", r[0] and r[1])
r = go((14, 6159), (14, 6220), lvl=40, pick=10, strg=30, carrying=w.item_name(3702))
check(f"Stone Barracks with its key, strength 30: goes — 0.8.223, the way out is the key door's other side ({r[:2]})",
      r[0] and r[1])
r = go((8, 559), (8, 560), pick=300)
check(f"Dark-Elf Castle: the moat way, not the '1000' door at 8/559 S ({r[:2]}, {len(b.path.steps) if b.path else 0} steps)",
      r[0] and r[1] and b.path and len(b.path.steps) > 1)

# a pocket whose only way out needs a rope you don't carry (1/1542 Stone Tunnel / Webbed Cave)
pk_ = w.pocket((1, 1542), level=10, have=set(), cap=3000) or set()
into = next((tuple(e.to) for k in pk_ for e in w.rooms[k].exits.values()
             if e.kind == "item" and tuple(e.to) not in pk_ and tuple(e.to) in w.rooms), None)   # (just outside it)
if into:
    r = go(into, (1, 1542), lvl=10, pick=0, strg=30)
    # 0.8.223: the rope the way back out needs is bought first (Dark-Elf City's Large Hole), not refused
    check(f"rope pocket 1/1542 without a rope: gets a rope first ({r[:2]} {sorted(getattr(b.path, 'out_items', []) or [])})",
          r[0] and (191 in (getattr(b.path, "out_items", None) or []) or
                    any("way back out" in l and "getting it first" in l for l in s.logs[-15:])))
# the warehouse door: 0.8.223 board fix — 'use crowbar' opens it, so a Go to fetches a crowbar (tests/test_errands_0823.py)
r = go((1, 1104), (1, 1327))
check(f"warehouse door 1/1104 N: fetches a crowbar for 'use crowbar' ({r[:2]} {r[2][:120]})",
      r[0] and 570 in {t_["num"] for t_ in (b.errands.active or {}).get("todo") or []})

# speed: planning with every item and a max HP set
w.char = dict(w.char or {}, max_hp=156)
every = set(w.items)
w.forget_routes(); t = time.time(); w._dist_map((16, 320), level=60, have=every); dt = time.time() - t
check(f"dist_map with every item and the HP wall: {dt:.2f} s (0.8.222 before the fix: ~3.4 s)", dt < 2.5)

# the map-only "any way in?" check ignores the HP wall
trap = next(ex for ex in w.rooms[(8, 1835)].exits.values() if ex.kind == "trap")
w.char = dict(w.char, max_hp=156)
check("156 HP: the 200-damage trap is a wall for you", w.hp_wall(trap) == 200)
w.char = dict(w.char, gate_any=True)
check("…but not for the 'is there any way in?' check", w.hp_wall(trap) == 0)
w.char = dict(w.char); w.char.pop("gate_any", None)

check("'sea n' is a search", bool(SEARCH_CMD_RE.match("sea n")) and bool(SEARCH_CMD_RE.match("search ne")))
check("…'sell x' isn't", not SEARCH_CMD_RE.match("sell sword") and not SEARCH_CMD_RE.match("seal"))

# a party's classes on a room command (the barmaid's 'ask barmaid adventure' is Bards only)
ex = next((e for r_ in w.rooms.values() for e in r_.exits.values()
           if getattr(e, "req", None) and e.req.get("classes")), None)
if ex:
    okc = ex.req["classes"][0]
    bad = next(c for c in range(1, 30) if c not in ex.req["classes"])
    w.char = dict(w.char, **{"class": okc, "party_classes": []})
    a = w.req_ok(ex, 99, set())
    w.char = dict(w.char, **{"party_classes": [bad]})
    c2 = w.req_ok(ex, 99, set())
    check(f"class-only room command: you alone {a}, with a member of another class {c2}", a and not c2)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
