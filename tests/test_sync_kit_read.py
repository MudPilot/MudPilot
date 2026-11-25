"""0.8.227.5 (Dan: PvP Miserable waited at Shadow Lord's door on his Go to Kingsport — the way round takes the river,
and after a restart Revolution's party sync carried no 'kit=': its pack hadn't been read since logging in, so the
leader planned the party as raftless). A MudPilot in a party with other MudPilots reads its pack when it hasn't,
and the 'kit=' with the raft goes out."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_sync_kit_read"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.party_sync = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
s.send = lambda c, from_bot=False: sent.append(c)
g, ps = s.state, s.partysync
g.party = {"Miserable": {}, "Revolution": {}}
g.level = 52
ps.asked = {"miserable"}
ps.peers = {"Miserable": {"me": {"lvl": 52}}}
check("just logged in: the pack isn't known", s.bot.held_items() is None)
ps.tick()
check(f"party sync reads the pack first ({sent})", "i" in sent)
sent.clear(); ps._me_checked = 0
ps.tick()
check(f"…not again straight away ({sent})", "i" not in sent)
g.carrying = "log raft, rope and grapple, 20 gold crowns"
sent.clear(); ps._me_checked = 0; ps._told_me = {}
ps.tick()
raft = s.world.item_names["log raft"]["num"]
me = [c for c in sent if "@mpsync me" in c]
check(f"…then its 'kit=' carries the raft ({me})", me and f"{raft}" in me[0].split("kit=")[-1].split()[0].split("."))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
