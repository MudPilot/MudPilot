"""Dan, 2026-11-04: '@loop peruse books' — Golden Spire Secret Library: peruse the blue book (always works), then
the red book (an int/wis roll, ~10 s each go) until the pharaoh story comes, then say in the room that the books
have been properly perused, so whoever sent an AFK character off knows it's done."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot import peruse
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, r, g = s.bot, s.remote, s.state
sent, gone = [], []
b.send = lambda c, **k: sent.append(c)
b.log = lambda m, *a, **k: None
b.goto = lambda t, *a, **k: gone.append(t) or True
p = b.peruse
g.candidates = [(12, 120)]
out = r.c_loop("Dan", "peruse books")
check(f"@loop peruse books walks to the Library ({out})", gone == [(12, 2248)] and p.active)
route = b.plan_route((12, 120), (12, 2248), None)
check("there's a way in (through the stand-opened door)", route and route[-1].to == (12, 2248))
g.candidates = [(12, 2247)]
p.tick()
check("one room out (the Library) isn't there yet", sent == [])
g.candidates = [(12, 2248)]
g.in_combat = g.resting = False; g.pending = None
p.tick()
check(f"blue book first ({sent})", sent == ["peruse blue book"])
p.tick()
check("not straight on", sent == ["peruse blue book"])
p.active["sent"] -= 4
p.tick()
check(f"then the red book ({sent})", sent[-1] == "peruse red book" and p.active["tries"] == 1)
p.active["sent"] -= 5
p.tick()
check("waits out the red book's delay", len(sent) == 2)
p.active["sent"] -= 10
p.tick()
check("…and tries again", sent[-1] == "peruse red book" and p.active["tries"] == 2)
g.in_combat = True
p.active["sent"] -= 20
p.tick()
check("not while fighting", len(sent) == 3)
g.in_combat = False
b.note_line("You failed to understand the book.")
check("anything else isn't the story", p.active)
p.active["sent"] = time.time()
b.note_line("Despite countless minutes of painstaking translation, you find nothing that ")
p.tick()
check(f"a failed roll: straight back at it ({sent[-1]}, {p.active['tries']})", p.active["tries"] == 3)
b.note_line(" May God have mercy on their souls.\"")
check(f"the story: says so in the room and stops ({sent[-1]})", sent[-1] == f".{peruse.DONE_SAY}" and not p.active)
# the book makes no sense (flag not 6): gives up after 3
r.c_loop("Dan", "peruse books"); p.tick()
for _ in range(3):
    b.note_line("You flip through the book, but can make no sense of the writing.")
check("no sense 3 times running: stops", not p.active)
# already done / @stop
st.known_abils = {"134": 7}
check(f"flag already 7 ({r.c_loop('Dan', 'peruse')})", "already" in r.c_loop("Dan", "peruse") and not p.active)
st.known_abils = {"134": 6}
r.c_loop("Dan", "peruse books")
b.walking = False
check(f"@stop ends it ({r.c_stop('Dan', '')})", not p.active)
# Dan: "i search book and peruse in loop and nothings there" — a row in the Loops list that runs it
from types import SimpleNamespace as NS
from mudpilot.app import App, PERUSE_IID
class Tree:
    def __init__(self): self.rows, self.sel = [], ()
    def delete(self, *a): self.rows = []
    def get_children(self, parent=""): return [r[0] for r in self.rows if r[2] == parent]
    def insert(self, parent, where, iid=None, text="", values=(), open=False):
        self.rows.append((iid, text, parent)); return iid
    def selection(self): return self.sel
    def selection_set(self, x): self.sel = (x,)
class Var:
    def __init__(self, v): self.v = v
    def get(self): return self.v
logged = []
fake = NS(s=s, tree=Tree(), paths_mode=Var("loop"), add_log=logged.append)
fake._refresh_loops = lambda q: App._refresh_loops(fake, q)
fake._loop_values = lambda mp: App._loop_values(fake, mp)
for q in ("", "book", "peruse"):
    fake.paths_q = Var(q)
    App.refresh_paths(fake)
    check(f"Loops list, search '{q}': Peruse books is there, in Golden Spire",
          any(r[0] == PERUSE_IID and r[2] == "folder:Golden Spire" for r in fake.tree.rows))
fake.paths_q = Var("zzqq"); App.refresh_paths(fake)
check("…not for an unrelated search", not fake.tree.rows)
st.known_abils = {"134": 6}; p.active = None
g.candidates = [(12, 2248)]
fake.tree.sel = ()                                      # nothing picked, one match: Run takes it
fake.paths_q = Var("peruse"); App.refresh_paths(fake)
fake._selected_path = lambda: App._selected_path(fake)
App._paths_go(fake)
check(f"Run on it starts perusing ({logged})", p.active and logged and "perusing" in logged[-1])
# …and in the toolbar's Loop → "Run a loop…" picker, which is what Dan searched
from mudpilot.gotodlg import Picker as GotoDialog
dlg = NS(s=s, mode="loop")
rows = list(GotoDialog._entries(dlg))
check("Run a loop… lists Peruse books", any(it == ("routine", "peruse") and "book" in lab.lower() for g_, lab, it in rows))
logs2 = []
s.log = lambda m, *a, **k: logs2.append(m)
p.active = None
sel = ["x"]
dlg2 = NS(s=s, mode="loop", app=None, _items={"x": ("routine", "peruse")}, destroy=lambda: None,
          tree=NS(selection=lambda: sel, item=lambda i, k: "Peruse books"), q=Var("book"), _first=lambda: None)
GotoDialog.go(dlg2)
check(f"…and Run starts it ({logs2[-1:]})", p.active and "perusing" in logs2[-1])
# mirror image: the Paths tab's Loops list and Run a loop… show the same loops in the same folders
from mudpilot.megamud_files import MPath
s.paths = [MPath(name="Tidepool (Longer)", author="", start_hash="a", end_hash="a", start_group="Tidepool"),
           MPath(name="Rotting glade", author="", start_hash="b", end_hash="b", start_group="Rotting Glade"),
           MPath(name="To town", author="", start_hash="c", end_hash="d")]
for i, mp in enumerate(s.paths):
    mp.filename = f"f{i}.mp"
s.loopstats.summary = lambda k: None
for q in ("", "tide", "book", "glade"):
    fake.paths_q = Var(q); App.refresh_paths(fake)
    tab = {(r[2][7:], r[1]) for r in fake.tree.rows if r[2]}
    pick = {(g_, lab) for g_, lab, it in GotoDialog._entries(dlg)
            if __import__("mudpilot.gotodlg", fromlist=["x"]).loop_matches(q, g_, lab, it)}
    check(f"search '{q}': both lists the same ({sorted(tab)})", tab == pick and "To town" not in str(tab))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
