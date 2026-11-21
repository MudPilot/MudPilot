"""Buddy, 2026-10-31: Evolution reconnected, the party reshuffled, and for a moment Revolution wasn't on Buddy's party list —
"Revolution casts greater healing on Evolution!" was read as Revolution attacking Evolution, and Buddy went after
its own party leader for 13 minutes. A heal is never an attack, and a friend is never a PvP target."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.defend_party_pvp = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
x, g = s.bot.x, s.state
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g.view = RoomView("Ancient Ruin, Palace Gates", {"N"}, [], [], ["Revolution", "Evolution", "Stranger"], time.time())
g.party = {"Buddy": {}, "Evolution": {}}                 # Revolution not on the list this second
x.note_line("Revolution casts greater healing on Evolution!")
check(f"a heal on a party member isn't an attack ({x.pvp_target})", not x.pvp_target)
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
x.is_friend("x")                                        # (the party is noted as it's seen)
g.party = {"Buddy": {}, "Evolution": {}}
x.note_line("Revolution casts fireball on Evolution for 40 damage!")
check(f"someone in the party a moment ago is never a target ({x.pvp_target})", not x.pvp_target)
x.note_line("Stranger casts fireball on Evolution for 40 damage!")
check(f"a stranger hurting the party still is ({x.pvp_target})", x.pvp_target == "Stranger")
x.stop_pvp()
s.partysync.peers = {"Zed": {"t": time.time()}}
x.start_pvp("Zed", "attacked Evolution")
check("a MudPilot partner is never a target", not x.pvp_target)
x.pvp_target = "Revolution"
x.pvp_tick()
check("an old target that's a friend is dropped", not x.pvp_target)
# Dan, 2026-10-31: someone in your party attacks you → hang up, but they stay a friend with their @ permissions
hung = []
s.safety.hangup = lambda reason, manual=False: hung.append(reason)
st.remote_players = {"Revolution": ["all"]}
g.party = {"Buddy": {}, "Revolution": {}}
s.safety.feed_line("Revolution casts greater healing on you!")
check(f"a heal from the party: no hang-up ({hung})", not hung)
s.safety.feed_line("Revolution moves to attack everyone in the room.")
check(f"a party member's area spell ('moves to attack everyone'): no hang-up ({hung})", not hung)
s.safety.feed_line("Revolution swings at you with his mace for 20 damage!")
check(f"a party member hitting you: hang up ({hung})", hung and "Revolution" in hung[0])
check("…their @ permissions untouched", st.remote_players == {"Revolution": ["all"]})
check("…and they're still a friend, not a PvP target", x.is_friend("Revolution") and not x.pvp_target)
# marked Friend in Game Data → Players: never a PvP target, whatever happened before
p = s.players.get("Vex") or s.players._seen("Vex"); p["relationship"] = "Friend"
x.start_pvp("Vex", "attacked Evolution")
check("Game Data Friend is never a PvP target", not x.pvp_target)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
