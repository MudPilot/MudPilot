"""Dan, 2026-11-16 (0.8.203 rollout): Evolution leads the PVE party in the game and closed first; Buddy's party broke a
second before his own restart, so he came back thinking he led, invited everyone, and Evolution — regrouping, loop
waiting — joined Buddy's party, which had no loop. The party left Revolution behind.
- a follower whose leader logged off just before its restart still rejoins that leader;
- a leader regrouping after a restart with its loop doesn't join someone it's inviting back — it invites them;
- status.json says who each character follows, so rollout.py closes followers first, the in-game leader last."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, control
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

tmp = tempfile.mkdtemp()

# --- Buddy: following Evolution, who logs off first; the party breaks; then Buddy's own restart
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st); s._no_log_file = True
box = control.ControlBox(s, folder=os.path.join(tmp, "buddy"))
x = s.bot.x
x.note_line("You are now following Evolution.")
check(f"following Evolution ({box._leader()})", box._leader() == "Evolution")
x.note_line("Your party has been disbanded.")
check(f"party broke under him a second ago: still Evolution ({box._leader()})", box._leader() == "Evolution")
x._followed_t = time.time() - 600
check("…but not from ten minutes ago", box._leader() is None)
x._followed_t = time.time()
box.write_status()
import json
d = json.load(open(os.path.join(tmp, "buddy", "status.json"), encoding="utf-8"))
check(f"status.json says who he follows ({d.get('follows')})", d.get("follows") == "Evolution")

# --- Evolution: back from its restart, leading, regrouping with its loop; Buddy invites it
st2 = config.Settings(); st2.save = lambda: None; st2.my_name = "Evolution"
st2.remote_players = {"Buddy": {"party": True}}
s2 = Session(st2); s2._no_log_file = True
sent = []
s2.send = lambda c, from_bot=False, **k: sent.append(c)
b2 = s2.bot
b2.loop, b2.path, b2.walking = True, type("P", (), {"title": "Hidden Copse - 13 2995", "steps": [], "is_loop": True})(), False
s2._regroup = {"names": ["Revolution", "Buddy"], "t": time.time(), "asked": 0, "until": time.time() + 300}
r = s2.remote.keep_my_loop("Buddy")
check(f"regrouping with its loop: invites Buddy instead of joining ({r}, {sent})", r and "invite Buddy" in sent
      and not any(c.startswith("join") for c in sent))
sent.clear()
r = s2.remote.keep_my_loop("Buddy")
check(f"Buddy invites again: still doesn't give way ({r}, {sent})", r and not any(c.startswith("join") for c in sent))
s2._regroup = None
s2.remote._invited_back = {}
check("no regroup, not walking: an invite is joined as before", not s2.remote.keep_my_loop("Buddy"))

# --- rollout: followers first, the in-game leader last
import rollout
fake = {"--evo": {"follows": None}, "--buddy": {"follows": "Evolution"}}
rollout.status = lambda f: fake.get(f, {})
live = ["--evo", "--buddy"]
live.sort(key=lambda f: 0 if rollout.status(f).get("follows") else 1)
check(f"rollout closes Buddy before Evolution ({live})", live == ["--buddy", "--evo"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
