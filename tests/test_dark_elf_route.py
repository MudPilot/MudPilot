"""Dan, 2026-10-28: Go to Dark-Elf City went through the Negative Power Plane (or asked about it) because MudPilot
didn't know the normal way's openers: the bloodstone orb ('ask commander orb' at 8/459) and the gate key (the
obsidian statue 'touch statue' calls up at 8/461). It should fetch those and walk in — never via the amber
talisman (roof jumping splits a party) — and route on the party's lowest level, saying so when that's what stops it.
Also: the raft shop is both Arlysia's docks and the Silvermere pier; King Crab's Go to lands where the crab spawns."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.char_level = 47; st.my_name = "Miserable"
st.auto_get_items = True; st.bash_key_doors = False
s = Session(st)
s.state.inv_at = float("inf")                # (the pack set here is the fresh read)
s.world = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s.state.world = s.world
s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True; s.state.level = 47
s.on_no_route = lambda m: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w, b = s.world, s.bot
check("orb: 'ask commander orb' at 8/459", any(a["cmd"] == "ask commander orb" and a["room"] == (8, 459)
                                              for a in w.npc_gives.get(807, [])))
check("gate key: 'touch statue' at 8/461 calls the obsidian statue", ((8, 461), "touch statue") in w.summons.get(347, []))
s.state.candidates = [(1, 1)]
s.state.candidates = [(1, 1)]
s.state.carrying = "astral staff (Weapon Hand)"; s.state.keys = ""; s.state.inv_seq += 1
s.state.party = {"Miserable": {}, "Revolution": {}}
s.comeback.leading = lambda: True
npp = b.avoid_set()
b.goto((8, 462))
mp = b.path
crossed = mp and any(x.room in npp for x in mp.steps)
check(f"Go to Dark-Elf City: no NPP ({mp and len(mp.steps)} steps)", mp is None or not crossed)
todo = (b.errands.active or {}).get("todo") or []
kinds = {w.item_name(t["num"]): (t["kind"], t["room"], t.get("cmd") or t.get("summon")) for t in todo}
check(f"fetches the orb by asking ({kinds})", kinds.get("bloodstone orb", ("",))[0] == "ask")
check("…and the gate key from the statue", kinds.get("gate key", ("", None, ""))[2] == "touch statue")
check("no amber talisman", "amber talisman" not in kinds)
check(f"detour said ({[l for l in s.logs if 'Detouring' in l][-1:]})", any("Detouring to" in l for l in s.logs))
fr = w.route((1, 1), (8, 462), level=47, have=b.every_item(), avoid=npp)
check(f"…through the Fungus Tunnel, 7/1405 (Dan's way; {fr and len(fr)} rooms)",
      fr and any(ex.to == (7, 1405) for ex in fr))
b.stop("Stopped by you"); b.errands.cancel()
# PVE live, 17:06: orb in hand in the Commander's Office, on to 8/493 — "only way is through Black Wasteland"; the
# one door left (the gate key, '[or 101 picklocks]') can be picked or its key fetched: go that way
s.state.candidates = [(8, 459)]
s.state.carrying = "astral staff (Weapon Hand), bloodstone orb"; s.state.inv_seq += 1
b._avoid_blocked = None
r = b.plan_route((8, 459), (8, 493))
check(f"orb in hand → the gate way, not Black Wasteland ({r and len(r)} rooms)",
      r is not None and not any(ex.to in npp for ex in r) and any(ex.to == (8, 462) for ex in r))
s.state.picklocks = 182                       # PVE: good enough to pick it — but the statue's key is the way
b.goto((8, 493))
todo = (b.errands.active or {}).get("todo") or []
check(f"…and fetches the gate key from the statue even with picklocks 182 ({[(w.item_name(t['num']), t.get('summon')) for t in todo]})",
      any(w.item_name(t["num"]) == "gate key" and t.get("summon") == "touch statue" for t in todo))
b.stop("Stopped by you"); b.errands.cancel(); s.state.picklocks = 0
s.state.carrying = "astral staff (Weapon Hand)"; s.state.inv_seq += 1
# party level: a level-30 follower can't take the level-40 portal
s.partysync.peers["Revolution"] = {"lvl": 30, "t": 0}
check(f"routes on the lowest level ({b.route_level()})", b.route_level() == 30)
st.check_needed_items = False; st.auto_get_items = False
s.state.candidates = [(8, 558)]
tgt = (8, 992)
r = b.goto(tgt)
check(f"too low → says so ({b.no_route_msg[:110]})", not r and "aren't big" in b.no_route_msg)
s.partysync.peers.clear()
st.check_needed_items = True
# rafts: nearest Boat Launch room, not always Arlysia's
raft = next(n for n, it in w.items.items() if it.get("name") == "log raft")
s.state.candidates = [(1, 1)]
src = b.errands.source_for(raft)
check(f"raft from the Silvermere pier, not Arlysia ({src and src['room']})", src and src["room"] == (1, 1813))
# King Crab: the label's monster spawn room
s.known_rooms = lambda: [("Ocean", "King Crab", (16, 297))]
tw = b._reachable_twin((1, 1), (16, 297))
check(f"King Crab → 16/287 ({tw and tw[0]})", tw and tw[0] == (16, 287))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
