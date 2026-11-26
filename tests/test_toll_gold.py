"""0.8.227.6 (Dan, 2026-11-25: PVE Evolution had no money and Miserable kept taking him through the Silvermere town
gates — "You do not have enough to cover the toll of 5 gold crowns", Evolution stopped following, Miserable walked
back for him and paid the toll each way, over and over — instead of checking his cash and giving him 50 gold).
The follower tells the leader's MudPilot it couldn't pay; the leader gives gold once they're together. And a
follower's cash rides along in party sync, so a broke one is topped up before a walk with a toll on it."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_toll_gold"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name; st.party_sync = True
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    sent = []
    class Tel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): self.connected = False
    s.telnet = Tel(); s._entered = True
    s.send = lambda c, from_bot=False: sent.append(c)
    s.state.party = {"Miserable": {}, "Evolution": {}}
    s.state.level = 50
    s.partysync.asked = {"miserable", "evolution"}
    return s, sent

# --- follower: the gate refuses it
ev, evsent = make("Evolution")
ev.partysync.peers = {"Miserable": {"me": {"lvl": 62}}}
ev.state.wealth = 0
ev._line([("You are now following Miserable.", Style())])
ev._line([("You do not have enough to cover the toll of 5 gold crowns.", Style())])
ev._line([("You are no longer following Miserable.", Style())])
check(f"the follower asks the leader for the toll ({evsent})", "/Miserable @mpsync toll 500" in evsent)
evsent.clear()
ev._line([("You do not have enough to cover the toll of 5 gold crowns.", Style())])
check(f"…once a minute at most ({evsent})", not any("@mpsync toll" in c for c in evsent))
# its party sync carries its cash
ev.state.wealth = 20
ev.bot.held_items = lambda: []
info = ev.partysync.my_info()
check(f"party sync's 'me' line has the cash ({info})", "cash=20" in info)

# --- leader: told, and gives gold when Evolution's in the room
ms, mssent = make("Miserable")
ms.state.wealth = 15_000_000
ms.partysync.peers = {"Evolution": {"me": {"lvl": 50}}}
ms.state.view = type("V", (), {"players": ["Buddy"]})()
ms.partysync.command("Evolution", "toll 500")
check(f"not in the room: nothing given yet ({mssent})", not any(c.startswith("give ") for c in mssent))
ms.state.view = type("V", (), {"players": ["Evolution", "Buddy"]})()
ms.partysync.tick()
check(f"together: 50 gold to Evolution ({mssent})", "give 50 gold Evolution" in mssent)
mssent.clear(); ms.bot._ready = {}
ms.partysync.tick()
check(f"…just the once ({mssent})", not any(c.startswith("give ") for c in mssent))

# --- leader, before a walk: a follower whose synced cash is under the tolls gets topped up
ms2, s2 = make("Miserable")
ms2.state.wealth = 1_000_000
ms2.state.view = type("V", (), {"players": ["Evolution"]})()
ms2.partysync.peers = {"Evolution": {"me": {"lvl": 50, "cash": 120}}}
got = ms2.partysync.pay_tolls(1000)
check(f"walk with 1,000 copper of tolls, Evolution has 120: topped up to 50 gold ({s2})",
      got == ["Evolution"] and "give 49 gold Evolution" in s2)
s2.clear()
ms2.partysync.peers = {"Evolution": {"me": {"lvl": 50, "cash": 90_000}}}
check(f"one with plenty gets nothing ({s2})", ms2.partysync.pay_tolls(1000) == [] and not s2)
ms2.partysync.peers = {"Evolution": {"me": {"lvl": 50, "cash": 0}}}
ms2.state.wealth = 3000
check(f"a leader who can't spare it keeps his toll money ({s2})", ms2.partysync.pay_tolls(1000) == [] and not s2)

# cash only re-syncs when it crosses 50 gold, not every coin
ev.partysync.peers = {"Miserable": {"me": {"lvl": 62}}}
ev.state.wealth = 20; evsent.clear(); ev.partysync._me_checked = 0; ev.partysync._told_me = {}
ev.partysync.tick()
n1 = len([c for c in evsent if "@mpsync me" in c])
ev.state.wealth = 40; ev.partysync._me_checked = 0
ev.partysync.tick()
n2 = len([c for c in evsent if "@mpsync me" in c])
ev.state.wealth = 6000; ev.partysync._me_checked = 0
ev.partysync.tick()
n3 = len([c for c in evsent if "@mpsync me" in c])
check(f"cash re-sync only across 50 gold ({n1}, {n2}, {n3})", (n1, n2, n3) == (1, 1, 2))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
