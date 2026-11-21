"""Dan, 2026-11-04: "why wont buddy goto pharoah" — Buddy had done the withered old man (DaoLordQuest 134 = 9 in the
game) but MudPilot still had 8, and at 8 the arches on the Great Pyramid's 4th level throw you to a random room. It
said "No walkable route … blocked by … (Cast: pre-0, post-702)" and didn't go. Now: no way there → read 'abil' again
once and plan again; the route memory knows every quest flag (it only knew 133); and the message says what the exit
does and what flags MudPilot has."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
out, logs, alerts, walks = [], [], [], []
class T:
    connected = True
    def send_line(self, x): out.append(x)
s.telnet = T()
b.log = lambda m, *a, **k: logs.append(m)
s.log = b.log
s.on_alert = lambda m: alerts.append(m)
s.on_no_route = lambda m: alerts.append(m)
b.start_path = lambda mp, loop=None, **k: walks.append(mp.title)
g.alignment = "Good"
g.candidates = [(12, 1263)]
g.carrying = "mithril helm (Head), waterskin"
def flag(v):
    g.abil_rows[("granted", 134)] = (v, time.time())
    g.abil_names[134] = "DaoLordQuest"
    st.known_abils = {"134": v}
PHARAOH = (12, 2085)
flag(8)
r = b.goto(PHARAOH)
check(f"at 8: no way — reads 'abil' again instead of giving up ({out[-1:]})", r and out[-1:] == ["abil"]
      and not walks and b._pending_abil and not alerts)
# the game answers: 9 (the old man was done)
flag(9)
b._pending_abil = (b._pending_abil[0], None, None, time.time() - 5)
pa = b._pending_abil
b._pending_abil = None
b.replan(pa[0], then=pa[1], ask=pa[2])
check(f"…with 9 it goes (the route memory doesn't hand back the old 'no way') ({walks})",
      walks and "12/2085" in walks[0])
# genuinely 8: says why, in words, with the flags
walks.clear(); alerts.clear()
flag(8)
b._flags_reread = {PHARAOH: time.time()}               # (read a moment ago)
b.goto(PHARAOH)
msg = alerts[-1] if alerts else ""
check(f"really 8: no walk, and tells you ({msg[:90]}…)", not walks and msg.startswith("No walkable route"))
check("…what the exit does, not '(Cast: pre-0, post-702)'", "pyramid 4 arch fail" in msg and "post-702" not in msg)
check("…and the quest flags it went by, with the next step", "DaoLordQuest (134) = 8" in msg and "withered old man" in msg)
# only once in a while per place: no 'abil' loop
out.clear()
b.goto(PHARAOH)
check("doesn't ask 'abil' again straight away", "abil" not in out)
# leading the party: Dan — "cant go revolution is on dao 8 and dao 9 is required or something like that"
from mudpilot.automation import Automation
real_start = Automation.start_path.__get__(b)
started = []
def start(mp, loop=None, checked=False, **k):
    if checked:
        started.append(mp.title); return
    return real_start(mp, loop, checked=checked)
b.start_path = start
b.missing_items = lambda mp: ([], [])
b.path_toll = lambda mp: 0
b.carry_sets = lambda mp: []
st.check_needed_items = True
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
s.comeback.leading = lambda: True
stopped = []
b.stop = lambda why="", **k: stopped.append(why)
def lead(rev, evo):
    out.clear(); alerts.clear(); started.clear(); stopped.clear()
    b.partyflags._asked = {}
    flag(9)
    b._flags_reread = {}
    b.goto(PHARAOH)
    asked = [c for c in out if "@flags" in c]
    b.partyflags.answer("Revolution", "{DaoLordQuest (134) = %s - next step: …}" % rev)
    b.partyflags.answer("Evolution", "{DaoLordQuest (134) = %s}" % evo)
    b.partyflags.tick()
    return asked
asked = lead(8, 9)
check(f"asks the party '@flags 134' before going ({asked})", "/Revolution @flags 134" in asked and "/Evolution @flags 134" in asked)
msg = alerts[-1] if alerts else ""
check(f"Revolution on 8: doesn't go, says so ({msg})", not started and stopped
      and "Revolution is on DaoLordQuest 8 (you're on 9)" in msg and "Evolution" not in msg)
lead(9, 9)
check(f"everyone on 9: off it goes ({started})", started and "12/2085" in started[0] and not alerts)
lead("not set", 9)
check(f"Revolution never started it: says so ({alerts[-1:]})", alerts and "Revolution has no DaoLordQuest (you're on 9)" in alerts[-1])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
