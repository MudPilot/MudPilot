"""The Go to pilot (pilot.py): every step is planned from where we really are — no step counter to resync.
A small in-process 'real world' answers each command from the Paradigm map (moves, room actions that open
hidden walls, text exits, 'pro'), and can make a move land somewhere else."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.worlddb import DIRS, DIR_WORDS, norm_dir
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT = "[HP=684/MA=473]:"
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_spells = st.auto_bless = st.auto_rest = st.auto_heal = False
st.check_needed_items = False; st.stop_before_boss = False; st.danger_check = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
from mudpilot.automation import Automation as _A
_A.DEFAULT_PROMPT_AREAS = ()          # this file tests pilot/vortex mechanics, not the default avoid areas
b, w, g = s.bot, s.world, s.state
q = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): q.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]

# every room action, by the room it's done in: (room, command) -> [(exit room, dir)] it opens
ACT = {}
for k, r in w.rooms.items():
    for d, e in r.exits.items():
        for a in getattr(e, "actions", None) or []:
            at = tuple(a["at"]) if a.get("at") else k
            for c in a.get("cmds") or []:
                ACT.setdefault((at, c.lower()), []).append((k, d))


class Real:
    def __init__(self, k):
        self.k, self.open, self.slips, self.log = k, set(), {}, []
        self.party = []                       # who's in the party (for 'par')
        self.on_move = None                   # f(cmd, landed) -> extra lines before the room

    def show(self, k=None):
        k = k or self.k
        r = w.room(k)
        ex = [d for d, e in r.exits.items() if d in DIRS and (e.visible or (k, d) in self.open)]
        out = [PROMPT + r.name]
        if getattr(self, "here_too", None):
            out.append("Also here: " + ", ".join(self.here_too) + ".")
        out.append("Obvious exits: " + (", ".join(DIR_WORDS[d].lower() for d in ex) or "none"))
        return out

    def move(self, to, cmd):
        self.k = to
        extra = self.on_move(cmd, to) if self.on_move else []
        return (extra or []) + self.show()

    def handle(self, c):
        low = c.strip().lower()
        r = w.room(self.k)
        self.log.append((self.k, low))
        if low in ("", "l", "look"):
            return self.show()
        if low == "pro":
            return [f"You are in map {self.k[0]}, room {self.k[1]}."]
        if low in ("par", "party"):
            if not self.party:
                return ["You are not in a party at the present time."]
            return ["The following people are in your travel party:",
                    "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank"] + \
                   [f"  {n} Abil               (Druid)      [M:100%] [H:100%]  - Backrank" for n in self.party]
        if low.startswith(("@", "/", "invite ", ".")):
            return []
        m = low[3:] if low.startswith("go ") and norm_dir(low[3:]) else low
        d = norm_dir(m) if m.split() and len(m.split()) == 1 else None
        if d:
            slip = self.slips.pop((self.k, d), None)
            if slip:
                return self.move(slip, low)
            e = r.exits.get(d)
            if e and e.to in w.rooms and (e.visible or (self.k, d) in self.open) and e.kind not in ("text",):
                return self.move(e.to, low)
            return ["There is no exit in that direction!"]
        for e in r.exits.values():
            if e.kind == "text" and e.accepts(low):
                return self.move(e.to, low)
        hits = ACT.get((self.k, low))
        if hits:
            self.open |= set(hits)
            return ["You hear a grinding noise as a passage opens!"]
        if low.startswith("ask ") or low.startswith("push "):
            return [f"You don't see {low.split(' ', 1)[1]} here."]
        return ["Huh?"]


def setup(start, located=True):
    real = Real(start)
    b.stop("reset"); b.resume = None
    b.pilot.done.clear()                      # a fresh world: every wall shut again
    g.candidates = [start]
    feed(*real.show())
    g.candidates = [start]
    g.pending.clear()
    if located:
        g.located = (start, time.time())
    return real


def run(real, until, secs=30):
    end = time.time() + secs
    while time.time() < end:
        for k in list(b._cool):
            b._cool[k] = (time.time() if k in ("par", "stat", "spells", "abil") else 0)
        g.in_combat = False
        b.tick()
        while q:
            c = q.pop(0)
            feed(*real.handle(c), PROMPT)
        if until():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------- 1. a plain Go to arrives
start = (17, 1637)
far = w.route(start, (1, 297), level=47)
tgt = far[11].to
real = setup(start)
check("Go to starts", b.goto(tgt))
check("…the pilot drives it", b.pilot.on())
arrived = run(real, lambda: not b.walking)
check(f"plain Go to arrives ({real.k}, {b.status})", arrived and real.k == tgt and g.room == tgt)

# ---------------------------------------------------------------- 2. landing somewhere unexpected: plan from there
real = setup(start)
b.goto(tgt)
r0 = w.route(start, tgt, level=47)
mid = r0[3]                                   # the 4th move goes somewhere else instead
frm = r0[2].to
alt = next(e.to for d, e in w.room(frm).exits.items() if d in DIRS and e.visible and e.to != mid.to)
real.slips[(frm, mid.dir)] = alt
b.s.logs.clear() if hasattr(b.s, "logs") and isinstance(b.s.logs, list) else None
arrived = run(real, lambda: not b.walking)
logs = "\n".join(s.logs[-80:]) if isinstance(s.logs, list) else ""
check(f"knocked into {alt}: re-planned from there", f"at {alt[0]}/{alt[1]}" in logs and "planning from here" in logs)
check(f"…and still arrives ({real.k})", arrived and real.k == tgt)

# ---------------------------------------------------------------- 3. the pyramid: a wrong move into the 12/1830 dead end
P0, PT = (12, 1811), (12, 1921)
real = setup(P0)
ask_in_1830 = []
def slipped(cmd, to):
    if to == (12, 1830) and not getattr(real, "_tricked", False):
        real._tricked = True
        real._trick_pending = True
    return []
real.on_move = slipped
real.slips[((12, 1829), "E")] = (12, 1830)        # the move to 12/1834 lands in the dead end
check("pyramid Go to starts", b.goto(PT))
def watch():
    if getattr(real, "_trick_pending", False):
        # the tracker takes the dead end for its look-alike, the sphinx room
        real._trick_pending = False
        g.candidates = [(12, 1920)]
    return not b.walking
arrived = run(real, watch, secs=60)
cmds = real.log
i30 = [i for i, (k, c) in enumerate(cmds) if k == (12, 1830)]
check("the slip into 12/1830 happened", bool(i30))
check(f"…'pro' was asked there ({[c for k, c in cmds if k == (12, 1830)]})",
      any(c == "pro" for k, c in cmds if k == (12, 1830)))
check("…never 'ask sphinx fire' in 12/1830", not any(c.startswith("ask sphinx") for k, c in cmds if k == (12, 1830)))
check("…walked south out of it", any(c in ("s", "south") for k, c in cmds if k == (12, 1830)))
check(f"…and on to the sphinx: arrived at 12/1921 ({real.k}, {b.status})", arrived and real.k == PT)
check("'ask sphinx fire' only in 12/1920", all(k == (12, 1920) for k, c in cmds if c.startswith("ask sphinx")))

# ---------------------------------------------------------------- 4. remote action: push block in 12/1808 opens 12/1811's north wall
N1 = (12, 1827)
real = setup(P0)
b.goto(N1)
pushed_at = []
arrived = run(real, lambda: not b.walking, secs=30)
cmds = real.log
ip = next((i for i, (k, c) in enumerate(cmds) if c == "push block"), None)
inn = next((i for i, (k, c) in enumerate(cmds) if k == P0 and c in ("n", "north")), None)
check(f"push block done in 12/1808 ({cmds[ip] if ip is not None else None})", ip is not None and cmds[ip][0] == (12, 1808))
check("…before the north step from 12/1811", ip is not None and inn is not None and ip < inn)
check(f"…and arrives ({real.k})", arrived and real.k == N1)
# knocked about on the way to the block: carries on to it (no fresh detour, no skipping it)
real = setup(P0)
b.goto(N1)
real.slips[((12, 1802), "N")] = (12, 1801)       # on the way to 12/1808 a move puts us back a room
arrived = run(real, lambda: not b.walking, secs=30)
cmds = real.log
pushes = [k for k, c in cmds if c == "push block"]
check(f"…knocked back on the way: still pushes once, in 12/1808 ({pushes})", pushes == [(12, 1808)])
check(f"…and arrives ({real.k})", arrived and real.k == N1)
# the wall shut again: back to do it once more
real = setup(P0)
b.goto(N1)
def shut(cmd, to):
    if to == P0 and not getattr(real, "_shut", False) and (P0, "N") in real.open:
        real._shut = True
        real.open.discard((P0, "N"))
    return []
real.on_move = shut
arrived = run(real, lambda: not b.walking, secs=40)
pushes = [k for k, c in real.log if c == "push block"]
check(f"…the wall shut again: pushed again ({pushes}) and arrived ({real.k})", len(pushes) == 2 and arrived and real.k == N1)

# ---------------------------------------------------------------- 5. a vortex (text exit, teleport) brings the party through
V0 = (3, 25)
nxt = w.room((3, 681)).exits["S"].to
real = setup(V0)
real.party = ["Revolution"]
feed("The following people are in your travel party:",
     "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", PROMPT)
b.x._own_party = True
def vortex(cmd, to):
    if cmd == "go vortex":
        real.party = []
        return ["You step into the swirling vortex, and find yourself... elsewhere.",
                PROMPT + "Revolution is no longer following you.", "Your party has been disbanded."]
    return []
real.on_move = vortex
check("Go to through the vortex starts", b.goto(nxt))
run(real, lambda: real.k == (3, 681), secs=10)
sent = [c for _k, c in real.log]
check(f"'@party go vortex' said before going through ({sent})", "@party go vortex" in sent
      and sent.index("@party go vortex") < sent.index("go vortex"))
run(real, lambda: False, secs=0.5)
check("…waits on the far side for Revolution (no step on)", real.k == (3, 681) and b.walking)
real.here_too = ["Revolution"]
feed(PROMPT + "Revolution appears in a flash of light!")
run(real, lambda: any("invite revolution" in c for _k, c in real.log), secs=5)
check("…invites him back when he shows up", any("invite revolution" in c for _k, c in real.log))
check("…still waiting until he's joined", real.k == (3, 681))
feed(PROMPT + "Revolution started to follow you.")
real.party = ["Revolution"]
arrived = run(real, lambda: not b.walking, secs=10)
check(f"…then walks on and arrives ({real.k})", arrived and real.k == nxt)
real.here_too = None; real.party = []
g.party = {}

# ---------------------------------------------------------------- 6. Rego after a stop carries on to the target
real = setup(P0)
b.goto(PT)
run(real, lambda: len(real.log) > 25, secs=10)
b.stop("Stopped by you")
check("stopped part way", not b.walking and real.k != PT)
check("Rego carries on", b.rego() and b.walking and b.pilot.on())
arrived = run(real, lambda: not b.walking, secs=60)
check(f"…to the target ({real.k})", arrived and real.k == PT)

# ---------------------------------------------------------------- 7. switched off: the old walker
st.pilot_goto = False
real = setup(start)
b.goto(tgt)
check("pilot_goto off: the old walker walks it", b.walking and not b.pilot.on())
arrived = run(real, lambda: not b.walking)
check(f"…and arrives ({real.k})", arrived and real.k == tgt)
st.pilot_goto = True
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
