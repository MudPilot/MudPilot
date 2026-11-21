"""Miserable PVE, 2026-11-05: "Lightning strikes you for 2 damage!" in the manscorpion king fight hung him up as
'PvP: attacked by Lightning'. A monster / room spell's first word isn't a player — unless we've seen a player by it."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style


def make():
    st = config.Settings(); st.save = lambda: None; st.pvp_realm = True   # (a PvP realm: PVE never hangs up on PvP-looking lines)
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    closed = []
    class FakeTel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): pass
        def close(self): closed.append(1); self.connected = False
    s.telnet = FakeTel(); s._want_connected = True
    feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
    return s, closed, feed


ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


s, closed, feed = make()
check(f"'lightning' is a spell word ({len(s.safety._spell_heads())} heads)", "lightning" in s.safety._spell_heads())
feed("Shards of stone slice you for 55 damage!", "Lightning strikes you for 2 damage!")
check("Lightning strikes you: no hang-up", not closed)

s, closed, feed = make()
feed("Bob strikes you for 20 damage!")
check("a player striking you still hangs up", closed)

s, closed, feed = make()
s.players.data["lightning"] = {"name": "Lightning", "t": time.time()}
feed("Lightning strikes you for 20 damage!")
check("…and a real player named Lightning does too", closed)

s, closed, feed = make()
feed("Ruby backstabs you for 300 damage!")
check("an unseen 'Ruby' backstabbing you still hangs up", closed)

# Revolution PVE, 2026-11-06, in the Mausoleum: "He bites into Skittles, drinking their blood!" (the vampire magus)
s, closed, feed = make()
s.state.party = {"Revolution": {}, "Skittles": {}}
feed("He bites into Skittles, drinking their blood!")
check("'He bites into Skittles': a pronoun, not a player", not closed)
# a PVE realm: a line that only looks like PvP doesn't hang up; the server's own PvP message still does
s, closed, feed = make(); s.settings.pvp_realm = False
feed("Bob strikes you for 20 damage!")
check("PVE realm: 'Bob strikes you' doesn't hang up", not closed)
feed("Server PvP Message: Bob has attacked you!")
check("…a Server PvP Message still does (and marks the realm PvP)", closed and s.settings.pvp_realm)
sys.exit(0 if ok else 1)
