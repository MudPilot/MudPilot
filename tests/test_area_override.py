"""A per-monster single-target pick (Game Data → Monsters: drooling geist → dfir) doesn't stop the area spell in a
crowded room (3+), and the area spell isn't re-sent every round while the game repeats it."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mudpilot", "bundled", "Paradigm.db"))
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
st.auto_combat = st.auto_nuke = True
st.multi_spell, st.use_area_min, st.multi_min_mobs, st.aoe_safety = "esto", True, 3, False
st.monster_spells = {"drooling geist": {"spell": "dfir", "variants": False}}
b.x.may_cast_attack = lambda: True
rec = {"name": "drooling geist", "num": 1}
def mobs(n):
    return [(f"drooling geist", dict(rec)) for _ in range(n)]

sent.clear(); b._cool.pop("cast", None); g.in_combat = False
b.fight(mobs(3))
check(f"3 geists: the area spell, not the per-monster dfir ({sent})", any(c.startswith("esto") for c in sent))
sent.clear(); b._cool.pop("cast", None); g.in_combat = True
b.fight(mobs(3))
check(f"…not re-sent while the game repeats it ({sent})", not any(c.startswith("esto") for c in sent))
b.note_line("*Combat Off*")
sent.clear(); b._cool.pop("cast", None)
b.fight(mobs(3))
check(f"…sent again after combat drops ({sent})", any(c.startswith("esto") for c in sent))
b.note_line("*Combat Off*")
sent.clear(); b._cool.pop("cast", None); g.in_combat = False
b.fight(mobs(2))
check(f"2 geists: the per-monster pick ({sent})", any(c.startswith("dfir") for c in sent) and
      not any(c.startswith("esto") for c in sent))
# Dan, 2026-11-05: Area spell left blank ("best area spell I know") + Revolution's 'fire' for geists/nightshades =
# single-target in full rooms for days. Blank still means: crowded room → the best area spell
w = s.world
geist = next(m for m in w.monsters.values() if m.get("name") == "drooling geist")
st.multi_spell, st.auto_spells = "", True
st.monster_spells = {"drooling geist": {"spell": "fire", "variants": False}}
g.level, g.max_hp, g.hp, g.max_ma, g.ma = 60, 900, 900, 600, 600
st.char_level = 60
s.spell_candidates = lambda: [sp for sp in (s.spellbook.find("quak"), s.spellbook.find("fire")) if sp]
b.note_line("*Combat Off*")
sent.clear(); b._cool.pop("cast", None); g.in_combat = True; b._area_armed = 0; b._melee_on = False
b.fight([("drooling geist", dict(geist)) for _ in range(3)])
check(f"blank Area spell, 3 geists: the best area spell, not 'fire' ({sent})", any(c.startswith("quak") for c in sent))
sent.clear(); b._cool.pop("cast", None); g.in_combat = True; b._area_armed = 0; b._melee_on = False
b._last_spell, b._cast_sent_at, b._cast_area = None, 0, False
b.fight([("drooling geist", dict(geist))])
check(f"…one geist: your 'fire' ({sent})", any(c.startswith("fire") for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
