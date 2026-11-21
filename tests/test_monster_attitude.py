"""0.8.208 (Dan, 2026-11-19): set a monster Enemy / Neutral / Friend — Game Data → Monsters or '@enemy amazon shaman' —
to farm non-hostile amazon shamans (nature tap)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
st.remote_players = {"Miserable": ["settings"]}
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, w = s.bot, s.world
sham = next(m for m in w.monsters.values() if m["name"].lower() == "amazon shaman")
check(f"amazon shaman isn't hostile by default (align {sham.get('align')})", not b.hostile(sham))
r = s.remote.c_enemy("Miserable", "amazon shaman")
check(f"@enemy amazon shaman ({r})", st.monster_attitude.get("amazon shaman") == "enemy" and b.hostile(sham))
r = s.remote.c_neutral("Miserable", "amazon shaman")
check(f"@neutral: left alone ({r})", not b.hostile(sham))
r = s.remote.c_enemy("Miserable", "off amazon shaman")
check(f"@enemy off: back to default ({r})", "amazon shaman" not in st.monster_attitude and not b.hostile(sham))
replies = []
s.remote.reply = lambda ch, who, txt: replies.append(txt)
s.remote.handle("Miserable", "@enemy amazon shaman", "tell") if hasattr(s.remote, "handle") else None
print("dispatch:", replies, st.monster_attitude)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
