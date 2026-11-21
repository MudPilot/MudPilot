"""0.8.201: step-by-step guides with on-screen highlights (Help → Step-by-step guides). Builds the real main window
(in a throw-away data folder, never data\\boards), steps through every guide and checks every highlight target is
found on screen — and that a missing one fails soft (step text, no highlight, no error). Nothing may grab the app."""
import os, sys, tempfile, shutil
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
TMP = tempfile.mkdtemp(prefix="mp_guides_")
os.environ["MUDPILOT_DATA_DIR"] = TMP
os.environ.setdefault("MUDPILOT_NO_RECORD", "1")
import tkinter as tk
from mudpilot import config, app as A, guides as G
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def pump(secs=0.6):
    import time
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.02)

check("throw-away data folder", os.path.normcase(os.path.abspath(config.DATA_DIR)) == os.path.normcase(os.path.abspath(TMP)))
A.App.ask_board_first_run = lambda self: None          # (a fresh folder would ask its board in a modal box)
A.App.check_updates = lambda self, quiet=True: None
config.Settings.save = lambda self, *a, **k: None
root = tk.Tk()
app = A.App(root)
app.s.settings.save = lambda *a, **k: None
root.geometry("980x600+20+20")                          # the smallest the main window goes
root.update()

# ---- the data: every guide well formed
ids = [g["id"] for g in G.GUIDES]
check(f"guides ({ids})", {"first_run", "loop", "party", "items", "alerts"} <= set(ids) and len(ids) == len(set(ids)))
bad = [(g["id"], i) for g in G.GUIDES for i, s in enumerate(g["steps"])
       if not s.get("text") or set(s) - {"text", "open", "target"}]
check(f"every step has text and only known keys ({bad})", not bad)

# ---- menu entry + chooser
hm = None
menubar = root.nametowidget(root["menu"])
for i in range(menubar.index("end") + 1):
    if menubar.type(i) == "cascade" and menubar.entrycget(i, "label") == "Help":
        hm = root.nametowidget(menubar.entrycget(i, "menu"))
labels = [hm.entrycget(i, "label") for i in range(hm.index("end") + 1) if hm.type(i) == "command"] if hm else []
check("Help menu has Step-by-step guides", any("Step-by-step guides" in l for l in labels))
ch = app.open_guides(); root.update()
btns = [w for w in G._walk(ch) if w.winfo_class() == "TButton"]
check(f"chooser lists every guide ({len(btns)} buttons)", len(btns) == len(G.GUIDES) + 1)
check("chooser doesn't grab", root.grab_current() is None)
ch.destroy()

# ---- the F1 help book has a way in
from mudpilot import help_text
hw = tk.Toplevel(root); pane = help_text.make_pane(hw, app); pane.pack(); root.update()
check("help book has a Step-by-step guides button",
      any(w.winfo_class() == "TButton" and "guides" in str(w.cget("text")).lower() for w in G._walk(pane)))
hw.destroy()

# ---- step through every guide
for g in G.GUIDES:
    r = app.open_guides(g["id"])
    root.update()
    check(f"{g['id']}: panel open on step 1, Back disabled", r.open and r.i == 0 and r.btn_back.instate(["disabled"]))
    missing, unshown = [], []
    for i, step in enumerate(g["steps"]):
        pump()
        if step.get("target"):
            if r.target is None:
                missing.append(i + 1)
            elif G.target_rect(r.target) is None or not r.hl.shown:
                unshown.append(i + 1)
        txt = r.lbl_step.cget("text")
        if txt != f"Step {i + 1} of {len(g['steps'])}" or r.lbl_text.cget("text") != step["text"]:
            missing.append(f"text{i + 1}")
        if root.grab_current() is not None:
            missing.append(f"grab{i + 1}")
        if i < len(g["steps"]) - 1:
            r.next()
    check(f"{g['id']}: every target found ({len(g['steps'])} steps; not found: {missing})", not missing)
    check(f"{g['id']}: every found target highlighted on screen (not shown: {unshown})", not unshown)
    check(f"{g['id']}: last step says Finish", "Finish" in r.btn_next.cget("text"))
    r.back(); root.update()
    check(f"{g['id']}: Back goes back", r.i == len(g["steps"]) - 2)
    r.next(); r.next(); root.update()
    check(f"{g['id']}: Finish closes the panel and the highlight", not r.open and not r.hl.strips
          and G.GuideRunner.current is None)

# ---- the highlight sits round the widget
r = app.open_guides("first_run"); root.update()
r.i = len(r.steps) - 1; r.show(); root.update()
x, y, w, h = G.target_rect(r.target)
s = r.hl.strips[0]
check("highlight's top strip sits just above the Connect button",
      abs(s.winfo_rootx() - (x - G.PAD - G.BORDER)) <= 2 and abs(s.winfo_rooty() - (y - G.PAD - G.BORDER)) <= 2)
px, py = r.win.winfo_rootx(), r.win.winfo_rooty()
check("panel on screen", 0 <= px < root.winfo_screenwidth() and 0 <= py < root.winfo_screenheight())
check("panel doesn't cover the highlighted button",
      not (px < x + w and x < px + r.win.winfo_width() and py < y + h and y < py + r.win.winfo_height()))
r.win.focus_force(); root.update(); r.win.event_generate("<Escape>"); root.update()
check("Esc closes the guide", not r.open)

# ---- a new guide replaces an old one; Close works mid-way
r1 = app.open_guides("loop"); r2 = app.open_guides("items"); root.update()
check("starting a guide closes the one before", not r1.open and r2.open)
r2.close(); root.update()
check("Close mid-way", not r2.open)

# ---- fail soft: unknown widgets / windows / attrs
G.GUIDES.append({"id": "_t", "title": "test", "steps": [
    {"text": "no such attr", "target": {"attr": "no_such_widget"}},
    {"text": "no such text", "target": {"text": "zzz no such button zzz"}},
    {"text": "no such window", "target": {"text": "Close", "window": "No Such Window"}},
    {"text": "no such tab", "open": {"settings": "No such tab"}, "target": {"tab": "Nope", "window": "settings"}},
    {"text": "bad open", "open": {"game_data": "Nope"}, "target": {"attr": "quick", "key": "nope"}},
    {"text": "no target"}]})
try:
    r = app.open_guides("_t"); root.update()
    soft = []
    for i in range(len(r.steps)):
        root.update()
        has_t = bool(r.steps[i].get("target"))
        if r.target is not None or r.hl.shown or r.lbl_text.cget("text") != r.steps[i]["text"] \
                or (has_t and "couldn't point" not in r.lbl_note.cget("text")) or (not has_t and r.lbl_note.cget("text")):
            soft.append(i + 1)
        if i < len(r.steps) - 1:
            r.next()
    check(f"missing targets fail soft: text shown, no highlight, a note (bad: {soft})", not soft)
    r.close()
except Exception as e:
    check(f"missing targets fail soft (raised {e!r})", False)
G.GUIDES.pop()
check("find_target on junk returns None", G.find_target(app, {"weird": 1}) is None and G.find_target(app, None) is None)

# ---- (same window, the CP437 tick on Settings → Other re-fonts the MUD window; off by default)
import tkinter.font as tkfont
app.open_settings("Other"); pump(0.3)
check("Settings → Other has the BBS art (CP437) tick, off",
      any("BBS art (CP437)" in G._text_of(w) for w in G._walk(app.settings_win)) and not app.s.settings.cp437_terminal)
fam0 = tkfont.Font(font=app.term.cget("font")).actual("family")
app._var("cp437_terminal").set(True); pump(0.3)
fam1 = tkfont.Font(font=app.term.cget("font")).actual("family")
check(f"ticked: MUD window uses the CP437 font ({fam0} → {fam1})", app.s.settings.cp437_terminal
      and fam1.lower() == app._term_font()[0].lower())
app._var("cp437_terminal").set(False); pump(0.3)
check("unticked: back to the picked font", tkfont.Font(font=app.term.cget("font")).actual("family") == fam0)

root.update()
root.destroy()
shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
