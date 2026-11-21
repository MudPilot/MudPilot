"""Dan, 2026-11-16: Miserable + Revolution, PvP at the Stonecaps (Bristlewood Grove, 14/65xx), Go to Rodolfo's Salvage
Yard (14/10451). It set off 202 rooms (down the river itself) to buy a wooden skiff, then on Rego took the dry way —
only for the 'round Shadow Lord' pass to swap it back for the 129-room river. "Even if it's longer it's usually
shorter on this side than going to get a raft": the dry way, start to finish, and nothing to buy."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 50
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
START, YARD = (14, 6561), (14, 10451)
g.party = {"Miserable": {}, "Revolution": {}}
g.carrying = ""
b.held_items = lambda: None                    # inventory being re-read (as at 23:35)
direct = w.route(START, YARD, level=50)
check(f"the short way is dry, over the Dale Road ({len(direct)} rooms)", not b._needy_rooms(START, direct, set()))
check("…and passes Shadow Lord's spawn room on the Wagon Track (14/8390)", any(e.to == (14, 8390) for e in direct))
r = b.plan_route(START, YARD)
check(f"inventory not read: the round-the-boss pass doesn't take the River Lorian ({len(r) if r else None} rooms)",
      r and not b._needy_rooms(START, r, set()))
b.held_items = lambda: set()
w.forget_routes(); b.__dict__.pop("_way_memo", None)
r2 = b.plan_route(START, YARD)
check(f"carrying nothing: still dry ({len(r2) if r2 else None} rooms)", r2 and not b._needy_rooms(START, r2, set()))
# solo with a skiff on you: round him by river is fine then
sk = next(n for n, it in w.items.items() if it.get("name") == "wooden skiff")
g.party = {"Miserable": {}}
b.held_items = lambda: {sk}
w.forget_routes(); b.__dict__.pop("_way_memo", None)
r3 = b.plan_route(START, YARD)
check(f"alone with a skiff: round Shadow Lord by the river is allowed ({len(r3) if r3 else None} rooms)",
      r3 and not any(e.to == (14, 8390) for e in r3))
# Rego from mid-river (the 2nd plan at 23:48): the dry way, and the boss pass keeps it dry
g.party = {"Miserable": {}, "Revolution": {}}
b.held_items = lambda: set()
mid = next(e.to for e in w.route(START, YARD, level=50, avoid=frozenset({(14, 8390)}))
           if (w.room(e.to).name or "").startswith("The River Lorian, Middle"))
w.forget_routes(); b.__dict__.pop("_way_memo", None)
r4 = b.plan_route(mid, YARD)
wet = w.route(mid, YARD, level=50)
print(f"  (from mid-river {mid}: straight on {len(wet)} rooms, planned {len(r4) if r4 else None})")
# the log raft stashed at the Stonecaps (14/6556): that's the one to get, not a wooden skiff from a shop
lr = next(n for n, it in w.items.items() if it.get("name") == "log raft")
boats = frozenset({lr, sk} | {n for n, it in w.items.items() if it.get("name") in ("silverbark canoe", "river punt")})
st.raft_stash = {"room": [14, 6556], "items": ["log raft"], "t": 0}
check("a stashed log raft is picked over buying a skiff", b.carry_pick(boats) == lr)

src = b.errands.source_for(lr, toward=YARD, frm=START)
check(f"…and is fetched from the stash ({src and src['kind']} {src and src['room']})", src and src["kind"] == "stash")
check("…but a member short of one still gets one bought (not 'our stash')",
      (b.errands.source_for(b.carry_pick(boats, own=False)) or {}).get("kind") == "shop")
st.raft_stash = {}
check("nothing stashed: the cheapest a shop sells, as before", b.carry_pick(boats) != lr or
      (b.errands.source_for(lr) or {}).get("kind") == "shop")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
