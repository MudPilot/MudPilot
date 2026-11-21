"""Dan, 2026-11-15: Buddy's holy avenger had no effect on the copsewights (magic 4), so MudPilot stopped meleeing them.
He switched to the ice crystal falchion, which can hurt them, and Buddy still never swung. The "no effect" note now
belongs to the weapon it was learned with, and a weapon swap clears it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st); s._no_log_file = True
b, g = s.bot, s.state
b.send = lambda c, late_ok=False: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

g.carrying = "holy avenger (Weapon Hand), platemail (Torso)"
b._melee_target = "large copsewight"
b.note_line("Your weapon has no effect against this monster!")
check(f"avenger can't hurt it ({b._melee_immune_now()})", "large copsewight" in b._melee_immune_now())
g.carrying = "ice crystal falchion (Weapon Hand), platemail (Torso)"
check("a different weapon in hand (pack re-read): melee it again", "large copsewight" not in b._melee_immune_now())
g.carrying = "holy avenger (Weapon Hand), platemail (Torso)"
check("back to the avenger: still not", "large copsewight" in b._melee_immune_now())
b.note_line("You have removed holy avenger.")
b.note_line("You are now holding ice crystal falchion.")
check("the game's swap lines clear it straight away", not b._melee_immune_now())
b._melee_immune = {"bog mummy"}           # the old shape (a set) still works
check("old set shape still read", "bog mummy" in b._melee_immune_now())
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
