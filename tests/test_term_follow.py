"""0.8.225 (bug hunt #26): the MUD screen scrolls once per batch of lines (after_idle), not once per line — and still
follows the newest line, still stays put while you're scrolled back, and the back-scroll banner doesn't flicker."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
from mudpilot.app import App
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

root = tk.Tk()
root.geometry("500x200")
a = object.__new__(App)
a.root = root
a.s = SimpleNamespace(settings=SimpleNamespace(scrollback_lines=5000))
a.term = tk.Text(root, height=8, state="disabled")
a._term_sb = ttk.Scrollbar(root, command=lambda *x: (a._see_cancel(), a.term.yview(*x)))
a.term.configure(yscrollcommand=a._on_term_scroll)
a.term.mark_set("partial", "end-1c")
a.term.mark_gravity("partial", "left")
a.term.pack(fill="both", expand=True)
sees = []
real_see = a.term.see
a.term.see = lambda i: (sees.append(i), real_see(i))[1]
St = SimpleNamespace(tag="cx")
shows = []
real_show = a._scroll_show
a._scroll_show = lambda: (shows.append(1), real_show())[1]
root.update()
a.scroll_bottom(); root.update(); shows.clear(); sees.clear()     # (the empty widget's first layout)

for i in range(200):
    a.add_line([(f"line {i}", St)])
check("no scroll per line", len(sees) == 0)
check("following while a follow is queued", a._following())
root.update()
check("one scroll for the batch", sees == ["end"])
check("at the bottom after the batch", a.term.yview()[1] >= 0.9995)
check("no back-scroll banner while following", not shows and not getattr(a, "_scrolled_back", False))

# partial lines (the prompt) follow too
sees.clear()
a.set_partial([("[HP=100]:", St)])
root.update()
check("partial follows once", sees == ["end"] and a.term.yview()[1] >= 0.9995)

# scrolled back: new lines don't pull you down; the banner counts them
a.term.yview_moveto(0.2)
root.update()
check("scrolled back is noticed", getattr(a, "_scrolled_back", False) and not a._following())
sees.clear()
for i in range(5):
    a.add_line([(f"more {i}", St)])
root.update()
check("scrolled back: no scroll", sees == [] and a.term.yview()[1] < 0.9995)
check("backlog counted", a._backlog == 5)

# back at the bottom it follows again
a.scroll_bottom()
root.update()
sees.clear()
a.add_line([("again", St)])
root.update()
check("follows again after jumping down", sees == ["end"] and a.term.yview()[1] >= 0.9995)

# your own scroll while a follow is queued wins
a.add_line([("queued", St)])
a.scroll_page(-1)
root.update()
check("page-up cancels a queued follow", a.term.yview()[1] < 0.9995 and getattr(a, "_scrolled_back", False))

root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
