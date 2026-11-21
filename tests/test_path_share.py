"""Dan, 2026-11-01: send the loop I just drew to Evolution so he can lead it — start room and steps, over telepath
(the game is the only link between the MudPilots). Pieces fit on one line (the game wraps at ~80), are numbered so the
other side knows when it has them all, and are rebuilt over its own map."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    s.telnet.sock = object()
    out = []
    s.send = lambda c, from_bot=False: out.append(c)
    return s, out


buddy, bout = make("Buddy")
evo, eout = make("Evolution")
saved = []
evo.save_path = lambda mp, fn: saved.append((mp, fn))
w = buddy.world
a, b = (1, 3), (1, 16)
mp = path_from_route(w, a, w.route(a, b) + w.route(b, a), name="Town loop")
mp.steps[2].pre = ["search"]
check(f"a loop to send ({len(mp.steps)} steps)", mp.is_loop and len(mp.steps) > 10)
buddy.pathshare.send(mp, "Evolution")
buddy.pathshare.out = [(0, c) for _t, c in buddy.pathshare.out]
buddy.pathshare.tick()
pieces = [c for c in bout if "@mpsync path" in c]
lines = [c.replace("/Evolution ", "Buddy telepaths: ", 1) for c in pieces]
check(f"sent in {len(pieces)} numbered pieces, each one game line (longest {max(len(x) for x in lines)})",
      len(pieces) > 1 and all(len(x) <= 80 for x in lines) and pieces[-1].split()[4] == f"{len(pieces)}/{len(pieces)}")
evo.state.party = {"Evolution": {}, "Buddy": {}}
answers = []
for i, c in enumerate(pieces):
    args = c.split(" @mpsync ", 1)[1]
    r = evo.partysync.command("Buddy", args)
    if r:
        answers.append((i, r))
check(f"nothing built until the last piece is in ({answers})", len(answers) == 1 and answers[0][0] == len(pieces) - 1)
got = saved[0][0] if saved else None
check(f"rebuilt: same start, same steps, a loop ({got and len(got.steps)})",
      got and got.is_loop and got.steps[0].room == a and [s.move for s in got.steps] == [s.move for s in mp.steps])
check("…commands kept (search before step 3)", got and got.steps[2].pre == ["search"])
check(f"answer says so ({answers and answers[0][1]})", answers and answers[0][1].startswith("got loop 'Town loop'"))
# a stranger can't push paths
saved.clear()
evo.state.party = {"Evolution": {}}
for c in pieces:
    r = evo.partysync.command("Stranger", c.split(" @mpsync ", 1)[1])
check(f"not from someone outside the party / not allowed ({r})", not saved and "not taking" in (r or ""))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
