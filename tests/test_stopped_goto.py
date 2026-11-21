"""Revolution, 2026-10-30: walking a Go to to the Bank of Godfrey, Buddy's restart sent '@stop', then Revolution was
restarted too — he came back 'Idle' with nothing to Rego, @rego found nothing, and nothing said why he was parked.
A stopped Go to now survives a restart, @rego carries on with it, and the status says who stopped it."""
import os, sys, json, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, control
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, r = s.bot, s.remote
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


# walking the Go to; Buddy says @stop
b.walking, b.path, b._goto_target = True, MPath("Go to 1/297 Bank of Godfrey", "MudPilot", "", ""), (1, 297)
r._channel = "telepath"
r.c_stop("Buddy", "")
check(f"stopped, Rego remembers the Go to ({b.resume})", b.resume and b.resume.get("target") == (1, 297))
check(f"status says who and what ({b.idle_text()})", "Buddy" in b.idle_text() and "1/297" in b.idle_text())
check(f"@status too ({r._activity()})", "Buddy" in r._activity() and "1/297" in r._activity())
# restart: the resume file keeps it
c = s.control
tmp = os.path.join(os.environ.get("TEMP", "."), "mp_resume_test")
os.makedirs(tmp, exist_ok=True)
c.dir = tmp
written = {}
_dump = json.dump
c.write_resume()
f = os.path.join(tmp, "resume.json")
data = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}
check(f"resume file keeps the stopped Go to ({data.get('stopped_goto')})", data.get("stopped_goto") == [1, 297])
b.resume = None
c.load_resume()
check(f"…and it's back for Rego after the restart ({b.resume})", b.resume and b.resume.get("target") == (1, 297))
called = []
b.goto = lambda t, then=None, ask=None: called.append(t) or True
s.state.candidates = [(1, 224)]                # (Rego with the room unknown looks first — 0.8.162)
out = r.c_rego("Buddy", "")
check(f"@rego carries on to 1/297 ({out}, {called})", called == [(1, 297)] and "1/297" in out)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
