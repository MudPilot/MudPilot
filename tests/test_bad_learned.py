"""0.8.54: a learned 'ask sphinx fire' from the 12/1830 dead end (a guess between look-alike rooms) sent every
pyramid Go to into the dead end. Not learned any more, dropped on load, and forgotten the moment it fails."""
import os, sys, time, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_spells = st.auto_bless = st.auto_rest = st.auto_heal = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
check("12/1830 and 12/1920 are look-alikes", w.look_alike((12, 1830)) and w.look_alike((12, 1920)))
# the old bad row, as it sits in learned_exits.json
d = tempfile.mkdtemp(); f = os.path.join(d, "learned_exits.json")
json.dump([[[12, 1830], "ask sphinx fire", [12, 1920]], [[10, 168], "say travel", [10, 201]]], open(f, "w"))
type(s).learned_file = property(lambda self: f)
s._load_learned()
check("on load: the look-alike guess is dropped", not any(r[1] == "ask sphinx fire" for r in w.learned))
check("…the file is cleaned too", not any(r[1] == "ask sphinx fire" for r in json.load(open(f))))
# if one slips in anyway (an older map): a failure forgets it and the Go to plans again
w.learned = []
check("a MegaMUD path / the tracker can't teach it again", not w.add_learned((12, 1830), "ask sphinx fire", (12, 1920)))
from mudpilot.worlddb import Exit
r_ = w.rooms[(12, 1830)]
r_.exits = {**r_.exits, "@ask sphinx fire": Exit("@ask sphinx fire", (12, 1920), "(Text: ask sphinx fire) (Learned)", False, False, "text")}
w.learned = [[[12, 1830], "ask sphinx fire", [12, 1920]]]
r = w.route((12, 1811), (12, 1921), level=47)
check("with the bad way the route uses it", any(getattr(e, "kind", "") == "text" and e.to == (12, 1920) for e in r))
mp = path_from_route(w, (12, 1811), r, name="Go to 12/1921")
g.candidates = [(12, 1811)]
b.start_path(mp, loop=False, checked=True); b._goto_target = (12, 1921)
b.idx = next(i for i, x in enumerate(mp.steps) if x.room == (12, 1830)) + 1
b._action_sent_at = time.time()
feed("You don't see sphinx fire here.")
check("…'You don't see sphinx fire here' forgets it", not any(x[1] == "ask sphinx fire" for x in w.learned)
      and not any("(Learned)" in (e.etype or "") for e in w.rooms[(12, 1830)].exits.values()))
r2 = w.route((12, 1811), (12, 1921), level=47)
check(f"…and the new route goes west at 12/1828", r2 and any(e.to == (12, 1831) for e in r2))
check("…the Go to is planned again", getattr(b, "_regoto_at", 0) > 0)
# pro beats the path's guess
g.candidates = [(12, 1830)]; g.located = ((12, 1830), time.time())
b._expect_dest = ((12, 1921), g.view_seq - 1, (12, 1920))
b._confirm_arrival()
check("'pro' said 12/1830: the path doesn't place us at 12/1921", g.candidates == [(12, 1830)])
# 'pro' relocating the tracker got learned as a way from 12/124 to 12/129 — and every route used it
check("'pro' is never learned as a way", not w.add_learned((12, 124), "pro", (12, 129)))
json.dump([[[12, 124], "pro", [12, 129]], [[12, 124], ".pro", [12, 129]]], open(f, "w"))
s._load_learned()
check("…and old 'pro' rows are dropped on load", not any(r[1].lstrip(".") == "pro" for r in w.learned))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
