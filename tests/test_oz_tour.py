"""Dan, 2026-11-06: the Go to to Ozrinom (17/2243) typed 'twist hand' AND 'twist sword' in 17/2094 and walked on —
17/2068's way down needs the hand twisted in 17/2094 and then the sword in 17/2076. The Go to walker (pilot.py)
did a remote-action detour to the first room only; each action now goes in its own room, in order (as
megamud_files.path_from_route already did). Also: a re-plan kept the old plan's lever-gate step numbers, so
'Running for the gate' fired mid-fight in the wrong place."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import STEPF
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 57
st.check_needed_items = False; st.danger_check = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b = s.world, s.bot
p = b.pilot
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def fresh(target):
    p.target, p.done, p.prog, p.pending, p._rush = target, {}, {}, None, []


OZ = (17, 2243)
fresh(OZ)
route = b.plan_route((17, 246), OZ)
check("there's a way to Ozrinom", route is not None)
steps = p._steps((17, 246), route)
acts = [(x.room, x.pre) for x in steps if x.pre and not x.pre[0].startswith("search")]
want = [((17, 2094), ["twist hand"]), ((17, 2076), ["twist sword"]),
        ((17, 2161), ["push eye"]), ((17, 2156), ["twist sword"])]
check(f"hand in 2094, sword in 2076, eye in 2161, sword in 2156 ({acts[:4]})", acts[:4] == want)
check("the Dark Sanctum letters in their own rooms",
      [x[0] for x in acts[4:]] == [(17, 2242), (17, 2240), (17, 2237), (17, 2235)])
down = [i for i, x in enumerate(steps) if x.room == (17, 2068) and x.move == "D"]
check("down from 2068 only after the sword", down and down[0] > steps.index(next(x for x in steps if x.pre == ["twist sword"])))
check("Ozrinom's doors aren't a run-don't-fight gate", p._rush == [] and
      not any(x.flags & STEPF["NOATTACK"] for x in steps))

# knocked about after the hand, before the sword: carry on to the sword — don't twist the hand again
fresh(OZ)
key = ((17, 2068), "D")
hand = next(x for x in steps if x.pre == ["twist hand"])
p.pending = hand._pilot_detour
p.prog[key] = (1, time.time())
plan = p._build((17, 2093))
pres = [(x.room, x.pre) for x in plan if x.pre and not x.pre[0].startswith("search")]
check(f"picks up at the sword ({pres[:2]})", pres[0] == ((17, 2076), ["twist sword"]))
check("…and doesn't twist the hand again", ((17, 2094), ["twist hand"]) not in pres)

# the step that does the last action marks the door opened
fresh(OZ)
plan = p._steps((17, 246), route)
sw = next(x for x in plan if x.pre == ["twist sword"])
check("the sword step finishes 2068's actions", sw._pilot_action == (key, 2))
check("the hand step is the first of two", next(x for x in plan if x.pre == ["twist hand"])._pilot_action == (key, 1))

# the mummy's gate is still a run (Dan, 2026-10-30)
fresh((1, 1063))
mr = b.plan_route((1, 1055), (1, 1063))
ms = p._steps((1, 1055), mr)
check(f"mummy levers each in their room ({[(x.room, x.pre) for x in ms if x.pre]})",
      [(x.room, x.pre) for x in ms if x.pre] == [((1, 1038), ["pull lever"]), ((1, 1044), ["pull lever"])])
r = p._rush[0] if p._rush else None
check("mummy gate: a run from the first lever to the gate",
      r and ms[r["first"]].pre == ["pull lever"] and ms[r["gate"]].move == "N"
      and all(x.flags & STEPF["NOATTACK"] for x in ms[r["first"]:r["gate"] + 1]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
