"""Dan, 2026-11-11: "nuke is aoe spells". Cast = single-target attack spells, Nuke = area ones. Evolution (druid, fist,
quak at 5+, 80 mana reserve) quaked lone nightshades: under the reserve the usual pick came up empty and the
'magical monster' fallback cast earthquake at any count and any mana. Unticked 'use area spells at least N' = never."""
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
st.auto_combat = True; st.auto_spells = True; st.spell_pick = "damage per mana"; st.aoe_safety = False
st.attack_spells = ["fist"]; st.multi_spell = "quak"; st.multi_min_mobs = 5; st.use_area_min = True
st.char_level = 30; s.state.level = 30; s.state.spellcasting = 174; st.spell_mana_reserve = 80
s.state.known_spells = st.known_spells = ["vine", "star", "strk", "pbol", "acid", "swar", "blaz", "plas", "quak", "fist"]
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
s.state.max_ma = 330
b.x.may_cast_attack = lambda: True
ns = w.monster_names["nightshade"]
check(f"nightshade is Magical 3 ({(ns.get('abils') or {}).get(28)}) and earthfist (level 30) can hurt it",
      not sb.useless(ns, sb.find("fist")))


def fight(n, ma, nuke=True, cast=True):
    st.auto_nuke, st.auto_combat = nuke, cast      # 0.8.185: single-target spells follow Combat (no Cast button)
    s.state.ma = ma
    sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0; b._area_armed = 0
    b.fight([("nightshade", ns)] * n)
    return [c.split()[0] for c in sent if c.split()]


for n in (1, 2, 4):
    c = fight(n, 330)
    check(f"{n} nightshade(s), full mana: no earthquake under 5 ({c})", "quak" not in c and "swar" not in c)
check(f"1 nightshade: earthfist ({fight(1, 330)})", "fist" in fight(1, 330))
c = fight(1, 90)
check(f"under the 80 reserve: no earthquake on one (was the 'magical' fallback) ({c})", "quak" not in c)
c = fight(1, 2)
check(f"2 mana: no earthquake ({c})", "quak" not in c)
c = fight(6, 330)
check(f"6 of them: earthquake ({c})", "quak" in c)
c = fight(6, 330, nuke=False)
check(f"Nuke off, 6 of them: no area spell, earthfist ({c})", "quak" not in c and "fist" in c)
c = fight(1, 330, cast=False)
check(f"Combat off, 1 of them: no single-target spell ({c})", not any(x in c for x in ("fist", "blaz", "plas", "acid")))
c = fight(1, 330, nuke=False, cast=False)
check(f"both off: melee only ({c})", not any(x in c for x in ("fist", "quak", "blaz", "plas", "swar")))
st.use_area_min = False
c = fight(6, 330)
check(f"'use area spells at least N' unticked: never an area spell ({c})", "quak" not in c and "swar" not in c)
st.use_area_min = True
st.auto_spells = False
c = fight(1, 330, nuke=False)
check(f"scripted fist, Nuke off: earthfist ({c})", "fist" in c)
st.attack_spells = ["quak", "fist"]
c = fight(1, 330)
check(f"scripted 'quak, fist' on one: the area one waits for 5 ({c})", "quak" not in c and "fist" in c)
# a death line comes before 'You gain … experience': the room list is stale from it, not from the exp line
b._kill_at = 0
b.note_line("The nightshade wails as it turns to dust.")
check("'turns to dust': the room list counts as stale", b._kill_at > 0)
b._kill_at = 0
b.note_line("You gain 2333 experience.")
check("'You gain … experience' still does", b._kill_at > 0)
b._kill_at = 0
b.note_line("The thin nightshade swipes at you with its claws!")
check("an ordinary fight line doesn't", b._kill_at == 0)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
