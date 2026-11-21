"""Dan, 2026-11-07: (1) too heavy to pick something up → a party member's MudPilot picks it up ('@do get …'), and a
'get' that didn't take isn't sent again every look; (2) someone scripting on top of us (PVE): trail them round the
loop's rooms to take the kills — never out of the area."""
import os, sys, time
from types import SimpleNamespace
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, w, sc = s.bot, s.state, s.world, s.scripters
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def look(items=(), players=()):
    g.view = RoomView("Glade", {"N"}, [], list(items), list(players), time.time())
    g.view_seq = getattr(g, "view_seq", 0) + 1
    b._loot_wait = None


# ---------------------------------------------------------------- party picks up what you can't carry
ROOM = (17, 1630)
g.candidates = [ROOM]
g.party = {"Miserable": {}, "Buddy": {}, "Evolution": {}}
s.partysync.peers = {"Buddy": {"t": time.time(), "me": {"str": 60}}, "Evolution": {"t": time.time(), "me": {"str": 90}}}
st.auto_loot, st.loot_items = True, ["*"]
g.carrying = "silver ring"
g.enc = (4000, 4032, "Heavy", 99)
heavy = next(n for n, it in w.item_names.items() if int((it or {}).get("encum") or 0) > 100)
sent.clear()
look([(1, heavy)], ["Buddy", "Evolution"])
b.loot()
check(f"too heavy for me: the strongest MudPilot here picks it up ({sent})",
      f"/Evolution @do get {heavy}" in sent and not any(x.startswith("get ") for x in sent))
sent.clear(); look([(1, heavy)], ["Buddy", "Evolution"]); b.loot()
check(f"…not asked again on the next look ({sent})", not any("@do" in x for x in sent))
b._grab_asked[(ROOM, heavy)]["t"] -= 30
sent.clear(); look([(1, heavy)], ["Buddy", "Evolution"]); b.loot()
check(f"…still there 20 s on: the next one tries ({sent})", f"/Buddy @do get {heavy}" in sent)
sent.clear(); b._grab_asked[(ROOM, heavy)]["t"] -= 30; look([(1, heavy)], ["Buddy", "Evolution"]); b.loot()
check("…everyone's tried: nobody asked again", not any("@do" in x for x in sent))

# a 'get' that didn't take (weight unknown / encumbrance stale): left here, and the party asked
g.enc = None
b._grab_asked, b._no_item = {}, {}
sent.clear(); look([(1, "mystery bauble")], ["Buddy"]); b.loot()
check(f"weight unknown: tries it ({sent})", "get mystery bauble" in sent)
sent.clear(); look([(1, "mystery bauble")], ["Buddy"]); b.loot()
check(f"still there after the get: not sent again, Buddy asked ({sent})",
      "get mystery bauble" not in sent and "/Buddy @do get mystery bauble" in sent)
sent.clear(); look([(1, "mystery bauble")], ["Buddy"]); b.loot()
check(f"…and not again the look after ({sent})", not sent or sent == [""])
# alone: no one to ask, nothing sent
g.party = {}
b._no_item = {}
sent.clear(); g.enc = (4000, 4032, "Heavy", 99); look([(1, heavy)]); b.loot()
check("no party: just left there", not any("@do" in x or x.startswith("get ") for x in sent))

# ---------------------------------------------------------------- trailing a scripter, inside our loop only
A = next(k for k, r in w.rooms.items() if k[0] == 17 and "N" in r.exits and r.exits["N"].kind in ("", "normal", None)
         and r.exits["N"].to and w.room(r.exits["N"].to) and len(w.room(r.exits["N"].to).exits) >= 2)
B = w.rooms[A].exits["N"].to
out_dir = next(d for d, e in w.rooms[B].exits.items() if e.to not in (A, B))
b.path = SimpleNamespace(steps=[Step("", 0, "N", [], A, B), Step("", 0, "S", [], B, A)], title="Test loop", is_loop=True)
b.walking, b.loop = True, True
b.x.leading = lambda: True
g.max_hp, g.hp, g.max_ma, g.ma = 600, 600, 400, 400
st.scripter_trail = True
g.candidates = [A]
look(players=["Zimmer"]); sc.on_room(g)
sc.seen["Zimmer"] = {A: time.time() - 20, B: time.time() - 20}
sc.lair_empty(A); sc.lair_empty(B)
check(f"caught clearing ahead: trailing him ({sc.trail and sc.trail['name']})", sc.trail and sc.trail["name"] == "Zimmer")
look(players=["Zimmer"]); sc.on_room(g)
check("with him: the loop waits", sc.trailing([]))
sent.clear()
sc.feed_line("Zimmer just left to the north.")
look()
check(f"he went north, into our loop: after him ({sent})", sc.trailing([]) and sent and sent[-1] == "n")
g.candidates = [B]
look(players=["Zimmer"]); sc.on_room(g)
sent.clear()
word = {"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast", "NW": "northwest", "SE": "southeast",
        "SW": "southwest", "U": "up", "D": "down"}[out_dir]
sc.feed_line(f"Zimmer just left to the {word}.")
look()
check(f"he left the area ({out_dir}): not followed, the loop carries on ({sent})", not sc.trailing([]) and not sent
      and sc.trail)
look()
check("lost him: no standing about — the loop carries on", not sc.trailing([]))
look(players=["Zimmer"]); sc.on_room(g)
check("met him again: with him a moment", sc.trailing([]))
sc.trail["with"] -= 20
check("…he's staying put: loop on", not sc.trailing([]))
sc.feed_line("Zimmer just left to the south.")
look([], []); g.view.monsters = [("nightshade", None)]
sent.clear()
check("he ran off while we fight: fight first, don't leave", sc.trailing([("nightshade", None)]) and not sent)
g.view.monsters = []
check(f"…fight over: after him ({sent})", sc.trailing([]) and sent and sent[-1] == "s")
st.scripter_trail = False
sc.trail, sc.marked = None, {}
look(players=["Zimmer"]); sc.on_room(g)
check("trail off (the default): never trails", not sc.trail and config.Settings().scripter_trail is False)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
