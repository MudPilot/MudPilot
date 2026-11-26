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
# Dan: "if i have revolution drop his log raft will mudpilot know that?" — the drop updates the pack, and the next
# sync (within a minute) tells the leader the kit changed
from mudpilot.ansi import Style
s._line([("You dropped log raft.", Style())])
sent.clear(); ps._me_checked = 0
ps.tick()
me = [c for c in sent if "@mpsync me" in c]
check(f"dropped the raft: the next sync's kit hasn't got it ({me})",
      me and f"{raft}" not in me[0].split("kit=")[-1].split()[0].split("."))
# the leader's side: that line replaces the kit it knew (no raft any more)
ps.peers["Revolution"] = {"me": {"lvl": 52, "kit": [191, raft]}}
ps._note_me("Revolution", me[0].split("@mpsync me ", 1)[1])
check(f"the leader's copy loses the raft ({ps.peers['Revolution']['me']})",
      raft not in ps.peers["Revolution"]["me"].get("kit", []))
# and an older '@have log raft' yes doesn't outlast the drop: the leader's party_carry goes by the newer kit
st.my_name = "Miserable"; g.party = {"Miserable": {}, "Revolution": {}}
s.bot.errands.known_have = {("revolution", raft): (True, time.time() - 600)}
s.partysync.info = lambda: {"Revolution": {"kit": [191]}}
ps.peers["Revolution"]["kit_t"] = time.time()
check(f"an '@have' yes from before the drop doesn't count ({sorted(s.bot.party_carry())})", raft not in s.bot.party_carry())
s.bot.errands.known_have = {("revolution", raft): (True, time.time() + 1)}
check("…one after the kit does", raft in s.bot.party_carry())
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
