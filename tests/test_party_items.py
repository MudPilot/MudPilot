"""Paths where each walker needs their own item (a raft for the river, the golden idol): the room spells say
so; leading a party, MudPilot asks everyone '@have log raft' and buys one for whoever hasn't. And a new quest
flag is reported to the leader."""
import os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from types import SimpleNamespace
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "world.db")
shutil.copy2(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"), db)
w = WorldDB(db)
RAFT = next(n for n, it in w.items.items() if (it.get("name") or "").lower() == "log raft")
river = next(k for k, sp in w.room_spells.items() if (w.spells.get(sp) or {}).get("Name") == "river damage")
src = next(k for k, r in w.rooms.items() for e in r.exits.values() if e.to == river)
ex = next(e for e in w.rooms[src].exits.values() if e.to == river)
need = w.carry_needs([(src, ex)])
check(f"walking into the river needs a raft or boat ({need and sorted(w.item_name(n) for n in need[0])})",
      need and RAFT in need[0])
quest = next(k for k, sp in w.room_spells.items() if "quest item place" in ((w.spells.get(sp) or {}).get("Name") or ""))
qsrc = next(k for k, r in w.rooms.items() for e in r.exits.values() if e.to == quest)
qex = next(e for e in w.rooms[qsrc].exits.values() if e.to == quest)
check("a quest room that takes your quest item isn't a 'carry this' room", w.carry_needs([(qsrc, qex)]) == [])
idol = [(k, e) for k, r in w.rooms.items() for e in r.exits.values() if "post-857" in (e.etype or "")]
check("the golden idol teleport exit needs the idol",
      idol and [w.item_name(n) for n in w.carry_needs(idol[:1])[0]] == ["golden idol"])

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
s.world = w
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.send = lambda c, from_bot=False: sent.append(c)
b, e, g = s.bot, s.bot.errands, s.state
g.party = {"Miserable": {}, "Revolution": {}}
s.comeback.leading = lambda: True
b.carry_pick = lambda items, own=True: RAFT
mp = SimpleNamespace(title="Go to 14/520 River", steps=[])
check("leading: asks the party @have", e.party_check(mp, False, [frozenset({RAFT})]) and
      "/Revolution @have log raft" in sent)
check("…ignores a telepath that isn't an answer", not e.have_answer("Revolution", "{Quest flag: x (1) = 1}"))
check("…reads MegaMUD's / MudPilot's answer", e.have_answer("Revolution", "{no log raft}"))
shop = (17, 580)
e.source_for = lambda n, toward=None: {"num": n, "kind": "shop", "room": shop, "what": "sold: Boat Launch (17/580)"}
b.set_mode = lambda m: None
e.asking["t"] = time.time() - 1
e.tick()
check(f"…Revolution has none: off to buy one for him ({e.active and e.active['todo']})",
      e.active and e.active["todo"][0].get("for") == "Revolution")
g.candidates = [shop]
b.held_items = lambda: {RAFT}                 # our own raft must not count as his
sent.clear()
e.tick()
check(f"in the shop: buys it ({sent})", "buy log raft" in sent)
e.active["todo"][0]["bought"] = time.time() - 3
e.tick()
check(f"…and hands it over ({sent})", "give log raft to Revolution" in sent)
# all said yes: walk on
started = []
b.start_path = lambda mp, loop=None, checked=False: started.append(checked)
e.active = None
e._rounds.clear()
e.party_check(mp, False, [frozenset({RAFT})])
e.have_answer("Revolution", "{yes: log raft}")
e.tick()
check(f"everyone has one: the walk goes on ({started})", started == [True])
# MegaMUD's real answers, as a say: '{no}' then '{yes: 1}'
e._rounds.clear(); started.clear()
e.party_check(mp, False, [frozenset({RAFT})])
check("MegaMUD's '{no}' (said to us) is read", s.remote.feed_line('Revolution says (to you) "{no}"') is True
      and e.asking["ans"].get(("Revolution", RAFT)) is False)
e.asking = None
e.party_check(SimpleNamespace(title="Go to 2", steps=[]), False, [frozenset({RAFT})])
s.remote.feed_line('Revolution says (to you) "{yes: 1}"')
check("…and '{yes: 1}'", e.asking["ans"].get(("Revolution", RAFT)) is True)
e.asking = None
# Dan, 2026-11-19 (Pavilion of Hides): everyone said yes, walk; Stop mid-ask; then Go to again → refused
e._rounds.clear(); started.clear(); e.giving_up = None
pm = SimpleNamespace(title="Go to 16/801 Pavilion of Hides", steps=[])
for _ in range(3):                                    # three rounds everyone passes
    e.party_check(pm, False, [frozenset({RAFT})]); e.have_answer("Revolution", "{yes: log raft}"); e.tick()
e.party_check(pm, False, [frozenset({RAFT})]); e.asking = None   # stopped before the answers came in
e.party_check(pm, False, [frozenset({RAFT})]); e.asking = None
check(f"rounds everyone passed / that were stopped don't count as 'asked twice' ({started}, {e.giving_up})",
      started == [True] * 3 and not e.giving_up and "/Revolution @have log raft" in sent)
# quest flags: a new one is told to the leader when following
b.x._following = "Revolution"
st.known_abils = {"134": 2}
g.abil_rows = {("granted", 134): (9, time.time() + 1)}
b._abil_read = ("sent", time.time() - 5)
sent.clear()
b._read_quest_flags()
check(f"new quest flag → telepath the leader ({sent})", any(c.startswith("/Revolution {Quest flag:") for c in sent))
st.known_abils = {"134": 9, "145": 5}
g.abil_rows = {("granted", 134): (9, time.time() + 1), ("granted", 145): (6, time.time() + 1)}
b._abil_read = ("sent", time.time() - 5)
sent.clear()
b._read_quest_flags()
check(f"ManaRegen going up isn't a quest flag ({sent})", not any("Quest flag" in c for c in sent))
b.note_quest_cmd("ask sphinx E")
check("a quest-style command asks for 'abil' again soon", b._quest_poke > 0)
from mudpilot import board_fixes
board_fixes.apply(w)
lev = w.rooms[(3, 1)].exits.get("U")
check("Paradigm: 3/1 up to the catacombs by levitation potion (each walker needs one)",
      lev and lev.to == (9, 1009) and [w.item_name(n) for n in w.carry_needs([((3, 1), lev)])[0]] == ["potion of levitation"])
r = w.route((3, 1), (9, 1009), level=47)
check("…and Go to plans through it", r and r[0] is lev)
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
