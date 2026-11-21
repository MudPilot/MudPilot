r"""Miserable, 2026-11-15: set Stonecaps' stash room as '14\6534' and it never stashed the cash. Only '14/6534' was
read, so the loop had no stash room, and the dialog saved it without a word. Any usual separator is read now."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.extras import room_text
ok = True
for txt, want in [("14/6534", (14, 6534)), ("14\\6534", (14, 6534)), (" 14 / 6534 ", (14, 6534)),
                  ("14 6534", (14, 6534)), ("14,6534", (14, 6534)), ("14-6534", (14, 6534)),
                  ("", None), ("abc", None), ("14/", None), ("6534", None)]:
    got = room_text(txt)
    good = got == want
    ok &= good
    print(("PASS " if good else "FAIL ") + f"{txt!r} -> {got}")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
