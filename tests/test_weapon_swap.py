"""Dan, 2026-11-16: Buddy's holy avenger (magic 3) can't hurt the copsewights (magic 4) in Hidden Copse. If he carries a
weapon that can (ice crystal falchion, magic 4), wield it and attack again — then his own weapon once the fight's over."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
b.send = lambda c, *a, **k: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

cw = next(m for m in s.world.monsters.values() if m.get("name") == "copsewight")
orc = next(m for m in s.world.monsters.values() if not (m.get("abils") or {}).get(28))
g.carrying = "holy avenger (Weapon Hand), platemail (Torso), ice crystal falchion, 40 gold crowns"
g.view = RoomView("Hidden Copse", {"N"}, [("copsewight", cw)], [], [], 0)
check("MME: the copsewight needs more than the avenger", b._needs_better_weapon(cw))
sent.clear()
check("swaps before swinging", b._swap_weapon_for(cw, "copsewight", "copsewight") and "eq ice crystal falchion" in sent)
check("…and re-reads the pack", "i" in sent)
b.note_line("You are now holding ice crystal falchion.")
check(f"falchion in hand now ({b._wielded_now()})", b._wielded_now() == "ice crystal falchion")
check("no more swapping needed", not b._needs_better_weapon(cw))

# the game says no effect even so — never swap back and forth
g.carrying = "ice crystal falchion (Weapon Hand), platemail (Torso), holy avenger"
b._melee_target = "copsewight"
b.note_line("Your weapon has no effect against this monster!")
b._cool.pop("weapon_swap", None)
sent.clear()
check(f"no better one left: no swap ({sent})", not b._swap_weapon_for(cw, "copsewight") and not sent)

# fight over, room clear: own weapon back
b._wpn_failed = set()
b._wpn_swap_back = "holy avenger"
g.in_combat = True
b._weapon_swap_back(); check("not during the fight", "eq holy avenger" not in sent)
g.in_combat = False
b._cool.pop("weapon_back", None)
b._weapon_swap_back(); check("copsewight still here: keep the falchion", "eq holy avenger" not in sent)
g.view = RoomView("Hidden Copse", {"N"}, [], [], [], 0)
b._cool.pop("weapon_back", None)
b._weapon_swap_back(); check(f"room clear: avenger back ({sent})", "eq holy avenger" in sent and not b._wpn_swap_back)

# an ordinary monster: never swaps
g.carrying = "holy avenger (Weapon Hand), ice crystal falchion"
b._inv_stale = False
check("ordinary monster: no swap", not b._needs_better_weapon(orc))
# the game refuses the weapon: not tried on that monster again
b._cool.pop("weapon_swap", None); sent.clear()
b._swap_weapon_for(cw, "copsewight")
b.note_line("You may not ready a 2-handed weapon with your shield worn!")
b._cool.pop("weapon_swap", None); sent.clear()
check(f"refused once: not again ({sent})", not b._swap_weapon_for(cw, "copsewight") and not sent)
# switched off
st.auto_weapon_swap = False; b._wpn_failed = set(); b._cool.pop("weapon_swap", None)
check("setting off: no swap", not b._swap_weapon_for(cw, "copsewight"))
# bare hands (martial arts): nothing to swap
st.auto_weapon_swap = True; g.carrying = "ice crystal falchion"; b._held = None
check("bare hands: no swap", not b._swap_weapon_for(cw, "copsewight"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
