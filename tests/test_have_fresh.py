"""Dan, 2026-11-01: Buddy gave Revolution a log raft, asked '@have log raft' and got "no" (Revolution answered from
the inventory it read before the raft came) — so Buddy bought and handed out another. @have re-reads 'i' when the
pack may have changed. And a wrapped listing ("2" / "log raft") answers "yes: 2 log raft", not "yes: 2"."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
r = s.remote
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


s.state.carrying = "51 gold crowns, mace (Weapon Hand), rope and grapple"
r._inv_dirty = False
check("nothing changed: answers straight away", r.c_have("Buddy", "log raft") == "no log raft")
r.feed_line("Buddy gives you log raft.")
sent.clear()
out = r.c_have("Buddy", "log raft")
check(f"handed something: reads 'i' first, no answer yet ({out}, {sent})", out is None and "i" in sent)
s.state.carrying = "51 gold crowns, mace (Weapon Hand), rope and grapple, 2\nlog raft"
answers = []
r.reply = lambda ch, who, line: answers.append(line)
r.inv_answer()
check(f"…then answers from the fresh one, wrapped line joined ({answers})", answers == ["yes: 2 log raft"])
check("…and the next @have needs no 'i'", r.c_have("Buddy", "log raft") == "yes: 2 log raft")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
