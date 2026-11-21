"""Game Data → Monsters: your spell for a monster beats the automatic pick and the learning."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session

st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
w = s.world
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
# a monster and two attack spells the character "knows"
mon = next(m for m in w.monsters.values() if (m.get("hp") or 0) > 50 and " " not in m["name"])
atk = [sp for sp in w.spells.values() if s._is_attack(sp) and int(sp.get("ManaCost") or 0) > 0][:40]
st.auto_spells = False; st.auto_nuke = True; st.auto_combat = True
st.attack_spells = [atk[0].get("Short")]
s.state.max_ma = s.state.ma = 5000
b = s.bot
b.x.may_cast_attack = lambda: True
# (one it doesn't resist by half: a spell it resists 50%+ is a real reason to use another — Dan, 2026-11-14)
other = next(sp for sp in atk if sp.get("Short") and sp.get("Short") != atk[0].get("Short")
             and b._real_reason_not(sp, mon) is None)
st.monster_spells = {mon["name"].lower(): {"spell": other["Short"], "variants": False}}
check("monster_spell lookup", b.monster_spell(mon) == other["Short"])
b.fight([(mon["name"], mon)])
check(f"casts your choice ({other['Short']}) — {sent}", any(c.split()[0] == other["Short"] for c in sent if c.split()))
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
st.monster_spells = {mon["name"].lower(): {"spell": "", "variants": False}}
b.fight([(mon["name"], mon)])
check(f"melee only → attacks, no spell ({sent})", sent and not any(c.split()[0] in (atk[0]["Short"], other["Short"]) for c in sent))
st.monster_spells = {}
check("nothing set → automatic", b.monster_spell(mon) is None)
from mudpilot.spelltune import family
st.monster_spells = {"drooling geist": {"spell": "dfir", "variants": True}}
check("variants: 'nasty drooling geist' uses the family's spell", b.monster_spell({"name": "nasty drooling geist"}) == "dfir")
st.monster_spells = {"drooling geist": {"spell": "dfir", "variants": False}}
check("not ticked: only the exact monster", b.monster_spell({"name": "nasty drooling geist"}) is None
      and b.monster_spell({"name": "drooling geist"}) == "dfir")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
