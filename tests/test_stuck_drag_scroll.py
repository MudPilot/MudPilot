"""0.8.227.7 (Dan: Miserable PVE's MUD window kept scrolling up by itself; clicking the yellow back-scroll bar didn't
stop it, clicking the command line and pressing Enter did). Tk's drag-select auto-scroll was left running (a click
that closed the Goto popup lost its release): it scrolls up every 50 ms and pulled the bar's jump-down straight back.
The bar, Ctrl+End, Enter and your own scrolling cancel it now."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
import tkinter as tk
from mudpilot import app as appmod
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

root = tk.Tk()
root.geometry("600x300+50+50")
term = tk.Text(root, height=10)
term.pack(fill="both", expand=True)
entry = tk.Entry(root)
entry.pack(fill="x")
term.insert("end", "".join(f"line {i}\n" for i in range(2000)))
root.update()

class Fake:
    pass
for n in ("_bar_click", "scroll_bottom", "_scroll_done", "_stop_drag_scan", "_see_cancel"):
    if hasattr(appmod.App, n):
        setattr(Fake, n, getattr(appmod.App, n))
f = Fake(); f.root, f.term, f.entry = root, term, entry

def stuck_scan():
    term.see("end"); root.update()
    root.tk.call("set", "::tk::Priv(x)", 10)
    root.tk.call("set", "::tk::Priv(y)", -40)        # 'dragging' above the top of the screen
    root.tk.call("tk::TextAutoScan", str(term))

def settle(ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        root.update(); time.sleep(0.01)

stuck_scan(); settle(300)
check(f"the stuck scan scrolls the screen up ({term.yview()[1]:.3f})", term.yview()[1] < 0.999)
# the old bar: jump down only — the scan pulls it back up
term.see("end"); settle(400)
check(f"old jump-down alone: pulled back up ({term.yview()[1]:.3f})", term.yview()[1] < 0.999)
check("the bar click has the fix", hasattr(Fake, "_stop_drag_scan"))
f._bar_click(); settle(500)
check(f"bar click: stays at the bottom ({term.yview()[1]:.4f})", term.yview()[1] >= 0.999)
stuck_scan(); settle(200)
f.scroll_bottom(); settle(500)
check(f"Ctrl+End / Enter (scroll_bottom): stays at the bottom ({term.yview()[1]:.4f})", term.yview()[1] >= 0.999)
# Dan: "scrolling down it was fighting me and would continue scrolling up soon as i stopped": one wheel turn
# (bound to _see_cancel) ends it
stuck_scan(); settle(200)
f._see_cancel(); term.yview_scroll(100, "units"); term.see("end"); settle(500)
check(f"mouse wheel down: stays down once you stop ({term.yview()[1]:.4f})", term.yview()[1] >= 0.999)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
