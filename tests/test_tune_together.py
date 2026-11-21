"""Two MudPilots in one party tune their spells together: one decides, one caster changes at a time,
and they settle instead of chasing each other."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
import mudpilot.spelltune as SPT
from mudpilot.session import Session
from mudpilot.ansi import Style


class Clock:
    t = 1_000_000.0
    def time(self): return self.t
CLK = Clock()
SPT.time = CLK          # the tuner's view of time (kill durations)

LADDER = [(400, 40, "magm"), (250, 20, "dfir"), (120, 10, "fbol")]   # dmg/round, mana/cast
MON_HP = 500
ROUND = 5.0

sessions = {}
def make(name):
    st = config.Settings(); st.save = lambda: None
    st.my_name = name; st.party_sync = True; st.spell_efficiency = True
    s = Session(st); s._no_log_file = True
    class Tel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x, s=s): route(s, x)
        def close(self): self.connected = False
    s.telnet = Tel(); s._want_connected = True; s._entered = True
    s.state.party = {"Dan": {}, "Revolution": {}}
    s.state.max_ma, s.state.ma = 10_000, 10_000
    s.bot._cast_target = "Cave Bear"; s.bot._last_spell = 1
    s.spelltune.note_ladder("cave bear", len(LADDER))
    sessions[name] = s
    return s

def route(src, line):
    """A telepath from one MudPilot shows up on the other's screen."""
    if not line.startswith("/"):
        return
    to, _, msg = line[1:].partition(" ")
    dst = sessions.get(to.capitalize())
    if dst:
        dst._line([(f"{src.settings.my_name} telepaths: {msg}", Style())])

def feed(s, *ls):
    for l in ls:
        s._line([(l, Style())])

dan, rev = make("Dan"), make("Revolution")
dan.bot.x._own_party = True            # Dan leads
rev.bot.x._following = "Dan"
# party sync handshake (normally partysync.tick does this)
dan.partysync.tick(); rev.partysync.tick()
print("Dan sees peers:", dan.spelltune.mudpilot_peers(), "| roles:", dan.spelltune.role(), rev.spelltune.role())

history = []
for kill in range(160):
    kd, kr = dan.spelltune.level("cave bear"), rev.spelltune.level("cave bear")
    kd, kr = min(kd, 2), min(kr, 2)
    dd, cd, _ = LADDER[kd]
    dr, cr, _ = LADDER[kr]
    rounds = math.ceil(MON_HP / (dd + dr))
    # round 1 damage lines, both screens
    feed(dan, f"Your {LADDER[kd][2]} hits the cave bear for {dd} damage!", f"Revolution's {LADDER[kr][2]} hits the cave bear for {dr} damage!")
    feed(rev, f"Your {LADDER[kr][2]} hits the cave bear for {dr} damage!", f"Dan's {LADDER[kd][2]} hits the cave bear for {dd} damage!")
    dan.state.ma -= cd * rounds; rev.state.ma -= cr * rounds
    feed(dan, "[HP=900/MA=%d]:" % dan.state.ma); feed(rev, "[HP=900/MA=%d]:" % rev.state.ma)
    dan.spelltune.feed_line(""); rev.spelltune.feed_line("")
    CLK.t += rounds * ROUND
    feed(dan, "You gain 100 experience."); feed(rev, "You gain 100 experience.")
    CLK.t += 3
    dan.state.ma = rev.state.ma = 10_000
    dan.spelltune._last_ma = rev.spelltune._last_ma = 10_000
    history.append((kd, kr))

changes = sum(1 for a, b in zip(history, history[1:]) if a != b)
both_at_once = sum(1 for a, b in zip(history, history[1:]) if a[0] != b[0] and a[1] != b[1])
final = history[-1]
print("levels over time:", history[::6])
print("changes:", changes, "| both changed at once:", both_at_once, "| final:", final)
print("\n".join(l for l in dan.logs if "Spell efficiency" in l))
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
check("Dan coordinates, Revolution follows", dan.spelltune.role() == "coord" and rev.spelltune.role() == "follow")
check("never both changing at the same time", both_at_once == 0)
check("settles on dfir + dfir (one-round kills, half the mana)", final == (1, 1))
check("stays settled (last 40 kills unchanged)", len(set(history[-40:])) == 1)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
