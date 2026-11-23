"""PvP hang-up, player-seen hang-up and look-toward-sound, driven by fake lines."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style

def make(**kw):
    st = config.Settings(); st.save = lambda: None; st.pvp_realm = True   # (a PvP realm: PVE never hangs up on PvP-looking lines)
    for k, v in kw.items(): setattr(st, k, v)
    s = Session(st)
    sent, closed = [], []
    class FakeTel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): closed.append(1); self.connected = False
    s.telnet = FakeTel(); s._want_connected = True
    feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
    return s, sent, closed, feed

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

# 1. PvP: a player attacking you
s, sent, closed, feed = make()
feed("[HP=650/MA=394]:Town Gates", "Obvious exits: north, south", "Bob swings at you with his longsword!")
check("PvP attack hangs up", closed and not s._want_connected)
# a monster line must not
s, sent, closed, feed = make()
feed("The orc swings at you with a club!", "The giant rat bites you for 4 damage!")
check("monster attacks don't hang up", not closed)
# a party member hitting you: hang up (Dan, 2026-10-31 — friendly fire, but out you go; they stay a friend)
s, sent, closed, feed = make()
s.state.party = {"Miserable": {}}
feed("Miserable swings at you with a dagger for 12 damage!")
check("party member hitting you hangs up", closed)
# PvP off
s, sent, closed, feed = make(hangup_on_pvp=False)
feed("Bob swings at you with his longsword!")
check("PvP option off", not closed)

# 2. Player seen
s, sent, closed, feed = make(hangup_on_player=True, pvp_friends=["Jim"])
feed("[HP=650/MA=394]:Town Gates", "Also here: Jim.", "Obvious exits: north")
check("friend in room ignored", not closed)
feed("[HP=650/MA=394]:Town Gates", "Also here: Bob, orc.", "Obvious exits: north")
check("stranger in room hangs up", closed)
s, sent, closed, feed = make(hangup_on_player=True)
feed("Bob walks into the room from the north.")
check("stranger arriving hangs up", closed)
s, sent, closed, feed = make()
feed("[HP=650/MA=394]:Town Gates", "Also here: Bob.", "Obvious exits: north")
check("player-seen off by default", not closed)

# 3. Stay offline window
s, sent, closed, feed = make(hangup_stay_offline=10)
s.safety.hangup("message: the boss is up")        # (0.8.224: not a PvP one — those never come back in by themselves)
check("stay-offline blocks reconnect", closed and not s.safety.may_reconnect() and s._want_connected)
check("…and after it, goes back in (not held at the MajorMUD menu)", not getattr(s, "hold_realm", False))
s, sent, closed, feed = make(hangup_stay_offline=10)
feed("Bob swings at you with his longsword!")
check("0.8.224 (Dan): a PvP hang-up never comes back in, stay-offline or not",
      closed and getattr(s, "hold_realm", False) and not s._want_connected)
s, sent, closed, feed = make()
feed("Bob swings at you with his longsword!")
check("stay offline 0: held at the menu until you go in", getattr(s, "hold_realm", False) and not s._want_connected)

# 4. Look toward sound, 3 s ignore per direction
s, sent, closed, feed = make()
for _ in range(5): feed("You hear movement to the northeast.")
feed("You hear footsteps to the south.", "You hear movement above you.")
check("one look per direction", sent.count("l ne") == 1 and "l s" in sent and "l u" in sent)
s.safety._heard["NE"] -= 3.1
feed("You hear movement to the northeast.")
check("looks again after 3 s", sent.count("l ne") == 2)
s, sent, closed, feed = make(look_on_sound=False)
feed("You hear movement to the northeast.")
check("look-on-sound off", not sent)

# 5. Peek doesn't overwrite the current room
s, sent, closed, feed = make()
feed("[HP=650/MA=394]:Town Gates", "Also here: Bob.", "Obvious exits: north")
here = s.state.view
s.send("look north")
feed("Market Square", "Also here: orc, orc.", "Obvious exits: south")
check("peek kept apart", s.state.view is here and s.state.peek_view and s.state.peek_view.name == "Market Square")
print("ALL PASS" if ok else "SOME FAILED")
