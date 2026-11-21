"""0.8.200: the in-app help book — topics, the live @command list, and search."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from mudpilot import help_text
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
tops = help_text.all_topics()
titles = [t for t, _ in tops]
check(f"topics ({len(tops)})", len(tops) >= 12 and "Remote @commands" in titles)
rc = dict(tops)["Remote @commands"]
check("the @command topic comes from the live list", "@summon" in rc and "@collect" in rc)
root = tk.Tk(); root.withdraw()
f = help_text.make_pane(root); f.pack(); root.update()
ent = [w for w in f.winfo_children()[0].winfo_children() if w.winfo_class() == "TEntry"][0]
lb = [w for w in f.winfo_children()[1].winfo_children() if w.winfo_class() == "Listbox"][0]
check(f"all topics listed ({lb.size()})", lb.size() == len(tops))
ent.insert(0, "stash"); root.update()
found = [lb.get(i) for i in range(lb.size())]
check(f"search 'stash' narrows it ({found})", 0 < len(found) < len(tops) and any("stash" in x.lower() for x in found))
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
