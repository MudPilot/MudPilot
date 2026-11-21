"""Leading, 'wait if a member is below HP %' (Settings → Party): 70% by default, and walk on as soon as they're back
over it — not stand till 90%, the healer's minor-heal line. @wait always holds. Old saves on 80/90 move to 70/0."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

check("default: wait below 70%, until back over that line", config.Settings().party_wait_pct == 70 and
      config.Settings().party_wait_until_pct == 0)

st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.party_wait_mins, st.party_check_secs = 2, 5
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
x, g = s.bot.x, s.state
x._own_party = True
def party(hp, ma=90):
    now = time.time()
    g.party = {"Revolution": {"hp": 100, "ma": 100, "t": now}, "Buddy": {"hp": hp, "ma": ma, "t": now}}

party(85)
check("Buddy at 85% (below the 90% minor heal): keep walking, the healer heals on the move", not x.wait_for_party())
party(65)
check("below 70%: the leader waits", x.wait_for_party())
party(72)
check("…and walks on once they're back over 70% (not at 90)", not x.wait_for_party())
s.remote.handle("telepath", "Buddy", "@wait")
check("@wait holds no matter what", s.remote.holding() == "Buddy")

# old save: 80 / 90 (the old defaults) move to 70 / 0; your own numbers stay
config.PROFILES_DIR = tempfile.mkdtemp()
for name, pct, until, want in (("Old", 80, 90, (70, 0)), ("Mine", 75, 85, (75, 85))):
    json.dump({"settings_version": 16, "party_wait_pct": pct, "party_wait_until_pct": until},
              open(config.Settings.profile_path(name), "w"))
    got = config.Settings.load(name)
    check(f"{name} save {pct}/{until} -> {want}", (got.party_wait_pct, got.party_wait_until_pct) == want)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
