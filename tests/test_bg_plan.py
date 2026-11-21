"""Dan, 2026-10-30: Goto turned the window white ('Not Responding') for 15 s while it planned; and a remote @goto
should ask the one who sent it about the route ('take Negative Power Plane? reply y or n'). bgplan runs the plan on
a worker thread; sends wait in a queue until the window's thread plays them back."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
jobs = []                                   # a stand-in for Tk's after / mainloop


def after(ms, fn):
    jobs.append((time.time() + ms / 1000, fn))


def run(secs):
    end = time.time() + secs
    while time.time() < end:
        jobs.sort(key=lambda j: j[0])
        if jobs and jobs[0][0] <= time.time():
            jobs.pop(0)[1]()
        time.sleep(0.005)


s.tk_after = after
r = s.remote
r._channel = "telepath"


def fake_goto(target, ask=None, then=None):
    s.send("thinking")                      # deferred while planning
    return ask(120, 150, "Negative Power Plane")


s.bot.goto = fake_goto
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


out = r._goto_bg("Dan", (1, 297), "Bank of Godfrey (1/297)")
check(f"answers straight away ({out})", "one moment" in out)
check("the bot sits out while it plans", s.bot._planning)
run(0.3)
check(f"asks Dan y or n ({sent})", any("reply y or n" in c and c.startswith("/Dan") for c in sent))
check("sends were played back in order", sent and sent[0] == "thinking")
check("Dan's plain 'y' is the answer", r.feed_line("Dan telepaths: y"))
run(0.3)
check(f"…then walks ({sent[-1]})", "walking to Bank of Godfrey" in sent[-1])
check("planning over", not s.bot._planning)
s.send("x")
check("send put back", sent[-1] == "x")
check("a 'y' nobody asked for is just chat", not r._route_answer("Dan", "y"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
