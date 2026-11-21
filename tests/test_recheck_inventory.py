"""Dan, 2026-11-05: "if he asks other characters for an item he needs to get somewhere he just needs to check his
inventory first". Buddy picked up the glowing red amulet and handed it to Evolution; Evolution's Go to the Massive
Chest (7/1282) then asked the party for one and stopped — its pack list was from before the hand-over."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.char_level = 25
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
g, b = s.state, s.bot
g.level = 25
AMU = s.world.item_names["glowing red amulet"]["num"]
_needs = b.path_needs
b.path_needs = lambda mp: [(AMU, False)] if "7/1282" in mp.title else _needs(mp)   # (a must-have, as on Evolution's board)
g.candidates = [(7, 1285)]
g.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
g.carrying = "black plate gauntlets, black plate boots"; g.keys = "dark temple key"
g.inv_seq += 1; g.inv_at = time.time() - 120          # read two minutes ago, before Buddy handed it over
b.goto((7, 1282))
check(f"needs the amulet, pack list old: reads it again first ({sent})", sent == ["i"])
check("…nobody asked yet", not any("@have" in c for c in sent))
g.carrying += ", glowing red amulet"; g.inv_seq += 1; g.inv_at = time.time()
b.tick()
check(f"it's in the pack: walks ({b.path and b.path.title}; {sent})",
      b.walking and b.path and "7/1282" in b.path.title and not any("@have" in c for c in sent))
# really missing: the re-read doesn't find it → on to the party, once (no second re-read)
b.stop("Stopped by you"); sent.clear()
g.carrying = "black plate gauntlets"; g.inv_seq += 1; g.inv_at = time.time() - 120
b.goto((7, 1282))
g.inv_seq += 1; g.inv_at = time.time()
b.tick()
for _ in range(3):
    b.tick()
check(f"really not there: asks the party ({sent})", sent[0] == "i" and sent.count("i") == 1
      and any("@have glowing red amulet" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
