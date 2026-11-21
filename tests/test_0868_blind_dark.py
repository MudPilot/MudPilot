"""0.8.168 (Dan, 2026-11-09, Great Pyramid): 'pro' set the map on 12/1993, then — blind — 's s e e s s' each got
"You are blind." and the map stayed put, six steps behind. And on level 2 (pitch black) moves typed ahead each went
from where we were when typed, so 's s' landed on the same room: two rooms off. Both followed now."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, g = s.world, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def line(t):
    s._line([(t, Style())])
def walk(start, moves):
    cur = start
    for m in moves:
        cur = w.rooms[cur].exits[m.upper()].to
    return cur
# level 2 of the pyramid, as the bot walked it (12/1921 → 12/1991), all pitch black
lvl2 = "s e s e e n w n n n e n e n w w w w s w n w w".split()
g.candidates = [(12, 1921)]
for i in range(0, len(lvl2), 2):                     # two at a time, typed before the answers
    pair = lvl2[i:i + 2]
    for m in pair:
        g.note_command(m)
    for _m in pair:
        line("The room is pitch black - you can't see anything")
        line("[HP=657/MA=491]:")
want = walk((12, 1921), lvl2)
check(f"pitch black, moves typed ahead: on the right room ({g.candidates} vs {want})", g.candidates == [want])
# Enter's answer in the dark isn't a move's
g.candidates = [(12, 1921)]
g.note_command("")
g.note_command("s")
line("The room is pitch black - you can't see anything")
check(f"…Enter's 'pitch black' doesn't move us ({g.candidates})", g.candidates == [(12, 1921)])
line("[HP=657/MA=491]:The room is pitch black - you can't see anything")
check(f"…the move's does ({g.candidates})", g.candidates == [walk((12, 1921), ["s"])])
# blind after 'pro': 's s' then 'e e' (the real moves after 12/1993 — wherever the map has them go)
start = (12, 1993)
g.candidates = [start]
moves = [m for m in ("s", "s", "e", "e", "s", "s")]
cur, legal = start, []
for m in moves:
    e = w.rooms[cur].exits.get(m.upper())
    if e is None:
        break
    legal.append(m); cur = e.to
for m in legal:
    g.note_command(m)
for _m in legal:
    line("[HP=583/MA=491]:You are blind.")
check(f"blind: {len(legal)} moves answered 'You are blind.' are followed ({g.candidates} vs {cur})",
      legal and g.candidates == [cur])
g.candidates = [start]
g.note_command("")
line("You are blind.")
check("…Enter's 'You are blind.' doesn't move us", g.candidates == [start])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
