"""0.8.184 (Dan, 2026-11-12): "miserable was trying to melee hanging tree… A mage should never use melee unless they cant
hit." No spell rated over the minimum (a boss, area spells blocked) and the fallback swung 'a tree'. A mage casts the
best spell that hurts it instead; it only swings when no spell can hurt it or none is affordable. Other classes keep
the melee fallback setting."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
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
tree = w.monster_names.get("hanging tree")
check("the hanging tree is in the bundled map", tree is not None)
mage = [x for x in ("mmis", "lbol", "chao", "come", "magm", "chai") if sb.find(x)]
check(f"mage attack spells found ({mage})", len(mage) >= 2)
st.auto_combat = True; st.auto_spells = True; st.auto_cast = True; st.auto_nuke = True; st.aoe_safety = False
st.attack_spells = mage; st.multi_spell = ""; st.char_level = 55; s.state.level = 55; s.state.spellcasting = 291
s.state.known_spells = st.known_spells = list(mage)
st.spell_mana_reserve = 0; s.state.max_ma = 514
st.spell_fallback_melee = True
st.spell_min_pct = 100000                   # nothing rates over it: the case that swung at the tree
b.x.may_cast_attack = lambda: True

def fight(cls, ma):
    s.state.char_class = st.char_class = cls
    s.state.ma = ma
    sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0; b._area_armed = 0
    b._attack_sent_at = 0; b._melee_on = False; s.state.in_combat = False
    b.fight([("hanging tree", tree)])
    return [c for c in sent if c.strip()]

c = fight("Mage", 514)
check(f"mage, no spell over the minimum: casts anyway, no melee ({c})",
      any(x.split()[0] in mage for x in c) and not any(x.startswith("a ") for x in c))
# the tree only takes level-50+ magic: magma blast (45) can't hurt it, comet (50) can, even resisted
check(f"…comet, the one spell that can hurt the tree ({c})", any(x.startswith("come") for x in c))
sb.no_effect.add((tree["num"], sb.find("come")["Number"]))   # the game said comet had no effect: the next that hurts
c = fight("Mage", 514)
check(f"immune to comet: falls back to another spell that hurts, not melee ({c})",
      c and not any(x.startswith(("a ", "come")) for x in c) and any(x.split()[0] in mage for x in c))
sb.no_effect.discard((tree["num"], sb.find("come")["Number"]))
st.auto_spells = False
c = fight("Mage", 514)
check(f"auto spells off (just the attack list): comet too, not magma blast that can't hurt it, no melee ({c})",
      any(x.startswith("come") for x in c) and not any(x.startswith(("a ", "magm")) for x in c))
st.auto_spells = True
c = fight("Mage", 0)
check(f"mage with no mana for any spell: melee is all that's left ({c})", not any(x.split()[0] in mage for x in c))
st.attack_spells = []; st.auto_spells = False     # (a warrior with no spells set: your attack spell would go out)
c = fight("Warrior", 514)
check(f"a warrior with melee fallback on still swings ({c})", any(x.startswith("a ") for x in c))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
