"""Dan, 2026-11-01: breaking a party up so someone else can lead is a pain — the old leader's auto-invite pulls them
straight back ("with MegaMUD you gotta be quick as fuck"). A disband you meant (typed, or a friend's @do disband):
no automatic invites for a minute. An @invite someone asks for, and invites you type, still go."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, session as S
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.telnet.send_line = lambda c: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


s.send("invite Evolution", from_bot=True)
check("normally: auto-invite goes", "invite Evolution" in sent)
sent.clear(); s.send("disband")                       # you typed it
s.send("invite Evolution", from_bot=True)
check(f"after a disband you typed: no auto-invite ({sent})", sent == ["disband"])
s.send("invite Evolution")                            # typed by you
check("…but one you type goes", "invite Evolution" in sent)
s.state.view = RoomView("x", {"N"}, [], [], ["Evolution"], time.time())
s.state.party = {"Revolution": {}, "Evolution": {}}
s._party_sent = {}; sent.clear(); s.remote.c_invite("Evolution", "")
check(f"…and an @invite someone asks for goes ({sent})", any(c.startswith("invite Evolution") for c in sent))
s._party_hold_until = time.time() - 1
s._party_sent = {}; sent.clear(); s.send("invite Evolution", from_bot=True)
check("a minute later: auto-invite again", "invite Evolution" in sent)
# a friend's '@do disband' counts; MudPilot's own disband (to join someone) doesn't
st.remote_players = {"Buddy": ["all"]}
s._party_hold_until = 0
s.remote.c_do("Buddy", "disband")
s._party_sent = {}; sent.clear(); s.send("invite Evolution", from_bot=True)
check("after '@do disband' from a friend: paused", not sent)
s._party_hold_until = 0
s.send("disband", from_bot=True)
s._party_sent = {}; sent.clear(); s.send("invite Evolution", from_bot=True)
check("MudPilot's own disband (to join someone): no pause", "invite Evolution" in sent)
# MegaMUD's own command, and MudPilot's @disband
s._party_hold_until = 0; s.remote.c_do("Buddy", "disband party")
s._party_sent = {}; sent.clear(); s.send("invite Evolution", from_bot=True)
check("'@do disband party' pauses it too", not sent)
s._party_hold_until = 0; sent.clear()
out = s.remote.c_disband("Buddy", "")
check(f"@disband: 'disband party' sent, and paused ({sent}, {out})", sent == ["disband party"] and s._party_hold_until > time.time())
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
