"""'st' shows "Mana: * 336/346" on Paradigm. The * kept MudPilot from reading it, so after Miserable PVE died and
came back naked (max 579 → 346) it still thought 579 and rested forever for 65% (Dan, 2026-11-03: "why is miserable
standing still")."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.gamestate import MANA_RE
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
m = MANA_RE.search("Mana: * 336/346   Spellcasting: 211    Traps:         157")
check(f"max mana read past the * ({m and m.groups()})", m and m.groups() == ("336", "346"))
m = MANA_RE.search("Mana:   310/529   Spellcasting: 276")
check(f"…and without it ({m and m.groups()})", m and m.groups() == ("310", "529"))
m = MANA_RE.search("Kai: * 40/90")
check("kai too", m and m.groups() == ("40", "90"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
