"""Dan, 2026-11-01: 0.8.131/0.8.132 hung Miserable, Revolution and Buddy up on each other with "friendly fire?" — every
one of them a false alarm. The real lines from their traces, replayed: none may hang up. A real hit from a party member,
or a stranger's attack, still does."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.hangup_on_pvp = True; st.pvp_realm = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
hung = []
s.safety.hangup = lambda reason, manual=False: hung.append(reason)
s.safety.pvp_hangup = lambda reason, victim: hung.append(reason)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g = s.state
g.party = {"Miserable": {}, "Revolution": {}, "Evolution": {}, "Buddy": {}}
g.view = RoomView("Rotting Glade, Trail", {"S", "E"}, [], [], ["Revolution", "Evolution", "Buddy", "Stranger"], time.time())
FALSE_ALARMS = [
    "Revolution moves to attack everyone in the room.",                     # Miserable, 00:12:58 (area spell)
    "Miserable moves to attack everyone in the room.",                      # Revolution, same moment
    "Revolution casts greater mend on you, healing 26 damage!",             # Miserable, 00:37
    "Revolution casts greater mend on you, healing 30 damage!",             # Miserable, 00:39:59
    "Revolution casts greater healing on you, healing 67 damage!",          # Buddy, 00:28:16
    "Revolution casts greater healing on Evolution, healing 40 damage!",
    "Revolution makes a mighty gesture!",
    "Revolution moves to attack happy nightshade.",
    "Revolution casts holy aura, surrounding everyone in the party in a white glow!",
    "Revolution telepaths: @stop",
    "Stranger casts cure poison on you!",
    "Stranger casts healing on you, healing 20 damage!",
]
for ln in FALSE_ALARMS:
    hung.clear()
    s.safety.feed_line(ln)
    check(f"no hang-up: {ln!r} ({hung})", not hung)
REAL = [
    "Revolution swings at you with his mace for 20 damage!",
    "Revolution moves to attack you.",
    "Stranger swings at you with a dagger!",
    "Stranger casts fireball on you for 40 damage!",
]
for ln in REAL:
    hung.clear()
    s.safety.feed_line(ln)
    check(f"hangs up: {ln!r} ({hung})", hung)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
