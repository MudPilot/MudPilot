"""Dan, 2026-11-14:
1. Miserable PVE drained (death touch) at 75% and the game kept repeating it every round — 84, 91, 99% — because
   MudPilot never re-sends while the game repeats a spell. Once the drain is done it switches to the real spell.
2. Evolution relogged and quaked a single copsewight: his own pick for it (elemental fury) was overruled by MME's
   'Magical 4' rule. Your per-monster pick goes out unless the game said "no effect".
3. Spells seen hurting a monster are remembered across restarts (spell_memory.json in the board folder)."""
import os, sys, time, tempfile, json
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.spells import SpellBook
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

# 1. the drain is repeating, HP is back over the goal: switch to magma blast now
crab = dict(w.monster_names.get("rotting fachan"), name="scorpion crab", abils={}, num=990010, undead=0, attack_data={})
st.auto_combat = st.auto_spells = st.auto_cast = st.auto_nuke = True; st.aoe_safety = False
s.state.char_class = st.char_class = "Mage"; st.char_level = s.state.level = 55; s.state.spellcasting = 290
st.known_spell_rows = [["magm", "magma blast", 45, 40], ["dtch", "deathtouch", 16, 25]]
s.state.known_spells = st.known_spells = ["magm", "dtch"]
st.attack_spells = ["magm"]; st.rest_until_hp = 90; st.rest_below_hp = 60
s.state.max_hp, s.state.max_ma, s.state.ma = 920, 519, 450
b.x.may_cast_attack = lambda: True
dtch = sb.find("dtch")
b._last_spell = dtch["Number"]; b._cast_target = "scorpion crab"; b._cast_sent_at = time.time() - 6
b._last_hit_at = time.time() - 1; b._cast_eff = 70; s.state.in_combat = True
s.state.view = RoomView("Shore", {"N"}, [("scorpion crab", crab)], [], [], time.time())
s.state.hp = 845                                          # 92%: over 90 — drain's done
sent.clear(); b._cool.clear(); b._cast_block_until = 0
b.fight([("scorpion crab", crab)])
c = [x for x in sent if x.strip()]
check(f"drain repeating at 92%: switches to magma blast now ({c})", any(x.startswith("magm") for x in c))
b._last_spell = dtch["Number"]; b._cast_sent_at = time.time() - 6; b._last_hit_at = time.time() - 1
s.state.hp = 700                                          # 76%: keep draining
sent.clear(); b._cool.clear()
b.fight([("scorpion crab", crab)])
c = [x for x in sent if x.strip()]
check(f"…at 76% the drain keeps going ({c})", not any(x.startswith("magm") for x in c))

# 2. your pick for a monster beats MME's Magical rule
cw = dict(crab, name="copsewight", abils={28: 4}, num=990011)   # Magical 4: weapons only
st.char_class = s.state.char_class = "Druid"; st.char_level = s.state.level = 36
st.known_spell_rows = [["vine", "vine strike", 1, 2], ["fury", "elemental fury", 35, 25], ["quak", "earthquake", 28, 40]]
s.state.known_spells = st.known_spells = ["vine", "fury", "quak"]
st.attack_spells = ["fury"]; st.monster_spells = {"copsewight": {"spell": "fury", "variants": False}}
st.drain_heal = False
fury = next(sp for sp in s.known_spell_dicts() if sp.get("Short") == "fury")   # (the druid's elemental fury)
check("Magical 4 doesn't stop fury (it's a weapon rating)", not sb.useless(cw, fury))
s.state.party = {"Evolution": {}, "Revolution": {}}
s.state.hp = s.state.max_hp; s.state.in_combat = False; b._last_spell = None; b._cast_target = None
b._cast_sent_at = 0; b._attack_sent_at = 0; b._melee_on = False
s.state.view = RoomView("Copse", {"N"}, [("nasty copsewight", cw)], [], ["Revolution"], time.time())
sent.clear(); b._cool.clear()
b.fight([("nasty copsewight", cw)])
c = [x for x in sent if x.strip()]
check(f"…but your pick (fury) goes out, no quake on one monster ({c})",
      any(x.startswith("fury") for x in c) and not any(x.startswith("quak") for x in c))
sb.no_effect.add((990011, sb.find("fury")["Number"])); sb.no_effect.add((990011, fury["Number"]))
b._last_spell = None; b._cast_sent_at = 0; sent.clear(); b._cool.clear()
b.fight([("nasty copsewight", cw)])
c = [x for x in sent if x.strip()]
check(f"…once the game says 'no effect', it isn't ({c})", not any(x.startswith("fury") for x in c))

# 3. remembered across restarts
d = tempfile.mkdtemp()
p = os.path.join(d, "spell_memory.json")
b1 = SpellBook(w); b1.load_memory(p)
b1._last_cast = (990011, fury["Number"], time.time())
b1.feed_line("Your elemental fury strikes nasty copsewight for 61 damage!")
check("a first hit is written down", os.path.exists(p) and json.load(open(p))["hits"])
b2 = SpellBook(w); b2.load_memory(p)
cw2 = dict(cw); cw2["num"] = 990011
check("…and the next session knows fury hurts copsewights", not b2.useless(cw2, fury))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
