"""0.8.223, errand fixes from the 2026-11-21 bug hunt (HUNT_1121.md "For Dan" 11 and 13):
- the warehouse door 1/1104 N opens with 'use crowbar' (board fix): a Go to behind it walks with a crowbar, fetches one
  (General Store) without, and the step sends 'use crowbar'; with no source it's refused, naming the crowbar.
- an item only an NPC carries (the moldy key: the sleazy shopkeeper, 8/486) is never fetched (no NPC killing); the
  reason says who has it.
- an errand leg that needs an item the errand gets later (the log raft for the Silver River on the way to the fang
  farm, m349 #6) gets it first — and the errand still runs to the end, no ping-pong.
- a waterskin whose shop is reached only through the Go to's own target isn't fetched first (fight3 #4, 12/977)."""
import os, sys, time, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_errands_0823"))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.char_level = 55; st.my_name = "Tester"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
s.on_no_route = lambda m: None
w, b, g = s.world, s.bot, s.state
logs = []
_log = b.log
b.log = lambda m, *a, **k: (logs.append(m), _log(m, *a, **k))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def go(here_, tgt, lvl=55, pick=182, strg=60, carrying="astral staff", hp=900):
    b.stop("Stopped by you"); b.errands.cancel(); s.trips.reset("t"); b._pending_abil = None
    g.candidates = [here_]; g.level = lvl; st.char_level = lvl; g.picklocks, g.strength = pick, strg
    g.max_hp = g.hp = hp; g.max_hp_read = True; g.wealth = 5000000
    g.carrying = carrying; g.keys = ""; g.inv_seq += 1; w.forget_routes(); b.no_route_msg = ""
    b._flags_reread = {tuple(tgt): time.time()}       # (no 'abil' re-read: there's no game to answer it)
    del logs[:]
    r = b.goto(tgt)
    return r, b.walking, b.no_route_msg or ""

todo = lambda: [(t["kind"], w.item_name(t["num"])) for t in ((b.errands.active or {}).get("todo") or [])]

# ---- 11: the warehouse door
door = w.rooms[(1, 1104)].exits["N"]
check(f"warehouse door 1/1104 N: 'use crowbar' with the crowbar ({door.action_cmds()}, {door.action_items()})",
      door.action_cmds() == ["use crowbar"] and door.action_items() == [570] and not w.stuck_door(door))
check("no DOOR_OPENERS special case left for it", ((1, 1327), "N") not in w.DOOR_OPENERS)
r = go((1, 1103), (2, 26), carrying="astral staff, crowbar")
pre = [x.pre for x in (b.path.steps if b.path else []) if x.room == (1, 1104) and x.dir == "N"]
check(f"Go to 2/26 (warehouse loft) carrying a crowbar: walks, 'use crowbar' at the door ({r[:2]}, {pre})",
      r[0] and r[1] and pre and "use crowbar" in (pre[0] or []))
r = go((1, 1103), (2, 26))
check(f"…without one: fetches a crowbar first ({r[:2]}, {todo()})",
      r[0] and not r[1] and ("shop", "crowbar") in todo())
ob = w.gear[570]["obtained"]
w.gear[570]["obtained"] = "Textblock #287"
try:
    r = go((1, 1103), (2, 26))
    msg = " ".join(logs)
    check(f"…no known source: refused, naming the crowbar ({r[:2]}, {r[2][:120] or msg[-160:]})",
          not r[1] and not b.errands.active and "crowbar" in (r[2] + msg))
finally:
    w.gear[570]["obtained"] = ob

# ---- 11: keys only an NPC carries
moldy = next(n for n, it in w.items.items() if it.get("name") == "moldy key")
who = w.npc_holder(moldy)
check(f"moldy key: carried by the sleazy shopkeeper ({who})", "sleazy shopkeeper" in who and "8/486" in who)
check("…not a source MudPilot fetches from (no NPC killing)", b.errands.source_for(moldy) is None)
check("a sold item has no NPC holder (waterskin)", w.npc_holder(283) == "")
from mudpilot.megamud_files import path_from_route
g.candidates = [(8, 453)]
mp = path_from_route(w, (8, 453), [w.rooms[(8, 633)].exits["D"]] if "D" in w.rooms[(8, 633)].exits else [],
                     name="Go to 8/594 Closet")
okp, why = b.errands.plan(mp, False, [moldy])
check(f"errand refusal names who has it ({okp}, {why})", not okp and "sleazy shopkeeper" in why
      and "moldy key" in why and "won't kill" in why)
bl = w.why_no_route((8, 531), w.rooms[(8, 531)].exits["W"].to, level=60, have=set())
check(f"why_no_route: the Dark-Elf Tower door needs the glowing key from the sleazy shopkeeper ({bl[:1]})",
      any("glowing key from the sleazy shopkeeper (8/486)" in (x[2] or "") for x in bl))
bl = w.why_no_route((9, 1426), w.rooms[(9, 1426)].exits["N"].to, level=60, have=set())
check(f"…and the basalt key door names Morukai ({bl[:1]})", any("basalt key from Morukai (9/1425)" in (x[2] or "") for x in bl))

# ---- 13: the log raft before the fang farm's Silver River (m349 #6), and the errand finishes
r = go((1, 1), (3, 608), lvl=10, pick=0, strg=30, carrying="club", hp=300)
check(f"Go to 3/608 (L10): an errand ({r[:2]}, {todo()[:3]}…)", r[0] and b.errands.active)
b.ready = lambda *a, **k: True                       # (no throttles: one tick = one step)
raft = next(n for n, it in w.items.items() if it.get("name") == "log raft")
held = ["club"]
seen, steps, done = [], 0, False
while steps < 40:
    steps += 1
    ea = b.errands.active
    if not ea:
        done = True
        break
    cur = ea["todo"][0]
    b.walking = False
    del logs[:]
    b.errands.tick()
    ea = b.errands.active
    if not ea:
        done = True
        break
    head = ea["todo"][0]
    seen.append((head["kind"], w.item_name(head["num"])))
    if steps == 1:
        check(f"…the farm leg needs the log raft: it's got first ({todo()[:3]})",
              todo()[0] == ("shop", "log raft") and any("this errand gets later" in m for m in logs))
    # arrive at the current item's room with it in hand
    rm = head.get("room") or (head.get("rooms") or [None])[0]
    if rm:
        g.candidates = [tuple(rm)]
    nm = w.item_name(head["num"])
    held.append(nm)
    g.carrying = ", ".join(held); g.inv_seq += 1
check(f"…the errand runs to the end in {steps} steps, no item twice in a row "
      f"({' > '.join(n for _k, n in seen)})", done and steps < 40 and all(seen[i] != seen[i + 1] for i in range(len(seen) - 1)))
check("…the raft was got before any fang farming",
      seen and ("shop", "log raft") in seen and all(k != "farm" for k, _n in seen[:seen.index(("shop", "log raft"))]))

# ---- 13: the waterskin past the target (fight3 #4)
r = go((12, 1747), (12, 977), lvl=25, pick=0, strg=60, carrying="club", hp=300)
check(f"Go to 12/977 from 12/1747 without a waterskin: straight there, not via Nekojin's store through 12/977 "
      f"({r[:2]}, {len(b.path.steps) if b.path else 0} steps)",
      r[0] and r[1] and not b.errands.active and b.path and len(b.path.steps) < 80
      and any("goes through 12/977 itself" in m for m in logs))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
