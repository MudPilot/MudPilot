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
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
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
# nothing fetchable: the only way is through the avoided area again
b.errands.source_for = lambda n: None; b._opener_ok = {}
r = b.plan_route((1, 348), target, ask_no)
check(f"only way is NPP, said no → no route ({len(asked)} prompts)", r is None and len(asked) == 1)
# a re-plan on the way (no one to ask: ask=None) must NOT pop the question again
r = b.plan_route((1, 348), target, ask=None)
check(f"re-plan (ask=None) doesn't pop the question again ({len(asked)} prompts total)", len(asked) == 1)
# the bot carrying on (ask=None) stops cleanly with a message, doesn't start walking
stopped = []
b.stop = lambda why="": stopped.append(why)
b.start_path = lambda *a, **k: stopped.append("WALKED")
s.on_alert = lambda m: None
res = b.goto(target, ask=None)
check(f"goto stops cleanly, no walking ({b.no_route_msg!r})", res is False and "WALKED" not in stopped
      and any(area in (b.no_route_msg or "") for area in ("Negative Power Plane", "Black Wasteland")))
check("…and no extra prompt from the unattended carry-on", len(asked) == 1)
# a place whose route crosses no prompt area still routes with no prompt (a short hop in town)
asked.clear(); b._trip_deny = {}
dest = next(((1, rm) for rm in (297, 309, 1, 310) if w.room((1, rm))
             and not any(ex.to in b.avoid_set() for ex in (w.route((1, 348), (1, rm), level=55) or []))), (1, 297))
r = b.plan_route((1, 348), dest, ask_no)
check(f"a town hop routes with no prompt ({dest}, {len(asked)})", r is not None and not asked)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
