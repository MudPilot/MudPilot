"""0.8.33: mana throttle never drops to a toy spell, resync goes to the nearest step, no spell change mid-fight."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.spells import auto_pick, is_attack_spell, spell_kind
from mudpilot.megamud_files import MPath
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
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
mage = next(k for k, v in w.classes.items() if v.get("Name") == "Mage")
from mudpilot.spells import class_spells
sps = class_spells(w, mage, 47)
mon = next(m for m in w.monsters.values() if "nightshade" in m["name"])
dmg = auto_pick(s.spellbook, sps, [mon], 47, 10 ** 6, 0.5, 225, 0, "damage")
mana = auto_pick(s.spellbook, sps, [mon], 47, 10 ** 6, 0.5, 225, 0, "mana")
check(f"saving mana picks {mana[0]['Name']} ({mana[1]}/round) vs hardest {dmg[0]['Name']} ({dmg[1]}) — at least half",
      mana[1] >= dmg[1] * 0.5)
check("…not magic missile", "magic missile" not in mana[0]["Name"].lower())
# resync goes to the nearest step
b = s.bot
class Step:
    def __init__(self, room): self.room, self.dest, self.hash, self.move, self.pre = room, None, "", "n", []
class P:
    title = "t"; resolved = True
    steps = [Step((1, i)) for i in range(40)]
steps = P.steps
steps[11].room = steps[35].room = (9, 9)
b.path = P()
s.state.candidates = [(9, 9)]
check(f"same room at step 12 and 36, we're at 36 → resync to 36 ({b._index_for_current(36) + 1})", b._index_for_current(36) == 35)
# no spell change mid-fight
sp_a = next(sp for sp in sps if "magma" in sp["Name"].lower())
sp_b = next(sp for sp in sps if "dragonfire" in sp["Name"].lower())
b._last_spell, b._cast_target, b._cast_sent_at = sp_a["Number"], mon["name"], time.time() - 3
s.state.in_combat = True; s.state.max_ma = s.state.ma = 500
sent.clear()
b._cast_pick(sp_b, 300, 1.0, "", (mon["name"], mon), mon, "night", 1)
check(f"mid-fight, same target: keeps the running spell ({sent})", not sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
