"""Revolution, 2026-11-03: Evolution keeps casting swarm. His multi spell is chaos storm; the auto picker took swarm
whenever it rated a bit higher, the magical fallback and the can't-hurt-it engage cast took it too. With a multi
spell set, that's the only area spell any of them use."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
w, b, sb = s.world, s.bot, s.spellbook
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
csto = sb.find("csto")
check(f"chaos storm is csto ({csto and csto['Name']})", csto is not None)
st.auto_spells = True; st.auto_nuke = True; st.auto_combat = True; st.spell_pick = "damage"
st.attack_spells = ["blaz"]; st.multi_spell = "csto"; st.multi_min_mobs = 5; st.use_area_min = False
st.char_level = 20; s.state.level = 20
s.state.known_spells = st.known_spells = ['vine', 'star', 'mend', 'aler', 'rcol', 'chao', 'sens', 'rfir', 'char',
    'anti', 'skin', 'camo', 'strk', 'rlit', 'pbol', 'rhel', 'swar', 'burn', 'acid', 'enta', 'rain', 'csto', 'rgen',
    'petr', 'free', 'pclo', 'rott', 'ston', 'blaz', 'rwat']           # Evolution's, 2026-11-03
st.spell_mana_reserve = 80; s.state.spellcasting = 137
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
s.state.max_ma = 600
b.x.may_cast_attack = lambda: True
names = ["green dragon serpent", "white dragon serpent", "red dragon serpent", "prismatic dragon", "nightshade",
         "wraithlord", "drooling geist", "frost giant", "ogre-mage", "crimson mist"]
names += ["behemoth"]
for k, ma in [(k, ma) for k in (1, 2, 3) for ma in (600, 150, 60)]:
    s.state.ma = ma
    for nm in names:
        rec = w.monster_names.get(nm)
        if not rec:
            continue
        sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
        b.fight([(nm, rec)] * k)
        casts = [c.split()[0] for c in sent if c.split()]
        if "swar" in casts:
            check(f"no swarm: {k} x {nm}, mana {ma} ({casts})", False)
check("no swarm at any of them", ok)
st.multi_spell = ""
st.use_area_min, st.multi_min_mobs = True, 3     # (unticked = no area spells at all, 0.8.173)
st.aoe_safety = False           # (no room seen in this test: the AoE safety would hold every area spell)
s.state.ma = 600                # (60 is under his 80 reserve: that only cast through the false "magical" path)
picked = set()
for nm in names:
    rec = w.monster_names.get(nm)
    if rec:
        sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
        b.fight([(nm, rec)] * 3)
        picked |= {c.split()[0] for c in sent if c.split()}
check(f"no multi spell set: any area spell is fair game again ({sorted(picked)})", picked & {"swar", "csto"})
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
