"""Evolution, 2026-11-21: "neutral quested characters are taking non neutral quested characters to jorah and trying
to make them ask jorah transport for the shortcut even after asking them their quest flags". Two faults:
1. the followers answered '{ability 127 = not set - …}' (they've never had NeutralQuest, so they don't know its
   name) — only the '(127) = …' form was read, so the answers were missed and the walk went ahead after 12 s;
2. even read, a 'not set' only stopped the walk when there was NO way there for them — with a longer way round,
   the original path (through 'ask Jorah transport', NeutralQuest 2+) was walked anyway.
Now the answers are read in both forms, the router checks the party's known values at quest gates, and the Go to
is worked out again when someone's flag differs."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.automation import Automation
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
out, logs, alerts = [], [], []
class T:
    connected = True
    def send_line(self, x): out.append(x)
s.telnet = T()
b.log = lambda m, *a, **k: logs.append(m)
s.log = b.log
s.on_alert = lambda m: alerts.append(m)
s.on_no_route = lambda m: alerts.append(m)
g.alignment = "Neutral"
JORAH, PIER = (1, 2327), (1, 1813)
g.candidates = [JORAH]
g.carrying = "waterskin"
g.abil_rows[("granted", 127)] = (13, time.time())
g.abil_names[127] = "NeutralQuest"
st.known_abils = {"127": 13}
real_start = Automation.start_path.__get__(b)
started = []
def start(mp, loop=None, checked=False, **k):
    if checked:
        started.append(mp); return
    return real_start(mp, loop, checked=checked)
b.start_path = start
b.missing_items = lambda mp: ([], [])
b.path_toll = lambda mp: 0
b.carry_sets = lambda mp: []
b.stop = lambda why="", **k: alerts.append(why)
def jorah(mp):
    return any("jorah" in (getattr(x, "move", "") or "").lower() for x in mp.steps or [])

# alone: the Jorah teleport is fine
started.clear()
b._flags_reread = {}
b.goto(PIER)
solo = b.path
check(f"solo NeutralQuest 13: Jorah's teleport is the way ({solo.title if solo else None})", solo and jorah(solo))

# the parser: both answer forms
from mudpilot.partyflags import ANSWER_RE
check("reads '{ability 127 = not set - …}'", [(a1 or a2, v) for a1, a2, v in
      ANSWER_RE.findall("{ability 127 = not set - next step: talk to hooded traveller}")] == [("127", "not set")])
check("still reads '{DaoLordQuest (134) = 8}'", [(a1 or a2, v) for a1, a2, v in
      ANSWER_RE.findall("{DaoLordQuest (134) = 8 - next step: …}")] == [("134", "8")])

# leading three who never did the quest
g.party = {"Evolution": {}, "Revolution": {}, "Miserable": {}, "Buddy": {}}
s.comeback.leading = lambda: True
b.path = None; b.walking = False
out.clear(); started.clear(); alerts.clear()
b.partyflags._asked = {}
b.goto(PIER)
asked = [c for c in out if "@flags" in c]
check(f"asks the party '@flags 127' ({asked})", "/Revolution @flags 127" in asked and len(asked) == 3)
for who in ("Revolution", "Miserable", "Buddy"):
    got = b.partyflags.answer(who, "{ability 127 = not set - next step: talk to hooded traveller about 'quest' "
                                   "at The Homely Hearth, Common Room}")
    check(f"{who}'s 'ability 127 = not set' is read", got)
b.partyflags.tick()
mp = started[-1] if started else b.path
check(f"walks to the pier without Jorah's teleport ({mp.title if mp else None}, alerts {alerts[-1:]})",
      mp is not None and "1/1813" in mp.title and not jorah(mp) and not alerts)
check("says why it worked the way out again", any("working the way out again" in m for m in logs))

# the party's answers keep counting for the router (no teleport the next time round either)
b.path = None; b.walking = False; started.clear()
b.goto(PIER)
mp = started[-1] if started else b.path
check(f"next Go to there: still no Jorah ({mp.title if mp else None})", mp is not None and not jorah(mp))

# someone who did the quest: Jorah again
b.partyflags.known = {n: {127: (5, time.time())} for n in ("revolution", "miserable", "buddy")}
s.world.forget_routes()
b.path = None; b.walking = False; started.clear()
b.goto(PIER)
mp = started[-1] if started else b.path
check(f"everyone on NeutralQuest 2+: Jorah's teleport again ({mp.title if mp else None})", mp is not None and jorah(mp))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
