"""Dan, 2026-10-28: Goto Dark-Elf City — "the only way goes through Negative Power Plane. Go through it?" He clicks
No and it pops up again, and again. Now: a No is remembered for the trip (no re-ask), and when the only way is the
avoided area the Go to stops cleanly instead of re-prompting / fetching keys."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot import board_fixes
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 45   # (0.8.225: NPP is only avoided under level 50)
st.avoid_names = ["Negative Power Plane"]; st.avoid_mode = "ask"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
board_fixes.apply(s.world)
b, g = s.bot, s.state
w = s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b.held_items = lambda: set()
g.candidates = [(1, 348)]
g.view = RoomView("Adventurer's Guild, Foyer", {"E", "W"}, [], [], [], time.time()); g.view_seq += 1
target = (8, 493)                                   # Dark-elf Prison — only MME way is through NPP
asked = []
def ask_no(short, scenic, area):
    asked.append(area); return False               # the user clicks "No"
# 0.8.189: with the orb fetchable there's a way in without Black Wasteland (the Fungus Tunnel) — no prompt
r = b.plan_route((1, 348), target, ask_no)
av = b.avoid_set()
check(f"fetching the orb: a way round, no prompt ({len(asked)})", r is not None and not asked
      and not any(ex.to in av for ex in r))
# nothing fetchable: the only way is through the Negative Power Plane — 0.8.225 (Dan): under level 50 NPP is
# avoided unless it's the only way, and then it goes: no question, no refusal
b.errands.source_for = lambda n: None; b._opener_ok = {}
r = b.plan_route((1, 348), target, ask_no)
check(f"only way is NPP (level 45): goes, no prompt ({len(asked)} prompts)", r is not None and not asked)
r = b.plan_route((1, 348), target, ask=None)
check("…and the same unattended (ask=None)", r is not None and not asked)
# from level 50 NPP isn't avoided at all
g.level = st.char_level = 55
check("level 55: NPP not in the avoid set", not any(w.room(k) and "negative power plane" in w.room(k).name.lower()
                                                     for k in b.avoid_set()))
g.level = st.char_level = 45
# a place whose route crosses no prompt area still routes with no prompt (a short hop in town)
asked.clear(); b._trip_deny = {}
dest = next(((1, rm) for rm in (297, 309, 1, 310) if w.room((1, rm))
             and not any(ex.to in b.avoid_set() for ex in (w.route((1, 348), (1, rm), level=55) or []))), (1, 297))
r = b.plan_route((1, 348), dest, ask_no)
check(f"a town hop routes with no prompt ({dest}, {len(asked)})", r is not None and not asked)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
