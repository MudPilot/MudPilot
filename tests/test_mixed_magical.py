"""Dan, 2026-11-14 (Albion): "casting vine strike and melee as a mage — it's getting ugly quick".
1. A large nightmare (Magical 4) and a small gorehoof (Magical 5) walked in on Miserable. Magma blast (level 45) hurts
   the nightmare, but spells were thrown out when useless against ANY monster here, so magma blast went, the storm was
   held (2 monsters, area needs 3) and the mage swung 'a nightmare'. A single-target spell is judged on its target.
2. Nothing can hurt it by MME's Magical rule: the engage-anyway spell was the cheapest — vine strike, every time.
   Now the strongest affordable one, the one most likely to land (and once it lands it's counted from then on)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
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

base = w.monster_names.get("rotting fachan")
check("a monster to copy", base is not None)
# (spell immunity, MME SpellImmu 139, is what limits spells — Magical is for weapons; the gorehoof here is made
#  immune below level 46 so magma blast (45) can't touch it)
nightmare = dict(base, name="nightmare", abils={28: 4, 139: 18}, num=990001)
gorehoof = dict(base, name="gorehoof", abils={28: 5, 139: 46}, num=990002)
mage = [x for x in ("mmis", "lbol", "magm", "esto") if sb.find(x)]
check(f"mage spells found ({mage})", "magm" in mage and "esto" in mage)
st.auto_combat = st.auto_spells = st.auto_cast = st.auto_nuke = True
st.aoe_safety = False; st.multi_spell = "esto"; st.multi_min_mobs = 3; st.use_area_min = True
st.attack_spells = ["magm"]; st.char_level = 46; s.state.level = 46; s.state.spellcasting = 223
s.state.char_class = st.char_class = "Mage"
s.state.known_spells = st.known_spells = list(mage)
s.state.max_ma = s.state.ma = 496; st.spell_fallback_melee = True
s.state.party = {"Miserable": {}, "Revolution": {}}
b.x.may_cast_attack = lambda: True


def fight(mobs):
    sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0; b._area_armed = 0
    b._attack_sent_at = 0; b._melee_on = False; s.state.in_combat = False
    s.state.view = RoomView("Maes Aur, Trail", {"E"}, mobs, [], [], time.time())
    b.fight(mobs)
    return [c for c in sent if c.strip()]


check("magma blast can hurt the nightmare, not the gorehoof",
      not sb.useless(nightmare, sb.find("magm")) and sb.useless(gorehoof, sb.find("magm")))
c = fight([("large nightmare", nightmare), ("small gorehoof", gorehoof)])
check(f"nightmare + gorehoof: magma blast at the nightmare, no melee ({c})",
      any(x.startswith("magm") for x in c) and not any(x.startswith("a ") for x in c))
c = fight([("small gorehoof", gorehoof), ("large nightmare", nightmare)])
check(f"gorehoof first: a spell that hurts it (the storm), no melee ({c})",
      c and not any(x.startswith("a ") for x in c))
c = fight([("large nightmare", nightmare)])
check(f"nightmare alone: magma blast ({c})", any(x.startswith("magm") for x in c))

# 2. the engage-anyway pick: the strongest affordable spell, not the cheapest
real = sb.useless
sb.useless = lambda mon, sp: True                     # nothing can hurt it (as far as the data says)
got = b._engage_anyway([("large nightmare", nightmare)], nightmare)
lvl = lambda sp: int(sp.get("ReqLevel") or 0)
singles = [sb.find(x) for x in mage if sb.find(x)]
check(f"engage anyway: not the cheapest level-1 spell ({got and got[0].get('Short')})",
      got and got[0].get("Short") != "mmis")
sb.useless = real

# 3. level 50+: no spell under level 20, ever, and no melee unless every spell is useless against it
st.char_level = s.state.level = 52
st.attack_spells = ["mmis"]; st.auto_spells = False
s.state.ma = 496
c = fight([("large nightmare", dict(base, name="plain thing", abils={}, num=990003))])
check(f"level 52, attack list = magic missile: no magic missile, no melee ({c})",
      not any(x.startswith(("mmis", "a ")) for x in c))
check("magic missile is too low at 52", s.spell_too_low(sb.find("mmis")) and not s.spell_too_low(sb.find("magm")))
st.char_level = s.state.level = 40
check("…not at 40", not s.spell_too_low(sb.find("mmis")))
st.char_level = s.state.level = 52; st.auto_spells = True; st.attack_spells = ["magm"]
st.known_spell_rows = [["mmis", "magic missile", 1, 1], ["lbol", "lightning bolt", 8, 3], ["magm", "magma blast", 45, 40],
                       ["esto", "eldritch storm", 40, 70]]
s.state.ma = 0
c = fight([("large nightmare", nightmare)])
check(f"level 52 mage out of mana: no melee — waits ({c})", not any(x.startswith("a ") for x in c))
immune = dict(base, name="immune thing", abils={139: 999}, num=990004)
real = sb.useless
sb.useless = lambda mon, sp: mon.get("num") == 990004 or real(mon, sp)
c = fight([("immune thing", immune)])
check(f"immune to all its magic, in a party: still joins the fight (engage spell) ({c})", bool(c))
s.state.party = {}
c = fight([("immune thing", immune)])
check(f"immune to all its magic, alone: melee is allowed ({c})", any(x.startswith("a ") for x in c))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
