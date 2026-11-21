"""Evolution, 2026-11-15 (report, 0.8.192): copsewight set to elemental fury in Game Data → Monsters, fury his attack
spell, and MudPilot cast vine strike at every copsewight saying nothing he had could hurt it. MME has copsewight as
'Magical 4' (only single-target spells of level 40+), so elemental fury (35) was ruled out — yet his vine strike, level
1, was hitting it for 13 on screen. Damage the game has shown now beats the magical rule: once a spell of level L has
hurt it, any single-target spell of level L or more can too."""
import os, sys, time
os.environ["MUDPILOT_NO_RECORD"] = "1"
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.char_class = "Druid"
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


cw = w.monster_names["copsewight"]
drag = w.monster_names["prismatic dragon"]
fury, vine = w.spells[716], w.spells[25]
check("copsewight is Magical 4 in the data", int(cw["abils"].get(28) or 0) == 4)
check("Magical is about weapons: fury (35) can hurt a copsewight (no spell immunity) from the start (2026-11-14)", sb.can_hit(cw, fury))
sb.observed[(cw["num"], vine["Number"])] = [13, 12]
check("vine strike (level 1) seen hitting it for 13 → elemental fury can hurt it", sb.can_hit(cw, fury)
      and not sb.useless(cw, fury))
check("…and vine itself", sb.can_hit(cw, vine))
check("the dragon (nothing seen) still follows the rule", not sb.can_hit(drag, vine))
sb.observed[(cw["num"], vine["Number"])] = [0, 0, 0]
check("zeros don't change that", sb.can_hit(cw, fury))
sb.observed[(drag["num"], w.spells[290]["Number"])] = [30]
check("blaze (20) hitting the dragon doesn't unlock vine (1)", not sb.can_hit(drag, vine))
sb.no_effect.add((cw["num"], fury["Number"]))
sb.observed[(cw["num"], vine["Number"])] = [13]
check("a 'no effect' from the game still rules it out", sb.useless(cw, fury))
sb.no_effect.clear()
# Evolution's set-up: auto spells, fury his attack spell, copsewight → fury, in a party
st.auto_spells = True; st.auto_nuke = True; st.auto_combat = True
st.attack_spells = ["fury"]; st.multi_spell = ""
st.monster_spells = {"copsewight": {"spell": "fury", "variants": False}}
st.char_level = 36; s.state.level = 36
st.known_spells = s.state.known_spells = ["vine", "fury"]
s.state.max_ma = s.state.ma = 320
b.x.may_cast_attack = lambda: True
s.state.party = {"Evolution": {}, "Buddy": {}, "Revolution": {}}
from mudpilot.gamestate import RoomView
s.state.view = RoomView("Hidden Copse", set(), [("nasty copsewight", cw)], [], ["Buddy", "Revolution"], time.time())
_find = sb.find      # (in the game, his spell list names it: 'fury' is the druid's elemental fury, not divine fury)
sb.find = lambda n: fury if isinstance(n, str) and n.strip().lower() == "fury" else _find(n)
f = sb.find("fury")
check(f"'fury' is elemental fury here ({f and f['Name']})", f is not None and f["Number"] == 716)
sent.clear(); b._last_spell = None; b._cool.clear(); b._cast_sent_at = 0
b.fight([("nasty copsewight", cw)])
casts = [c.split()[0] for c in sent if c.split()]
check(f"fights the copsewight with fury, not vine ({sent})", "fury" in casts and "vine" not in casts)
print("ALL PASS" if ok else "SOME FAILED")
