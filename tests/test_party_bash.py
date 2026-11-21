"""Dan, 2026-10-30, the Dark Passageway (8/433) door down — '[41 picklocks/strength]', bashable: three failed bashes and
MudPilot gave up ("won't open — going round it"). Bashing is a roll: up to 20 tries now, and the party's MudPilots in
the room help bash."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g = s.bot, s.state
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


check(f"bash up to 20 times ({st.attempt_bash})", st.attempt_bash == 20)
import json, tempfile
tmp = tempfile.mkdtemp()
_pp = config.Settings.profile_path
config.Settings.profile_path = classmethod(lambda cls, prof: os.path.join(tmp, prof + ".json"))
json.dump({"attempt_bash": 3, "settings_version": 14}, open(os.path.join(tmp, "Old.json"), "w"))
json.dump({"attempt_bash": 5, "settings_version": 14}, open(os.path.join(tmp, "Mine.json"), "w"))
check("an old save on the old default (3) goes to 20", config.Settings.load("Old").attempt_bash == 20)
check("…one you set yourself (5) stays", config.Settings.load("Mine").attempt_bash == 5)
config.Settings.profile_path = _pp
g.candidates = [(8, 433)]
g.party = {"Revolution": {}, "Buddy": {}, "Evolution": {}}
g.view = RoomView("Dark Passageway", {"NW"}, [], [], ["Buddy", "Evolution"], time.time())
s.partysync.peers = {"Buddy": {"t": time.time()}, "Evolution": {"t": time.time()}}
b.x.leading = lambda: True
b._party_bash("D")
helps = [c for c in sent if "@do" in c]
check(f"party in the room helps bash ({helps})",
      len(helps) == 2 and all("bash down" in c for c in helps) and "/Buddy @do bash down" in helps[0])
sent.clear(); b._party_bash("D")
check("…asked once, not on every bash", not sent)
g.view = RoomView("Dark Passageway", {"NW"}, [], [], ["Buddy"], time.time())
b._bash_help = None
sent.clear(); b._party_bash("D")
check(f"only those standing here ({sent})", len(sent) == 1 and sent[0].startswith("/Buddy"))
# Dan, 2026-10-30: the chrome key door — the leader is too weak, Buddy isn't: Buddy bashes, the leader tries the door
from mudpilot.worlddb import Exit
s.partysync.command("Buddy", "me lvl=20 str=90 cls=Paladin")
s.partysync.command("Evolution", "me lvl=20 str=40 cls=Druid")
s.partysync.members = lambda: ["Revolution", "Buddy", "Evolution"]
ex = Exit("N", None, "Key: 999 [or 80 picklocks/strength]", False, True, "key")
g.strength, g.picklocks = 70, 0
check(f"party member strong enough → the door is doable ({b.door_hands(ex)})", b.door_doable(ex) and b.door_hands(ex) == ["Buddy"])
ex2 = Exit("N", None, "Key: 999 [or 95 picklocks/strength]", False, True, "key")
check("nobody strong enough → not doable", b.door_doable(ex2) is False)
g.view = RoomView("Dark Passageway", {"NW"}, [], [], ["Buddy", "Evolution"], time.time())
b._bash_help = None; sent.clear()
b._party_bash("N", ["Buddy"])
check(f"only the strong one is asked ({sent})", len(sent) == 1 and sent[0].startswith("/Buddy @do bash north"))
# Dan, 2026-11-01: a helper with the picklocks (not the strength) picks it instead of bashing
s.partysync.command("Evolution", "me lvl=20 str=40 pick=90 cls=Druid")
g.candidates = [(8, 433)]
g.view = RoomView("Dark Passageway", {"NW"}, [], [], ["Evolution"], time.time())
s.partysync.members = lambda: ["Revolution", "Buddy", "Evolution"]
b._bash_help = None; sent.clear()
b._party_bash("D", ["Evolution"])
check(f"the picker picks ({sent})", sent and sent[0].startswith("/Evolution @do pick down"))
# party sync: strength / picklocks / traps go out again when they change (or turn up after 'st')
ps = s.partysync
ps.peers = {"Buddy": {"t": time.time()}}; ps.members = lambda: ["Revolution", "Buddy"]
ps.asked = {"buddy", "revolution"}; s._entered = True
g.level, g.strength, g.picklocks, g.traps, g.max_hp = 47, 0, 0, 0, 600
ps._told_me = {}; ps._me_checked = 0; sent.clear(); ps.tick()
first = [c for c in sent if "@mpsync me" in c]
g.strength, g.picklocks = 86, 25
ps._me_checked = 0; sent.clear(); ps.tick()
again = [c for c in sent if "@mpsync me" in c]
ps._me_checked = 0; sent.clear(); ps.tick()
check(f"stats sent again once 'st' fills them in ({again}), not every minute after ({sent})",
      first and again and "str=86" in again[0] and not [c for c in sent if "@mpsync me" in c])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
