"""0.8.227.7 (Dan, 2026-11-26: "Everytime i disband party i get an @comeback from revolution and it fucks up the
party"). Miserable leads Revolution to sell, then Dan disbands so Revolution can lead the script. Revolution saw
"Your party has been disbanded", took it for the party breaking, and sent @comeback. The leader's MudPilot now tells
its MudPilot followers first that the disband is meant; a party broken by accident still gets @comeback."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_disband_no_comeback"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name; st.party_sync = True; st.party_comeback = True
    s = Session(st); s._no_log_file = True
    wire = []
    class Tel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): wire.append(x)
        def close(self): self.connected = False
    s.telnet = Tel(); s._entered = True
    return s, st, wire

# ---- the leader: Dan types 'disband'
m, mcfg, mwire = make("Miserable")
m.state.party = {"Miserable": {}, "Revolution": {}}
m.partysync.peers = {"Revolution": {"me": {"lvl": 52}}}
m.bot.x._own_party = True
m.send("disband")
tell = [i for i, c in enumerate(mwire) if c == "/Revolution @mpsync disband"]
dis = [i for i, c in enumerate(mwire) if c == "disband"]
check(f"leader tells Revolution, ahead of the disband ({mwire})", tell and dis and tell[0] < dis[0])
mwire.clear()
m.bot.x._own_party = False; m.bot.x._following = "Revolution"
m.send("disband")
check(f"…not when it isn't leading ({mwire})", "/Revolution @mpsync disband" not in mwire)
mwire.clear()
m.bot.x._own_party = True; m.bot.x._following = None
m.send("disband", from_bot=True)
check(f"…nor for a disband MudPilot sends itself ({mwire})", "/Revolution @mpsync disband" not in mwire)

# ---- the follower
r, rcfg, rwire = make("Revolution")
r.state.party = {"Miserable": {}, "Revolution": {}}
r.bot.x._following = "Miserable"; r.bot.x._followed = "Miserable"
r.state.candidates = [(14, 6538)]
r.partysync.peers = {"Miserable": {"me": {"lvl": 52}}}
r.comeback.feed_line("Your party has been disbanded.")
# (a room that looks like others: it checks which with 'pro' first, then sends @comeback)
check(f"control: an accidental break still asks @comeback ({rwire})",
      any("@comeback" in c for c in rwire) or getattr(r.comeback, "_comeback_ask", None))
r.comeback._comeback_ask = None
rwire.clear()
r.comeback._self_left = 0; r._party_hold_until = 0
r.partysync.command("Miserable", "disband")
r.comeback.feed_line("Your party has been disbanded.")
check(f"told it's meant: no @comeback ({rwire})", not any("@comeback" in c for c in rwire)
      and not getattr(r.comeback, "_comeback_ask", None) and "pro" not in rwire)
rwire.clear()
r.send("invite Miserable", from_bot=True)
check(f"…no automatic invite during the pause ({rwire})", "invite Miserable" not in rwire)
r.remote._asked_invite = True
r.send("invite Miserable", from_bot=True)
r.remote._asked_invite = False
check(f"…but an @invite Dan asks for goes straight through ({rwire})", "invite Miserable" in rwire)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
